# Evaluation Report — Ghost Data Still Exists

All numbers below come from code in this folder and can be reproduced from the repository root:

```bash
python code/evaluation/main.py --verbose        # runs the agent on the 32 public samples and scores it
python code/evaluation/custom_cases.py          # 5 hand-built cases
python code/evaluation/validate_output.py       # contract checks on the final output.csv
```

## 1. Labelled sample set (32 public cases, `dataset/sample_output.csv`)

| Metric | Definition | Score |
|---|---|---|
| Case-level status accuracy | `deletion_status` matches | **1.000** (32/32) |
| Step precision | predicted steps that exactly match a gold step (phase, system, resource, operation, state, evidence) | **0.978** |
| Step recall | gold steps that were produced | **0.933** |
| Step F1 | harmonic mean | **0.955** |
| Core step F1 | same, ignoring `evidence_id` | **0.955** |
| Field-level accuracy | steps aligned by position, share of the 7 fields that match (over the longer list) | **0.920** |
| Sequence accuracy | the entire `steps_json` array is identical | **0.656** (21/32) |

Status breakdown: gold 10 COMPLETE / 22 INCOMPLETE; predicted 10 / 22, all on the correct cases.
No predicted finding cites evidence captured after `audit_at` (enforced by `validate_output.py`).

### Remaining sample errors (11 cases, all inside VERIFICATION)

| Cause | Cases | Why it is hard |
|---|---|---|
| Anonymized analytics record not linked to the person | 03, 04, 21, 25, 26, 27, 28 | After anonymization the record carries no email, hash, phone or `user_id` in any participant file. The only trace is an `ANONYMIZE_RECORD` activity in a batch that mixes several people. Pairing by batch order was tried and was right in only 1 of 3 batches, so it was removed. |
| Account chosen from the wrong batch slot | 04, 23, 28/29 | The account id never appears next to the person's identifiers. The agent falls back to the deletion workflow's own activity (time closest to `reported_at`, job result consistent with `reported_status`). When two cases share a batch, the same timestamp and the same result, they cannot be separated. |
| Retained audit record absent from all participant files | 18, 20 | `audit_record_6645` and `audit_record_5569` do not appear in any participant-visible file. |

## 2. Full evaluation run (518 cases, `output.csv`)

| | Count |
|---|---|
| INCOMPLETE | 357 |
| COMPLETE | 151 |
| NOT_APPLICABLE | 10 (exactly the 10 requests that the privacy-intake activity stream also classified as non-deletion) |
| Contract problems found by `validate_output.py` | 0 |
| Runtime | ≈2 s, no model calls (see `usage_report.md`) |

Spot checks against raw evidence (e.g. `case_488`, `case_34`, `case_55`, `case_220`) confirmed the linked
resources, states and cited files by hand.

## 3. Additional evaluation cases created by the team

`custom_cases.py` builds small synthetic worlds and runs them through the real `CaseAudit` and planner code.

| # | Case | What it tests | Expected | Result |
|---|---|---|---|---|
| 1 | `historical_email_and_lookalike_decoy` | Request arrives with an old email from `user_audit_log`; a `old.person.jr@…` record belongs to someone else | INCOMPLETE: only `search_9002` reported; decoy `search_9003` ignored | PASS |
| 2 | `evidence_after_audit_is_ignored` | A capture after `audit_at` shows the profile again | COMPLETE, citing only the pre-audit capture | PASS |
| 3 | `flows_disabled_before_dependent_records` | Active sync, restorable backup, identifiable analytics, shared support thread, exposed tombstone | Remediation order DISABLE → BLOCK → REDACT → ANONYMIZE; tombstone REDACT, not DELETE | PASS |
| 4 | `non_deletion_request_in_spanish` | "Quisiera recibir una copia de mis datos…" | NOT_APPLICABLE with `[]` | PASS |
| 5 | `workflow_claim_does_not_prove_deletion` | Activity says SUCCESS but a later snapshot still has the profile | INCOMPLETE with a remaining-record finding | PASS |

**5 / 5 pass.**

## 4. Failures found and improvements made

Each change was measured on the 32 labelled samples (status accuracy / step F1 / sequence accuracy):

| Step | Problem found | Change | Status | Step F1 | Seq. |
|---|---|---|---|---|---|
| 0 | First end-to-end version | — | 0.938 | 0.847 | 0.344 |
| 1 | A legal-hold PDF listing many `user_…` ids linked one tombstone to five people | Document aliases that are user ids are no longer used. A multi-resource document gives each resource only the identifiers printed on its own line. | | | |
| 2 | An empty scoped inventory snapshot "proved" profiles absent | Absence is inferred only from full primary/replica database captures, never from scoped inventories | | | |
| 3 | Retained audit records seen only in files captured after `audit_at` were dropped | Identity links may come from any capture, but **state** is read only from evidence visible at `audit_at`. Unseen records still get their required post-remediation check. | 1.000 | 0.902 | 0.438 |
| 4 | Same person with two requests (Feb and Sep) | Each record is given to the request whose audit window it was first seen in | | | |
| 5 | A read-replica captured before the request hid a later security record | SQL absence counts only for snapshots taken between `requested_at` and `audit_at`, and never for retained categories | 1.000 | 0.925 | 0.562 |
| 6 | Accounts in the same deletion batch were swapped | Activity matching also checks that the job result agrees with the reported status (SUCCESS↔COMPLETE, PARTIAL↔PARTIALLY_COMPLETE, FAILED↔NOT_STARTED), as a 30-minute penalty rather than a hard rule | 1.000 | 0.950 | 0.594 |
| 7 | Deleted profile with no lookup but a visible tombstone | A visible deleted-account tombstone for the subject is accepted as proof that the profile is absent | 1.000 | **0.955** | **0.656** |

Other fixes along the way:

- Output was sorted as text (`case_100` before `case_33`). It is now sorted numerically, matching the input file.
- The intent rules first matched "copy of my profile" as an access request. Negation phrases were tightened and now decide all 550 public request texts confidently.

## 5. Known limitations

- Anonymized analytics with no identifiers are not reported for COMPLETE cases (see §1). This affects verification steps only, not the status.
- Account selection from the activity stream is a heuristic when no evidence names the account.
- The screenshot facts are a cached transcription (see `usage_report.md`). If the images change, re-run `--refresh-vision`.
