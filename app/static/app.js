'use strict';
const $ = id => document.getElementById(id);
const state = {token: '', assessments: [], selected: null, assessment: null, report: null, busy: false, plannerInfo: null, planRequest: null};
function node(tag, text, className) { const n = document.createElement(tag); if (text !== undefined) n.textContent = text; if (className) n.className = className; return n; }
function notify(message, error=false) { $('notice').textContent=message; $('notice').className='notice'+(error?' error':''); $('notice').hidden=false; }
async function api(path, method='GET', data) {
  const response=await fetch('/api/v1'+path,{method,headers:{Authorization:'Bearer '+state.token,...(method==='POST'?{'Content-Type':'application/json'}:{})},...(method==='POST'?{body:JSON.stringify(data||{})}:{})});
  const result=await response.json();
  if(!response.ok) { if(response.status===401) $('connect-panel').hidden=false; const error=new Error(typeof result.detail==='string'?result.detail:(result.detail?.message||'Please check the form values.')); error.status=response.status; throw error; }
  return result;
}
async function task(work) {
  if(state.busy) return;
  state.busy=true;
  document.querySelectorAll('button').forEach(b=>b.disabled=true);
  try { await work(); } catch(e) { notify(e.message,true); }
  finally { state.busy=false; document.querySelectorAll('button').forEach(b=>b.disabled=false); }
}
function renderAssessments() {
  const list=$('assessment-list');
  if(!state.assessments.length) return;
  list.replaceChildren();
  for(const a of state.assessments) { const b=node('button',undefined,'assessment-item'+(a.id===state.selected?' selected':'')); b.append(node('strong',a.name),node('span',a.targets.length+' targets · '+new Date(a.created_at).toLocaleDateString())); b.onclick=()=>task(()=>select(a.id)); list.append(b); }
}
function control(label, className, work) { const b=node('button',label,className); b.type='button'; b.onclick=()=>task(work); return b; }
function renderPlans() {
  $('planner-panel').hidden=false;
  const info=state.plannerInfo;
  $('planner-badge').textContent=info?.live_ai?'AI · '+info.model:'RULE-BASED · OFFLINE';
  $('planner-help').textContent=info?.live_ai?'Your goal and scoped check list are sent to the configured model. You may also include compact observations from prior checks. It proposes header checks; review and approve each proposal before running it.':'The offline baseline planner proposes header checks for unchecked URLs in scope. Review and approve each proposal before running it.';
  $('planner-footer').textContent=info?.live_ai?'LLM planner configured · '+info.model:'Rule-based planning · no model requests';
  const list=$('plan-list'); list.replaceChildren();
  const plans=state.assessment.plans||[];
  if(!plans.length)return;
  list.append(node('div','RECENT PLANS','plan-history-label'));
  for(const plan of plans.slice(0,5)) {
    const record=node('article',undefined,'plan-record'), meta=node('div',undefined,'plan-meta');
    const labels={completed:'Proposals ready',running:'Generating',denied:'Plan denied',failed:'Planning failed'};
    meta.append(node('span',labels[plan.status]||plan.status,'status '+plan.status),node('span',plan.action_ids.length+' proposed checks'),node('span',new Date(plan.created_at).toLocaleString()));
    record.append(meta,node('p',plan.goal,'plan-goal'),node('p',plan.summary||(plan.status==='running'?'Planning is in progress. Refresh to check its status.':'No checks were created. Generate a new plan to try again.')));
    const provenance=node('details'), summary=node('summary','Planner source');
    provenance.append(summary,node('p',plan.provider+' · '+plan.model));
    if(plan.evidence_context)provenance.append(node('p',plan.evidence_context.observations.length+' prior observations included · '+plan.evidence_context.omitted_count+' older observations omitted'));
    record.append(provenance);list.append(record);
  }
}
function renderActions() {
  const a=state.assessment;
  $('selected-name').textContent=a.name;
  $('selected-scope').textContent=a.targets.length+' exact URLs in scope · HTTP header checker';
  $('proposal-form').hidden=false; $('export-button').hidden=false;
  const target=$('proposal-target'), old=target.value; target.replaceChildren();
  for(const t of a.targets) { const option=node('option',t); option.value=t; target.append(option); }
  if(a.targets.includes(old)) target.value=old;
  const list=$('action-list'); list.replaceChildren();
  if(!a.actions.length) list.append(node('p','No actions yet. Propose your first header check.','muted'));
  for(const action of a.actions) {
    const card=node('article',undefined,'action-card'), title=node('div',undefined,'action-title');
    title.append(node('strong',action.parent_id?'HTTP header check · retest':'HTTP header check'),node('span',action.status,'status '+action.status));
    card.append(title,node('p',action.target,'action-target'),node('p',action.rationale,'action-rationale'));
    if(action.plan_id)card.append(node('p','Generated by a plan · operator review required','source-label'));
    const controls=node('div',undefined,'action-controls');
    const decide=async verb=>{await api('/actions/'+action.id+'/'+verb,'POST',{}); await refresh(); notify(verb==='approve'?'Approved. Select Run check to execute.':'Proposal rejected.');};
    if(action.status==='pending') controls.append(control('Approve','primary',()=>decide('approve')),control('Reject','reject',()=>decide('reject')));
    if(action.status==='approved') controls.append(control('Run check','primary',async()=>{notify('Running the approved header check…'); const result=await api('/actions/'+action.id+'/execute','POST',{}); await refresh(); notify(result.status==='completed'?'Check completed. Evidence is available.':result.error,result.status==='failed'); if(result.evidence)showEvidence(result);}));
    if(action.evidence) controls.append(control('View evidence','secondary',async()=>showEvidence(action)));
    if(['completed','failed'].includes(action.status)) controls.append(control('Propose retest','secondary',async()=>{await api('/actions/'+action.id+'/retest','POST',{}); await refresh(); notify('Retest proposed. Review and approve it before execution.');}));
    if(action.error)card.append(node('p',action.error,'action-error'));
    card.append(controls); list.append(card);
  }
  $('pending-count').textContent=a.actions.filter(x=>x.status==='pending').length;
  $('completed-count').textContent=a.actions.filter(x=>x.status==='completed').length;
  const latest=new Map(); for(const action of a.actions) if(action.evidence&&!latest.has(action.target))latest.set(action.target,action.evidence);
  $('finding-count').textContent=[...latest.values()].reduce((sum,e)=>sum+e.findings.length,0);
}
function showEvidence(action) {
  const e=action.evidence; $('evidence-section').hidden=false;
  $('evidence-title').textContent='Header check · '+new URL(action.target).pathname;
  $('evidence-description').textContent='HTTP '+e.status_code+' · '+e.conclusion+' · '+new Date(e.captured_at).toLocaleString();
  const findings=$('findings'); findings.replaceChildren();
  if(!e.findings.length)findings.append(node('p',e.conclusion==='observed'?'No missing headers detected by these three checks. This is a limited configuration review.':'No conclusion about header configuration was made.','muted'));
  for(const f of e.findings){const row=node('article',undefined,'finding'),body=node('div'); body.append(node('h3',f.title),node('p',f.recommendation),node('p',f.confidence));row.append(node('span',f.severity.toUpperCase(),'severity'),body);findings.append(row);}
  if(e.comparison)findings.append(node('p','Retest comparison: '+JSON.stringify(e.comparison),'muted'));
  $('evidence-json').textContent=JSON.stringify(e,null,2);
  $('evidence-section').scrollIntoView({behavior:'smooth',block:'start'});
}
function renderAudit() {
  const r=state.report,list=$('audit-list');list.replaceChildren();
  const valid=r.integrity.audit_chain_valid&&r.integrity.evidence_hashes_valid&&r.integrity.plan_hashes_valid;
  $('integrity').textContent=valid?'HASHES VERIFIED':'INTEGRITY MISMATCH';
  for(const event of [...r.audit].reverse()) { const row=node('div',undefined,'audit-row'),time=node('time',new Date(event.at).toLocaleTimeString());time.dateTime=event.at; const body=node('div');body.append(node('strong',event.event.replaceAll('_',' ')),node('p',JSON.stringify(event.details)));row.append(time,body);list.append(row); }
}
async function select(id) { state.selected=id; $('evidence-section').hidden=true; await refresh(); }
async function refresh() {
  if(!state.plannerInfo)state.plannerInfo=await api('/planner');
  state.assessments=await api('/assessments'); $('assessment-count').textContent=state.assessments.length;
  if(!state.selected&&state.assessments.length)state.selected=state.assessments[0].id;
  if(state.selected){state.assessment=await api('/assessments/'+state.selected);state.report=await api('/assessments/'+state.selected+'/report');renderActions();renderPlans();renderAudit();}
  renderAssessments();
}
$('connect-form').onsubmit=e=>{e.preventDefault();task(async()=>{state.token=$('token').value.trim();state.plannerInfo=null;await refresh();$('token').value='';$('connect-panel').hidden=true;notify('Connected to the local assessment workspace.');});};
$('new-button').onclick=()=>{if(!state.token){notify('Connect with the terminal access token first.',true);$('token').focus();return;}$('create-panel').hidden=false;$('assessment-name').focus();};
$('cancel-create').onclick=()=>{$('create-panel').hidden=true;};
$('create-form').onsubmit=e=>{e.preventDefault();task(async()=>{const targets=[...document.querySelectorAll('input[name="target"]:checked')].map(x=>x.value);if(!targets.length)throw new Error('Select at least one demo target.');const a=await api('/assessments','POST',{name:$('assessment-name').value,targets,authorization_confirmed:$('authorization').checked});state.selected=a.id;$('create-panel').hidden=true;$('assessment-name').value='';$('authorization').checked=false;await refresh();notify('Assessment created. Propose a header check below.');});};
$('proposal-form').onsubmit=e=>{e.preventDefault();task(async()=>{await api('/assessments/'+state.selected+'/actions','POST',{tool:'http_headers',target:$('proposal-target').value,rationale:$('rationale').value});await refresh();notify('Action proposed. Review its target and approve or reject it.');});};
$('plan-form').onsubmit=e=>{e.preventDefault();task(async()=>{
  const goal=$('plan-goal').value.trim(), includeEvidence=$('plan-evidence').checked;
  if(!goal)throw new Error('Describe your assessment goal first.');
  // Retain the key after a lost response so retrying cannot duplicate a successful plan.
  if(!state.planRequest||state.planRequest.assessment!==state.selected||state.planRequest.goal!==goal||state.planRequest.includeEvidence!==includeEvidence)state.planRequest={assessment:state.selected,goal,includeEvidence,key:crypto.randomUUID()};
  notify(state.plannerInfo?.live_ai?'Requesting a plan from the configured model…':'Generating a local baseline plan…');
  let plan;
  try { plan=await api('/assessments/'+state.selected+'/plans','POST',{goal,include_evidence:includeEvidence,request_id:state.planRequest.key}); }
  catch(error) { if(error.status){state.planRequest=null;await refresh();} throw error; }
  state.planRequest=null;
  await refresh();
  notify(plan.action_ids.length?plan.action_ids.length+' checks proposed. Review and approve each check before running it.':plan.summary);
});};
$('export-button').onclick=()=>task(async()=>{const report=await api('/assessments/'+state.selected+'/report');const url=URL.createObjectURL(new Blob([JSON.stringify(report,null,2)],{type:'application/json'}));const link=node('a');link.href=url;link.download='assessment-'+state.selected+'.json';link.click();setTimeout(()=>URL.revokeObjectURL(url),1000);notify('JSON report downloaded.');});
$('close-evidence').onclick=()=>{$('evidence-section').hidden=true;};
$('overview-nav').onclick=()=>window.scrollTo({top:0,behavior:'smooth'});
