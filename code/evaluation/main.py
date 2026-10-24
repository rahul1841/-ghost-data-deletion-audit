"""Score predictions against labelled cases.

    python code/evaluation/main.py                         # samples: runs the agent, then scores
    python code/evaluation/main.py --pred P.csv --gold G.csv [--verbose]

Metrics
  status accuracy   - deletion_status matches
  step P/R/F1       - steps compared as (phase, system_id, resource_id, operation, state, evidence_id)
  core step F1      - same, ignoring evidence_id
  field accuracy    - steps aligned by position; share of the 7 fields that match (over the longer list)
  sequence accuracy - the whole steps_json array is identical
"""
import argparse
import csv
import json
import subprocess
import sys
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
FIELDS = ["step_no", "phase", "system_id", "resource_id", "operation", "state", "evidence_id"]


def load(path):
    with open(path, encoding="utf-8", newline="") as f:
        return {r["case_id"]: (r["deletion_status"], json.loads(r["steps_json"])) for r in csv.DictReader(f)}


def tup(s, with_ev=True):
    t = (s["phase"], s["system_id"], s["resource_id"], s["operation"], s["state"])
    return t + (s["evidence_id"],) if with_ev else t


def prf(pred, gold):
    p, g = Counter(pred), Counter(gold)
    tp = sum((p & g).values())
    prec = tp / sum(p.values()) if p else (1.0 if not g else 0.0)
    rec = tp / sum(g.values()) if g else (1.0 if not p else 0.0)
    return tp, sum(p.values()), sum(g.values()), prec, rec


def score(pred, gold, verbose=False):
    n = len(gold)
    status_ok = seq_ok = 0
    tp = np_ = ng = 0
    ctp = cnp = cng = 0
    field_hit = field_tot = 0
    failures = []
    for cid, (gs, gsteps) in sorted(gold.items()):
        ps, psteps = pred.get(cid, ("MISSING", []))
        status_ok += ps == gs
        seq_ok += [tup(s) for s in psteps] == [tup(s) for s in gsteps] and ps == gs
        a, b, c, _, _ = prf([tup(s) for s in psteps], [tup(s) for s in gsteps])
        tp, np_, ng = tp + a, np_ + b, ng + c
        a, b, c, _, _ = prf([tup(s, False) for s in psteps], [tup(s, False) for s in gsteps])
        ctp, cnp, cng = ctp + a, cnp + b, cng + c
        for i in range(max(len(psteps), len(gsteps))):
            for f in FIELDS:
                field_tot += 1
                if i < len(psteps) and i < len(gsteps) and psteps[i].get(f) == gsteps[i].get(f):
                    field_hit += 1
        if ps != gs or [tup(s) for s in psteps] != [tup(s) for s in gsteps]:
            missing = sorted(set(map(tup, gsteps)) - set(map(tup, psteps)))
            extra = sorted(set(map(tup, psteps)) - set(map(tup, gsteps)))
            failures.append((cid, gs, ps, missing, extra))
    f1 = lambda t, p, g: 2 * t / (p + g) if p + g else 1.0
    res = {
        "cases": n,
        "status_accuracy": status_ok / n,
        "step_precision": tp / np_ if np_ else 1.0, "step_recall": tp / ng if ng else 1.0,
        "step_f1": f1(tp, np_, ng),
        "core_step_f1": f1(ctp, cnp, cng),
        "field_accuracy": field_hit / field_tot if field_tot else 1.0,
        "sequence_accuracy": seq_ok / n,
    }
    if verbose:
        for cid, gs, ps, missing, extra in failures:
            print(f"--- {cid}: gold={gs} pred={ps}")
            for m in missing:
                print("   missing", m)
            for e in extra:
                print("   extra  ", e)
    return res, failures


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pred")
    ap.add_argument("--gold", default=str(ROOT / "dataset" / "sample_output.csv"))
    ap.add_argument("--input", default="sample_deletion_requests.csv")
    ap.add_argument("--verbose", action="store_true")
    args = ap.parse_args()
    pred_path = args.pred
    if not pred_path:
        pred_path = str(HERE / "sample_predictions.csv")
        subprocess.run([sys.executable, str(ROOT / "code" / "main.py"), "--input", args.input,
                        "--output", pred_path], check=True)
    res, _ = score(load(pred_path), load(args.gold), args.verbose)
    for k, v in res.items():
        print(f"{k:20s} {v:.3f}" if isinstance(v, float) else f"{k:20s} {v}")


if __name__ == "__main__":
    main()
