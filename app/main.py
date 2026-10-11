import secrets
from contextlib import asynccontextmanager
from pathlib import Path
import httpx
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.trustedhost import TrustedHostMiddleware
from .config import Settings
from .db import Store, digest, ExecutionBusy
from .models import AssessmentInput, ProposalInput, DecisionInput
from .policy import PolicyError, validate_target, validate_action
from .tools import HeaderChecker, compare
from .planning import FakePlanner, PlanningService, PlanInput, PlanningError


STATIC = Path(__file__).parent / "static"


def create_app(settings=None, checker=None, planner=None):
    settings = settings or Settings()
    store = Store(settings.db_path)
    checker = checker or HeaderChecker(settings.tool_timeout)
    planning = PlanningService(store, planner or FakePlanner(), settings)

    @asynccontextmanager
    async def lifespan(app):
        store.initialize()
        print(f"\nDashboard: http://127.0.0.1:8000\nAccess token: {settings.token}\n", flush=True)
        yield

    app = FastAPI(title="HoneyAGI", version="0.2.0", lifespan=lifespan,
                  docs_url=None, redoc_url=None, openapi_url=None)
    app.state.store, app.state.settings = store, settings
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=["127.0.0.1", "localhost", "testserver"])

    @app.middleware("http")
    async def boundary(request: Request, call_next):
        origin = request.headers.get("origin")
        if origin and origin not in settings.dashboard_origins:
            return JSONResponse({"detail": "Origin is not allowed"}, status_code=403)
        if request.url.path.startswith("/api/") and request.method == "POST":
            if request.headers.get("content-type", "").split(";")[0] != "application/json":
                return JSONResponse({"detail": "Use application/json"}, status_code=415)
            # Count streamed bytes too, rather than trusting Content-Length.
            size, chunks = 0, []
            async for chunk in request.stream():
                size += len(chunk)
                if size > 16384:
                    return JSONResponse({"detail": "Request body exceeds 16 KiB"}, status_code=413)
                chunks.append(chunk)
            # Populate Starlette's bounded body cache for downstream Pydantic parsing.
            request._body = b"".join(chunks)
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Content-Security-Policy"] = "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"
        response.headers["Cache-Control"] = "no-store"
        return response

    def authorize(request: Request):
        supplied = request.headers.get("authorization", "")
        if not secrets.compare_digest(supplied.encode(), f"Bearer {settings.token}".encode()):
            raise HTTPException(401, "Enter the access token printed in the server terminal")

    auth = [Depends(authorize)]

    def assessment_or_404(assessment_id):
        value = store.get_assessment(assessment_id)
        if not value:
            raise HTTPException(404, "Assessment not found")
        return value

    def action_or_404(action_id):
        value = store.get_action(action_id)
        if not value:
            raise HTTPException(404, "Action not found")
        return value

    def policy_check(tool, target, assessment, action_id=None):
        try:
            validate_action(tool, target, assessment["targets"], settings.demo_origin)
        except PolicyError as exc:
            store.record(assessment["id"], "policy_denied", action_id, {"reason": str(exc)})
            raise HTTPException(403, str(exc)) from exc

    @app.get("/health")
    def health():
        return {"status": "ok", "version": "0.2.0"}

    @app.get("/api/v1/planner", dependencies=auth)
    def planner_info():
        return {**planning.info.model_dump(), "mode": "rule_based", "live_ai": False,
                "allowed_tools": ["http_headers"], "requires_approval": True}

    @app.get("/api/v1/assessments", dependencies=auth)
    def list_assessments():
        return store.list_assessments()

    @app.post("/api/v1/assessments", status_code=201, dependencies=auth)
    def create_assessment(data: AssessmentInput):
        try:
            targets = list(dict.fromkeys(validate_target(t, settings.demo_origin) for t in data.targets))
        except PolicyError as exc:
            raise HTTPException(403, str(exc)) from exc
        return store.create_assessment(data.name, targets)

    @app.get("/api/v1/assessments/{assessment_id}", dependencies=auth)
    def get_assessment(assessment_id: str):
        return {**assessment_or_404(assessment_id), "actions": store.list_actions(assessment_id), "plans": store.list_plans(assessment_id)}

    @app.post("/api/v1/assessments/{assessment_id}/plans", dependencies=auth)
    async def generate_plan(assessment_id: str, data: PlanInput):
        assessment_or_404(assessment_id)
        try:
            plan, created = await planning.generate(assessment_id, data)
        except PlanningError as exc:
            raise HTTPException(exc.status_code, {"message": exc.message, "plan_id": exc.plan_id}) from exc
        return JSONResponse(plan, status_code=201 if created else 200)

    @app.post("/api/v1/assessments/{assessment_id}/actions", status_code=201, dependencies=auth)
    def propose(assessment_id: str, data: ProposalInput):
        assessment = assessment_or_404(assessment_id)
        policy_check(data.tool, data.target, assessment)
        return store.propose(assessment_id, data.tool, data.target, data.rationale)

    @app.post("/api/v1/actions/{action_id}/approve", dependencies=auth)
    def approve(action_id: str, data: DecisionInput):
        action = action_or_404(action_id)
        policy_check(action["tool"], action["target"], assessment_or_404(action["assessment_id"]), action_id)
        if not store.transition(action_id, "pending", "approved", "action_approved", {"note": data.note, "actor": "local_operator"}):
            raise HTTPException(409, "Only pending actions can be approved")
        return store.get_action(action_id)

    @app.post("/api/v1/actions/{action_id}/reject", dependencies=auth)
    def reject(action_id: str, data: DecisionInput):
        action_or_404(action_id)
        if not store.transition(action_id, "pending", "rejected", "action_rejected", {"note": data.note, "actor": "local_operator"}):
            raise HTTPException(409, "Only pending actions can be rejected")
        return store.get_action(action_id)

    @app.post("/api/v1/actions/{action_id}/execute", dependencies=auth)
    async def execute(action_id: str, data: DecisionInput):
        action = action_or_404(action_id)
        policy_check(action["tool"], action["target"], assessment_or_404(action["assessment_id"]), action_id)
        try:
            claimed = store.transition(action_id, "approved", "running", "execution_started", {"tool": action["tool"], "target": action["target"]})
        except ExecutionBusy as exc:
            raise HTTPException(429, "Two checks are running; retry after they finish") from exc
        if not claimed:
            raise HTTPException(409, "Execution requires approval and can run only once")
        try:
            evidence = await checker.run(action["target"])
            if action["parent_id"]:
                parent = store.get_action(action["parent_id"])
                if parent and parent["evidence"]:
                    evidence["comparison"] = compare(parent["evidence"], evidence)
                    evidence["sha256"] = digest({k: v for k, v in evidence.items() if k != "sha256"})
            store.transition(action_id, "running", "completed", "execution_completed",
                             {"evidence_sha256": evidence["sha256"], "finding_count": len(evidence["findings"])}, evidence=evidence)
        except (httpx.HTTPError, TimeoutError, ValueError):
            store.transition(action_id, "running", "failed", "execution_failed", {"reason": "Target unavailable, timeout, or invalid response"},
                             error="Target unavailable, timeout, or invalid response. Check the demo terminal.")
        except BaseException:
            store.transition(action_id, "running", "failed", "execution_failed", {"reason": "Execution interrupted"}, error="Execution interrupted")
            raise
        return store.get_action(action_id)

    @app.post("/api/v1/actions/{action_id}/retest", status_code=201, dependencies=auth)
    def retest(action_id: str, data: DecisionInput):
        action = action_or_404(action_id)
        if action["status"] not in ("completed", "failed"):
            raise HTTPException(409, "Retest requires a completed or failed action")
        policy_check(action["tool"], action["target"], assessment_or_404(action["assessment_id"]), action_id)
        return store.propose(action["assessment_id"], action["tool"], action["target"], data.note or "Retest previous observation", parent_id=action_id)

    @app.get("/api/v1/assessments/{assessment_id}/report", dependencies=auth)
    def report(assessment_id: str):
        assessment_or_404(assessment_id)
        return JSONResponse(store.report(assessment_id), headers={"Content-Disposition": f'attachment; filename="assessment-{assessment_id}.json"'})

    @app.get("/")
    def dashboard():
        return FileResponse(STATIC / "index.html")

    app.mount("/static", StaticFiles(directory=STATIC), name="static")
    return app
