"""Derived, bounded progress for operator-triggered planning sequences."""
import json

MAX_PLANNING_STEPS = 4


class ContinuationDenied(ValueError):
    pass


def planning_progress(db, assessment_id):
    latest = db.execute("SELECT * FROM plans WHERE assessment_id=? ORDER BY rowid DESC LIMIT 1",
                        (assessment_id,)).fetchone()
    result = {"status": "not_started", "steps_used": 0, "max_steps": MAX_PLANNING_STEPS,
              "latest_plan_id": latest["id"] if latest else None, "can_continue": False}
    if latest is None:
        return result
    # Bounded walk; reject missing, cross-assessment or cyclic provenance.
    row, seen = latest, set()
    while row:
        if row["id"] in seen or row["assessment_id"] != assessment_id or len(seen) >= MAX_PLANNING_STEPS:
            return {**result, "status": "blocked", "steps_used": len(seen)}
        seen.add(row["id"])
        parent = row["continuation_of"]
        if parent is None:
            break
        row = db.execute("SELECT * FROM plans WHERE id=?", (parent,)).fetchone()
        if row is None:
            return {**result, "status": "blocked", "steps_used": len(seen)}
    result["steps_used"] = len(seen)
    if latest["status"] == "running":
        return {**result, "status": "generating"}
    if latest["status"] != "completed":
        return {**result, "status": "blocked"}
    if db.execute("SELECT 1 FROM actions WHERE assessment_id=? AND status IN ('pending','approved','running') LIMIT 1",
                  (assessment_id,)).fetchone():
        return {**result, "status": "awaiting_actions"}
    try:
        ids = json.loads(latest["action_ids"])
        if not isinstance(ids, list):
            raise ValueError()
    except (ValueError, TypeError):
        return {**result, "status": "blocked"}
    if not ids:
        return {**result, "status": "finished"}
    if len(seen) >= MAX_PLANNING_STEPS:
        return {**result, "status": "budget_reached"}
    return {**result, "status": "ready", "can_continue": True}
