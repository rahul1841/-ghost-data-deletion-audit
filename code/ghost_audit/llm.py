"""Thin, optional wrapper around the Anthropic SDK with token accounting.

The audit pipeline is deterministic and works without any model. The model is used for:
  * screenshot extraction (`--refresh-vision`), cached on disk;
  * a fallback intent check for request texts the multilingual rules cannot decide (`--llm`).
Every call is counted so evaluation/usage_report.md can be produced from real numbers.
"""
import json
import os
from pathlib import Path

MODEL = os.environ.get("GHOST_AUDIT_MODEL", "claude-opus-5-5")
USAGE = {"calls": 0, "input_tokens": 0, "output_tokens": 0, "by_purpose": {}}
USAGE_FILE = Path(__file__).resolve().parents[1] / "evaluation" / "last_run_usage.json"


def available():
    try:
        import anthropic  # noqa: F401
    except ImportError:
        return False
    return True


def complete(content, max_tokens=1024, purpose="general", system=None):
    import anthropic
    client = anthropic.Anthropic()
    kwargs = dict(model=MODEL, max_tokens=max_tokens, messages=[{"role": "user", "content": content}],
                  output_config={"effort": "low"})
    if system:
        kwargs["system"] = system
    try:
        resp = client.beta.messages.create(betas=["server-side-fallback-2026-07-01"], fallbacks="default", **kwargs)
    except anthropic.BadRequestError:
        resp = client.messages.create(**kwargs)
    u = resp.usage
    USAGE["calls"] += 1
    USAGE["input_tokens"] += u.input_tokens
    USAGE["output_tokens"] += u.output_tokens
    p = USAGE["by_purpose"].setdefault(purpose, {"calls": 0, "input_tokens": 0, "output_tokens": 0})
    p["calls"] += 1
    p["input_tokens"] += u.input_tokens
    p["output_tokens"] += u.output_tokens
    if resp.stop_reason == "refusal":
        return ""
    return "".join(b.text for b in resp.content if getattr(b, "type", "") == "text")


def save_usage(extra=None):
    data = dict(USAGE, model=MODEL)
    if extra:
        data.update(extra)
    USAGE_FILE.parent.mkdir(parents=True, exist_ok=True)
    USAGE_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")
