import hashlib
import json
import sqlite3
from contextlib import contextmanager
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
                CREATE TABLE IF NOT EXISTS actions (
                    id TEXT PRIMARY KEY, assessment_id TEXT NOT NULL REFERENCES assessments(id),
                    tool TEXT NOT NULL, target TEXT NOT NULL, rationale TEXT NOT NULL,
                    status TEXT NOT NULL CHECK(status IN
                      ('pending','approved','rejected','running','completed','failed')),
                    created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
                    parent_id TEXT REFERENCES actions(id), error TEXT, evidence TEXT
                );
                CREATE TABLE IF NOT EXISTS audit (
                    seq INTEGER PRIMARY KEY AUTOINCREMENT,
                    assessment_id TEXT NOT NULL REFERENCES assessments(id),
                    event TEXT NOT NULL, action_id TEXT, at TEXT NOT NULL,
                    details TEXT NOT NULL, previous_hash TEXT NOT NULL, hash TEXT NOT NULL
                );
            """)
        # One process only: a previous process's in-flight request cannot be replayed.
        with self.connection(write=True) as db:
            for row in db.execute("SELECT * FROM actions WHERE status='running'").fetchall():
                db.execute("UPDATE actions SET status='failed',error=?,updated_at=? WHERE id=?",
                           ("Execution interrupted by server restart; propose a retest", now(), row["id"]))
                self.audit(db, row["assessment_id"], "execution_interrupted", row["id"], {})

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

    def report(self, assessment_id):
        # Consistent snapshot while other requests may write.
        with self.connection() as db:
            db.execute("BEGIN")
            row = db.execute("SELECT * FROM assessments WHERE id=?", (assessment_id,)).fetchone()
            if not row:
                return None
            actions = [self.action(r) for r in db.execute("SELECT * FROM actions WHERE assessment_id=? ORDER BY created_at", (assessment_id,))]
            audit = [{**dict(r), "details": json.loads(r["details"])} for r in db.execute("SELECT * FROM audit WHERE assessment_id=? ORDER BY seq", (assessment_id,))]
        previous, valid = "0" * 64, True
        for entry in audit:
            payload = {k: v for k, v in entry.items() if k not in ("seq", "hash")}
            valid = valid and entry["previous_hash"] == previous and digest(payload) == entry["hash"]
            previous = entry["hash"]
        captured_hashes = {entry["action_id"]: entry["details"].get("evidence_sha256")
                           for entry in audit if entry["event"] == "execution_completed"}
        evidence_valid = all(digest({k: v for k, v in a["evidence"].items() if k != "sha256"}) == a["evidence"]["sha256"]
                             and captured_hashes.get(a["id"]) == a["evidence"]["sha256"] for a in actions if a["evidence"])
        return {"schema_version": 1, "generated_at": now(), "assessment": self.assessment(row),
                "actions": actions, "audit": audit,
                "integrity": {"audit_chain_valid": bool(valid), "evidence_hashes_valid": evidence_valid,
                              "note": "Local integrity checks; a database owner can rewrite hashes. No external anchoring."}}
