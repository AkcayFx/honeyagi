"""Exercise the plain-JS continuation controls with Node's VM and a minimal DOM."""
import shutil
import subprocess
from pathlib import Path
import pytest

HARNESS = r"""
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const elements=new Map();
function element(id){
  if(!elements.has(id))elements.set(id,{id,value:'',checked:false,textContent:'',disabled:false,hidden:false,className:''});
  return elements.get(id);
}
const env={document:{getElementById:element,querySelectorAll:()=>[element('continue-button'),element('generate-button')]},
  crypto:{randomUUID:()=> 'test-request-'+(++env.sequence)},sequence:0,setTimeout,clearTimeout};
vm.createContext(env);
vm.runInContext(fs.readFileSync('app/static/app.js','utf8'),env);
function run(code){return vm.runInContext(code,env);}
run("state.selected='a';state.assessment={planning_progress:{status:'ready',steps_used:1,max_steps:4,can_continue:true}};");
(async()=>{
SCENARIO
})().catch(error=>{console.error(error);process.exitCode=1;});
"""


def run_js(scenario):
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node is required for dashboard behavior checks")
    result = subprocess.run([node, "-e", HARNESS.replace("SCENARIO", scenario)],
                            cwd=Path(__file__).resolve().parents[1], capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stdout + result.stderr


def test_progress_disables_button_even_after_task_cleanup():
    run_js(r"""
    for(const status of ['not_started','generating','awaiting_actions','finished','budget_reached','blocked']){
      run("state.assessment.planning_progress.status='"+status+"';state.assessment.planning_progress.can_continue=false;renderPlanningProgress();");
      assert.equal(element('continue-button').disabled,true);
      await run('task(async()=>{})');
      assert.equal(element('continue-button').disabled,true);
      assert.match(element('planning-progress').textContent,/1 \/ 4/);
    }
    run("state.assessment.planning_progress.status='ready';state.assessment.planning_progress.can_continue=true;renderPlanningProgress();");
    assert.equal(element('continue-button').disabled,false);
    """)


def test_lost_response_retry_reuses_uuid_and_never_approves_or_executes():
    run_js(r"""
    const calls=[];env.testApi=async(path,method,data)=>{
      calls.push({path,method,data});
      if(calls.length===1)throw Error('Connection lost');
      return {action_ids:[],summary:'No more checks'};
    };
    run("api=testApi;refresh=async()=>{state.assessment.planning_progress={status:'finished',steps_used:2,max_steps:4,can_continue:false};};");
    await element('continue-button').onclick();
    assert.equal(calls.length,1);
    assert.equal(element('continue-button').disabled,false);
    assert.equal(element('continue-button').textContent,'Retry continuation');
    const first=calls[0].data.request_id;
    await element('continue-button').onclick();
    assert.equal(calls.length,2);
    assert.equal(calls[1].data.request_id,first);
    for(const call of calls){
      assert.equal(call.path,'/assessments/a/continue');assert.equal(call.method,'POST');
      assert.deepEqual(Object.keys(call.data),['request_id']);
    }
    assert.equal(element('continue-button').disabled,true);
    assert.match(element('notice').textContent,/No further checks proposed/);
    """)


def test_server_denial_does_not_automatically_retry():
    run_js(r"""
    let calls=0;env.testApi=async()=>{calls++;const error=Error('Step limit');error.status=409;throw error;};
    run("api=testApi;refresh=async()=>{state.assessment.planning_progress={status:'budget_reached',steps_used:4,max_steps:4,can_continue:false};};");
    await element('continue-button').onclick();
    assert.equal(calls,1);
    assert.equal(element('continue-button').disabled,true);
    assert.equal(run('Object.keys(state.continueRequests).length'),0);
    """)


def test_overlapping_clicks_issue_one_request_and_waiting_actions_remain_disabled():
    run_js(r"""
    let calls=0,release;
    env.testApi=()=>{calls++;return new Promise(resolve=>{release=resolve;});};
    run("api=testApi;refresh=async()=>{state.assessment.planning_progress={status:'awaiting_actions',steps_used:2,max_steps:4,can_continue:false};};");
    const first=element('continue-button').onclick();
    await element('continue-button').onclick();
    assert.equal(calls,1);
    release({action_ids:['pending-check']});await first;
    assert.equal(element('continue-button').disabled,true);
    assert.match(element('notice').textContent,/Review and approve/);
    """)
