import pytest
from conftest import assessment, proposal, ORIGIN


def test_auth_required_and_no_cors(lab):
    c, *_ = lab
    assert c.get('/health', headers={"Authorization": ""}).status_code == 200
    assert c.get('/api/v1/assessments', headers={"Authorization": ""}).status_code == 401
    assert c.get('/api/v1/assessments', headers={"Authorization": "Bearer wrong"}).status_code == 401
    assert "access-control-allow-origin" not in c.get('/api/v1/assessments').headers


@pytest.mark.parametrize("origin", ["https://evil.example", "null", "http://127.0.0.1:8001", "http://localhost:9000"])
def test_cross_origin_rejected_even_with_token(lab, origin):
    c, *_ = lab
    assert c.get('/api/v1/assessments', headers={"Origin": origin}).status_code == 403


def test_host_validation(lab):
    c, *_ = lab
    assert c.get('/health', headers={"Host": "evil.example"}).status_code == 400


def test_body_limit_and_content_type(lab):
    c, *_ = lab
    assert c.post('/api/v1/assessments', content='x', headers={"Content-Type": "text/plain"}).status_code == 415
    assert c.post('/api/v1/assessments', content='x' * 17000, headers={"Content-Type": "application/json"}).status_code == 413
    assert c.post('/api/v1/assessments', content=iter([b'x' * 9000, b'x' * 9000]), headers={"Content-Type": "application/json"}).status_code == 413
    assert c.post('/api/v1/assessments', content='{bad', headers={"Content-Type": "application/json"}).status_code == 422


def test_unknown_tool_and_parameters_cannot_reach_executor(lab):
    c, _, calls, _ = lab
    a = assessment(c)
    for body in [{"tool": "shell", "target": ORIGIN + '/vulnerable', "rationale": "test"},
                 {"tool": "http_headers", "target": ORIGIN + '/vulnerable', "rationale": "test", "command": "anything"}]:
        assert c.post(f'/api/v1/assessments/{a["id"]}/actions', json=body).status_code == 422
    assert calls == []


def test_missing_authorization(lab):
    c, *_ = lab
    body = {"name": "Test", "targets": [ORIGIN + '/vulnerable'], "authorization_confirmed": False}
    assert c.post('/api/v1/assessments', json=body).status_code == 422
    del body['authorization_confirmed']
    assert c.post('/api/v1/assessments', json=body).status_code == 422


def test_missing_ids(lab):
    c, *_ = lab
    assert c.get('/api/v1/assessments/missing').status_code == 404
    assert c.post('/api/v1/actions/missing/execute', json={}).status_code == 404
    assert c.get('/api/v1/assessments/missing/report').status_code == 404


def test_static_dashboard_security_headers(lab):
    c, *_ = lab
    response = c.get('/')
    assert response.status_code == 200
    assert 'Assessment Lab' in response.text
    assert "script-src 'self'" in response.headers['content-security-policy']
    assert response.headers['x-content-type-options'] == 'nosniff'
    assert c.get('/static/app.js').status_code == 200
    assert c.get('/static/styles.css').status_code == 200
