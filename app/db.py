import hashlib
import json
import sqlite3
from contextlib import contextmanager
from dataclasses import asdict
from .evidence import build_evidence_context, EvidenceContextError
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def canonical(value) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def digest(value) -> str:
    return hashlib.sha256(canonical(value).encode()).hexdigest()


class ExecutionBusy(RuntimeError):
    pass


class PlanningBusy(RuntimeError):
    pass


class PlanConflict(RuntimeError):
    pass


class PlanStale(RuntimeError):
    pass


class Store:
    def __init__(self, path: Path):
        self.path = Path(path)

    @contextmanager
    def connection(self, write=False):
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        try:
            if write:
                db.execute("BEGIN IMMEDIATE")
            yield db
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    def initialize(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connection() as db:
            db.execute("PRAGMA journal_mode=WAL")
            db.executescript("""
                CREATE TABLE IF NOT EXISTS assessments (
                    id TEXT PRIMARY KEY, name TEXT NOT NULL, targets TEXT NOT NULL,
                    created_at TEXT NOT NULL, authorization_confirmed INTEGER NOT NULL
                );
                CREATE TABLE IF NOT EXISTS plans (
                    id TEXT PRIMARY KEY, assessment_id TEXT NOT NULL REFERENCES assessments(id),
                    goal TEXT NOT NULL, provider TEXT NOT NULL, model TEXT NOT NULL,
                    fingerprint TEXT NOT NULL, status TEXT NOT NULL CHECK(status IN
                      ('running','completed','denied','failed')),
                    summary TEXT, error_code TEXT, created_at TEXT NOT NULL, finished_at TEXT,
                    action_ids TEXT NOT NULL DEFAULT '[]', sha256 TEXT
                );
                CREATE TABLE IF NOT EXISTS actions (
                    id TEXT PRIMARY KEY, assessment_id TEXT NOT NULL REFERENCES assessments(id),
                    tool TEXT NOT NULL, target TEXT NOT NULL, rationale TEXT NOT NULL,
                    status TEXT NOT NULL CHECK(status IN
                      ('pending','approved','rejected','running','completed','failed')),
                    created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
                    parent_id TEXT REFERENCES actions(id), error TEXT, evidence TEXT,
                    plan_id TEXT REFERENCES plans(id)
                );
                CREATE TABLE IF NOT EXISTS audit (
                    seq INTEGER PRIMARY KEY AUTOINCREMENT,
                    assessment_id TEXT NOT NULL REFERENCES assessments(id),
                    event TEXT NOT NULL, action_id TEXT, at TEXT NOT NULL,
                    details TEXT NOT NULL, previous_hash TEXT NOT NULL, hash TEXT NOT NULL
                );
            """)
            # Additive migration preserves all day-one actions and audit entries.
            if "plan_id" not in {r["name"] for r in db.execute("PRAGMA table_info(actions)")}:
                db.execute("ALTER TABLE actions ADD COLUMN plan_id TEXT REFERENCES plans(id)")
            if "evidence_context_json" not in {r["name"] for r in db.execute("PRAGMA table_info(plans)")}:
                db.execute("ALTER TABLE plans ADD COLUMN evidence_context_json TEXT")
        # One process only: a previous process's in-flight request cannot be replayed.
        with self.connection(write=True) as db:
            for row in db.execute("SELECT * FROM actions WHERE status='running'").fetchall():
                db.execute("UPDATE actions SET status='failed',error=?,updated_at=? WHERE id=?",
                           ("Execution interrupted by server restart; propose a retest", now(), row["id"]))
                self.audit(db, row["assessment_id"], "execution_interrupted", row["id"], {})
            for row in db.execute("SELECT * FROM plans WHERE status='running'").fetchall():
                db.execute("UPDATE plans SET status='failed',error_code='interrupted',finished_at=? WHERE id=?", (now(), row["id"]))
                self.audit(db, row["assessment_id"], "planning_interrupted", None, {"plan_id": row["id"]})

    def audit(self, db, assessment_id, event, action_id, details):
        previous = db.execute("SELECT hash FROM audit WHERE assessment_id=? ORDER BY seq DESC LIMIT 1",
                              (assessment_id,)).fetchone()
        entry = {"assessment_id": assessment_id, "event": event, "action_id": action_id,
                 "at": now(), "details": details, "previous_hash": previous[0] if previous else "0" * 64}
        db.execute("INSERT INTO audit (assessment_id,event,action_id,at,details,previous_hash,hash) VALUES (?,?,?,?,?,?,?)",
                   (assessment_id, event, action_id, entry["at"], canonical(details), entry["previous_hash"], digest(entry)))

    @staticmethod
    def assessment(row):
        return {**dict(row), "targets": json.loads(row["targets"]),
                "authorization_confirmed": bool(row["authorization_confirmed"])}

    @staticmethod
    def action(row):
        return {**dict(row), "evidence": json.loads(row["evidence"]) if row["evidence"] else None}

    def create_assessment(self, name, targets):
        assessment_id = str(uuid4())
        with self.connection(write=True) as db:
            db.execute("INSERT INTO assessments VALUES (?,?,?,?,1)", (assessment_id, name, canonical(targets), now()))
            self.audit(db, assessment_id, "assessment_created", None, {"targets": targets, "authorization_confirmed": True})
        return self.get_assessment(assessment_id)

    def list_assessments(self):
        with self.connection() as db:
            return [self.assessment(r) for r in db.execute("SELECT * FROM assessments ORDER BY created_at DESC")]

    def get_assessment(self, assessment_id):
        with self.connection() as db:
            row = db.execute("SELECT * FROM assessments WHERE id=?", (assessment_id,)).fetchone()
            return self.assessment(row) if row else None

    def get_action(self, action_id):
        with self.connection() as db:
            row = db.execute("SELECT * FROM actions WHERE id=?", (action_id,)).fetchone()
            return self.action(row) if row else None

    def list_actions(self, assessment_id):
        with self.connection() as db:
            return [self.action(r) for r in db.execute("SELECT * FROM actions WHERE assessment_id=? ORDER BY created_at DESC", (assessment_id,))]

    def propose(self, assessment_id, tool, target, rationale, parent_id=None):
        action_id, timestamp = str(uuid4()), now()
        with self.connection(write=True) as db:
            db.execute("INSERT INTO actions (id,assessment_id,tool,target,rationale,status,created_at,updated_at,parent_id) VALUES (?,?,?,?,?,'pending',?,?,?)",
                       (action_id, assessment_id, tool, target, rationale, timestamp, timestamp, parent_id))
            self.audit(db, assessment_id, "action_proposed", action_id,
                       {"tool": tool, "target": target, "rationale": rationale, "parent_id": parent_id})
        return self.get_action(action_id)

    def transition(self, action_id, expected, status, event, details=None, evidence=None, error=None):
        """Compare-and-swap in one transaction prevents duplicate execution/decisions."""
        with self.connection(write=True) as db:
            if status == "running" and db.execute("SELECT count(*) FROM actions WHERE status='running'").fetchone()[0] >= 2:
                raise ExecutionBusy("Two checks are already running")
            result = db.execute("UPDATE actions SET status=?,updated_at=?,evidence=?,error=? WHERE id=? AND status=?",
                                (status, now(), canonical(evidence) if evidence else None, error, action_id, expected))
            if result.rowcount != 1:
                return False
            row = db.execute("SELECT assessment_id FROM actions WHERE id=?", (action_id,)).fetchone()
            self.audit(db, row[0], event, action_id, details or {})
        return True

    def record(self, assessment_id, event, action_id, details):
        with self.connection(write=True) as db:
            self.audit(db, assessment_id, event, action_id, details)

    @staticmethod
    def plan(db, row):
        result = {**dict(row), "action_ids": json.loads(row["action_ids"])}
        context_json = result.pop("evidence_context_json", None)
        # Omit absent context to preserve hashes and replays of pre-migration plans.
        if context_json is not None:
            result["evidence_context"] = json.loads(context_json)
        result["proposals"] = [dict(r) for r in db.execute(
            "SELECT id,tool,target,rationale FROM actions WHERE plan_id=? ORDER BY rowid", (row["id"],))]
        return result

    def get_plan(self, plan_id):
        with self.connection() as db:
            row = db.execute("SELECT * FROM plans WHERE id=?", (plan_id,)).fetchone()
            return self.plan(db, row) if row else None

    def list_plans(self, assessment_id):
        with self.connection() as db:
            return [self.plan(db, row) for row in db.execute(
                "SELECT * FROM plans WHERE assessment_id=? ORDER BY rowid DESC", (assessment_id,)).fetchall()]

    def begin_plan(self, plan_id, assessment_id, goal, info, *, include_evidence=False, demo_origin=None):
        fingerprint = digest({"assessment_id": assessment_id, "goal": goal, **info,
                              **({"include_evidence": True} if include_evidence else {})})
        with self.connection(write=True) as db:
            existing = db.execute("SELECT * FROM plans WHERE id=?", (plan_id,)).fetchone()
            if existing:
                if existing["fingerprint"] != fingerprint:
                    raise PlanConflict()
                return self.plan(db, existing), False
            active = db.execute("SELECT assessment_id FROM plans WHERE status='running'").fetchall()
            if len(active) >= 2 or any(r[0] == assessment_id for r in active):
                raise PlanningBusy()
            context = None
            if include_evidence:
                # The writer lock prevents evidence changing between snapshot and insert.
                try:
                    context = asdict(build_evidence_context(self.report(assessment_id), demo_origin))
                except (ValueError, TypeError, KeyError, AttributeError, RecursionError) as exc:
                    raise EvidenceContextError() from exc
            db.execute("INSERT INTO plans (id,assessment_id,goal,provider,model,fingerprint,status,created_at,evidence_context_json) VALUES (?,?,?,?,?,?,'running',?,?)",
                       (plan_id, assessment_id, goal, info["provider"], info["model"], fingerprint, now(),
                        canonical(context) if context is not None else None))
            self.audit(db, assessment_id, "planning_started", None,
                       {"plan_id": plan_id, **info, "goal_sha256": digest(goal),
                        **({"evidence_context_sha256": digest(context),
                            "evidence_count": len(context["observations"]),
                            "evidence_omitted_count": context["omitted_count"]} if context is not None else {})})
            row = db.execute("SELECT * FROM plans WHERE id=?", (plan_id,)).fetchone()
            return self.plan(db, row), True

    def fail_plan(self, plan_id, code, status):
        with self.connection(write=True) as db:
            row = db.execute("SELECT * FROM plans WHERE id=? AND status='running'", (plan_id,)).fetchone()
            if not row:
                return
            db.execute("UPDATE plans SET status=?,error_code=?,finished_at=? WHERE id=?", (status, code, now(), plan_id))
            self.audit(db, row["assessment_id"], "planning_" + status, None, {"plan_id": plan_id, "reason": code})

    def complete_plan(self, plan_id, output, demo_origin):
        from .policy import validate_action
        with self.connection(write=True) as db:
            row = db.execute("SELECT * FROM plans WHERE id=? AND status='running'", (plan_id,)).fetchone()
            if not row:
                raise PlanStale()
            assessment = self.assessment(db.execute("SELECT * FROM assessments WHERE id=?", (row["assessment_id"],)).fetchone())
            # Recheck the current database inside the same transaction as insertion.
            for action in output.actions:
                validate_action(action.tool, action.target, assessment["targets"], demo_origin)
                if db.execute("SELECT 1 FROM actions WHERE assessment_id=? AND tool=? AND target=?",
                              (assessment["id"], action.tool, action.target)).fetchone():
                    raise PlanStale()
            ids = []
            for action in output.actions:
                action_id, timestamp = str(uuid4()), now()
                ids.append(action_id)
                db.execute("INSERT INTO actions (id,assessment_id,tool,target,rationale,status,created_at,updated_at,plan_id) VALUES (?,?,?,?,?,'pending',?,?,?)",
                           (action_id, assessment["id"], action.tool, action.target, action.rationale, timestamp, timestamp, plan_id))
                self.audit(db, assessment["id"], "action_proposed", action_id,
                           {"tool": action.tool, "target": action.target, "rationale": action.rationale, "parent_id": None, "plan_id": plan_id})
            db.execute("UPDATE plans SET status='completed',summary=?,finished_at=?,action_ids=? WHERE id=?",
                       (output.summary, now(), canonical(ids), plan_id))
            completed = self.plan(db, db.execute("SELECT * FROM plans WHERE id=?", (plan_id,)).fetchone())
            plan_hash = digest({k: v for k, v in completed.items() if k != "sha256"})
            db.execute("UPDATE plans SET sha256=? WHERE id=?", (plan_hash, plan_id))
            self.audit(db, assessment["id"], "planning_completed", None,
                       {"plan_id": plan_id, "plan_sha256": plan_hash, "action_count": len(ids)})
        return self.get_plan(plan_id)

    def report(self, assessment_id):
        # Consistent snapshot while other requests may write.
        with self.connection() as db:
            db.execute("BEGIN")
            row = db.execute("SELECT * FROM assessments WHERE id=?", (assessment_id,)).fetchone()
            if not row:
                return None
            actions = [self.action(r) for r in db.execute("SELECT * FROM actions WHERE assessment_id=? ORDER BY created_at", (assessment_id,))]
            audit = [{**dict(r), "details": json.loads(r["details"])} for r in db.execute("SELECT * FROM audit WHERE assessment_id=? ORDER BY seq", (assessment_id,))]
            plans = [self.plan(db, r) for r in db.execute("SELECT * FROM plans WHERE assessment_id=? ORDER BY rowid", (assessment_id,)).fetchall()]
        previous, valid = "0" * 64, True
        for entry in audit:
            payload = {k: v for k, v in entry.items() if k not in ("seq", "hash")}
            valid = valid and entry["previous_hash"] == previous and digest(payload) == entry["hash"]
            previous = entry["hash"]
        captured_hashes = {entry["action_id"]: entry["details"].get("evidence_sha256")
                           for entry in audit if entry["event"] == "execution_completed"}
        evidence_valid = all(digest({k: v for k, v in a["evidence"].items() if k != "sha256"}) == a["evidence"]["sha256"]
                             and captured_hashes.get(a["id"]) == a["evidence"]["sha256"] for a in actions if a["evidence"])
        plan_hashes = {e["details"]["plan_id"]: e["details"]["plan_sha256"] for e in audit if e["event"] == "planning_completed"}
        plans_valid = all(digest({k: v for k, v in p.items() if k != "sha256"}) == p["sha256"]
                          and plan_hashes.get(p["id"]) == p["sha256"]
                          and p["action_ids"] == [a["id"] for a in p["proposals"]] for p in plans if p["status"] == "completed")
        return {"schema_version": 2, "generated_at": now(), "assessment": self.assessment(row),
                "actions": actions, "plans": plans, "audit": audit,
                "integrity": {"audit_chain_valid": bool(valid), "evidence_hashes_valid": evidence_valid,
                              "plan_hashes_valid": plans_valid,
                              "note": "Local integrity checks; a database owner can rewrite hashes. No external anchoring."}}
