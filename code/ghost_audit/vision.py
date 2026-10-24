"""Screenshot evidence -> structured records.

Screenshots are read once by a vision model and the result is cached in
`vision_cache/image_records.json`, so audit runs are deterministic and free.
`python code/main.py --refresh-vision` re-extracts every image with the Claude API
(requires the `anthropic` package and an ANTHROPIC_API_KEY or `ant auth login`).
"""
import base64
import json
import re
from pathlib import Path

from .common import identifier_keys, keys_of, system_of
from . import llm

CACHE = Path(__file__).resolve().parent / "vision_cache" / "image_records.json"

PROMPT = """You are extracting facts from a screenshot of an internal admin tool used in a data-deletion audit.
Return ONLY a JSON object: {"text": "<every visible label and value, one per line>",
"records": [{"resource_id": "<id such as account_123, search_45, analytics_6, support_7, export_8,
data_flow_9, backup_10, audit_record_11, tombstone_12, marketing_13, object_14>",
"fields": {"<field>": "<value>"}}]}.
Create one record per resource id that is visibly shown. Copy identifiers exactly (emails, phones,
user_ids, names). Include status-like fields such as enabled, restore_allowed, status, owner, email.
Use null for blank or dash values. Do not invent resource ids."""


def _load_cache():
    if CACHE.exists():
        return json.loads(CACHE.read_text(encoding="utf-8"))
    return {}


def refresh(paths):
    """Re-extract all screenshots with Claude and rewrite the cache."""
    cache = _load_cache()
    for path in paths:
        data = base64.standard_b64encode(Path(path).read_bytes()).decode("utf-8")
        content = [{"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": data}},
                   {"type": "text", "text": PROMPT}]
        text = llm.complete(content, max_tokens=4000, purpose="vision")
        m = re.search(r"\{.*\}", text or "", re.S)
        if m:
            cache[Path(path).name] = json.loads(m.group(0))
    CACHE.parent.mkdir(parents=True, exist_ok=True)
    CACHE.write_text(json.dumps(cache, indent=2, ensure_ascii=False), encoding="utf-8")
    return cache


def image_observations(path, eid, ftime, aliases, Observation, derive_state):
    entry = _load_cache().get(Path(path).name)
    if not entry:
        return []
    obs = []
    seen = set()
    for rec in entry.get("records", []):
        rid = rec.get("resource_id")
        system = system_of(rid)
        if not system:
            continue
        fields = rec.get("fields", {})
        state = rec.get("state") or derive_state(system, fields, "screenshot")
        keys = keys_of(fields)
        obs.append(Observation(eid, ftime, ftime, system, rid, state, keys, "screenshot:" + Path(path).stem))
        seen.add(rid)
    text = entry.get("text", "")
    for alias, rid in aliases.items():
        if rid in seen or not alias or not re.search(r"(?<![\w.])" + re.escape(alias) + r"(?![\w])", text):
            continue
        system = system_of(rid)
        keys = set()
        for tok in re.split(r"[\s|,;()·]+", text):
            keys |= identifier_keys(tok.strip(".:"))
        has_direct = any(k.startswith(("email:", "tel:", "hash:")) for k in keys)
        state = derive_state(system, {"email": "x"} if has_direct else {}, "screenshot")
        obs.append(Observation(eid, ftime, ftime, system, rid, state, keys, "screenshot-alias"))
    return obs
