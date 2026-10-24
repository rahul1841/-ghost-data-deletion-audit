# Usage Report — final full-dataset run

## Final run that produced `output.csv`

Command: `python code/main.py` (518 requests from `dataset/deletion_requests.csv`).
Raw counters written by the run: `code/evaluation/last_run_usage.json`.

| Provider | Model | Model calls | Input tokens | Output tokens | Total tokens | Avg tokens / request | Est. cost | Est. cost / request |
|---|---|---|---|---|---|---|---|---|
| Anthropic | `claude-opus-5-5` (configured, optional) | 0 | 0 | 0 | 0 | 0 | $0.00 | $0.00 |
| **Overall** | | **0** | **0** | **0** | **0** | **0** | **$0.00** | **$0.00** |

Runtime ≈ 2 seconds on a laptop.

The final run makes no model calls because every decision is deterministic:

- **Request intent:** the multilingual rules decided all 518 request texts confidently. The Claude fallback (`--llm`) is only called for texts the rules cannot decide.
- **PDF evidence:** read with `pdfplumber`.
- **Screenshot evidence:** read from a cached extraction (`code/ghost_audit/vision_cache/image_records.json`).
- **Everything else:** identity resolution, evidence parsing, state reconstruction, policy and step ordering are plain Python.

## One-time screenshot extraction (development, not part of the run)

The 11 screenshots in `dataset/evidence/images/` were transcribed once into the cache during development. The coding agent did this (Claude Code running `claude-opus-5-5`, see `log.txt`), viewing each image, and the facts were written to the cache by hand-checked transcription.

| Provider | Model | Images | Est. input tokens | Est. output tokens | Est. cost |
|---|---|---|---|---|---|
| Anthropic | `claude-opus-5-5` | 11 (12 views) | ≈ 19,000 (≈1,600 per image) | ≈ 4,500 | ≈ $0.17 at $4 / $20 per MTok |

These figures are estimates, because the extraction ran inside the coding session and not through the pipeline's metered client.

To regenerate the cache through the API with metering, run `python code/main.py --refresh-vision`. It needs `pip install anthropic` and credentials. It makes one call per image (11 calls), and the counts land in `last_run_usage.json`.

## Optional LLM path

`python code/main.py --llm` sends only the request texts the rules cannot decide to `claude-opus-5-5`, using the low effort setting, a 256-token cap, and server-side refusal fallback. On the current dataset that is 0 texts, so it costs nothing. In the worst case (all 518 texts), it would be ≈ 518 × ~150 input + ~5 output tokens ≈ 80k tokens ≈ $0.37 total, or ≈ $0.0007 per request.
