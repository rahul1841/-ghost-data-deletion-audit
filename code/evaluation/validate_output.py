"""Check output.csv against the submission contract.

    python code/evaluation/validate_output.py [output.csv]
"""
import csv
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "code"))
from ghost_audit.common import parse_ts, read_csv  # noqa: E402
from ghost_audit.planner import OP_STATE, FINDING_ORDER, REMEDIATION_ORDER, VERIFICATION_ORDER  # noqa: E402

PHASE_OPS = {"FINDING": FINDING_ORDER, "REMEDIATION": REMEDIATION_ORDER, "VERIFICATION": VERIFICATION_ORDER}


def validate(path):
    errors = []
    requests = {r["case_id"]: r for r in read_csv("deletion_requests.csv")}
    ev_time = {r["file_id"]: parse_ts(r["captured_at"]) for r in read_csv("evidence_files.csv")}
    ev_time.update({a["activity_id"]: parse_ts(a["event_time"]) for a in read_csv("system_activity.csv")})
    ev_time.update({a["audit_id"]: parse_ts(a["event_time"]) for a in read_csv("user_audit_log.csv")})
    with open(path, encoding="utf-8", newline="") as f:
        rd = csv.reader(f)
        header = next(rd)
        rows = list(rd)
    if header != ["case_id", "deletion_status", "steps_json"]:
        errors.append(f"bad header {header}")
    ids = [r[0] for r in rows]
    if sorted(ids) != sorted(requests) or len(ids) != len(set(ids)):
        errors.append("case ids do not match deletion_requests.csv one-to-one")
    if ids != sorted(ids, key=lambda c: int(c.split("_")[-1])):
        errors.append("rows not sorted by case_id")
    for cid, status, js in rows:
        steps = json.loads(js)
        audit = parse_ts(requests[cid]["audit_at"]) if cid in requests else None
        if status not in ("COMPLETE", "INCOMPLETE", "NOT_APPLICABLE"):
            errors.append(f"{cid}: bad status")
        if status == "NOT_APPLICABLE" and steps:
            errors.append(f"{cid}: NOT_APPLICABLE must have []")
        if status == "COMPLETE" and any(s["phase"] != "VERIFICATION" or not s["evidence_id"] for s in steps):
            errors.append(f"{cid}: COMPLETE must be evidence-backed verification only")
        last = (-1, -1)
        for i, s in enumerate(steps, 1):
            if set(s) != {"step_no", "phase", "system_id", "resource_id", "operation", "state", "evidence_id"}:
                errors.append(f"{cid}: step {i} fields")
            if s["step_no"] != i:
                errors.append(f"{cid}: step numbering")
            if OP_STATE.get(s["operation"]) != s["state"] or s["operation"] not in PHASE_OPS.get(s["phase"], []):
                errors.append(f"{cid}: step {i} op/state/phase mismatch")
                continue
            pos = (list(PHASE_OPS).index(s["phase"]), PHASE_OPS[s["phase"]].index(s["operation"]))
            if pos < last:
                errors.append(f"{cid}: step {i} out of order")
            last = pos
            ev = s["evidence_id"]
            if status == "INCOMPLETE" and s["phase"] != "FINDING" and ev:
                errors.append(f"{cid}: future step {i} must not cite evidence")
            if ev:
                if ev not in ev_time:
                    errors.append(f"{cid}: unknown evidence {ev}")
                elif audit and ev_time[ev] > audit:
                    errors.append(f"{cid}: evidence {ev} captured after audit_at")
    return errors, len(rows)


if __name__ == "__main__":
    errs, n = validate(sys.argv[1] if len(sys.argv) > 1 else ROOT / "output.csv")
    for e in errs[:50]:
        print("ERROR", e)
    print(f"{n} rows checked, {len(errs)} problems")
    sys.exit(1 if errs else 0)
