"""Shared helpers: paths, time parsing, identifier normalisation, resource kinds."""
import csv
import re
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
DATASET = REPO_ROOT / "dataset"

EMAIL_RE = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")
HASH_RE = re.compile(r"^[0-9a-f]{64}$")
USER_RE = re.compile(r"^user_\d+$")
PHONE_RE = re.compile(r"^\+[\d\s().\-]{7,}$")
RESOURCE_RE = re.compile(
    r"\b(account|search|analytics|support|export|data_flow|backup|audit_record|tombstone|legal_hold|"
    r"marketing|object|cache|email_delivery|telemetry)_\d+\b")

# resource-id prefix -> system_id used in answers
PREFIX_SYSTEM = {
    "account": "account_service",
    "search": "search_service",
    "analytics": "analytics_platform",
    "support": "support_platform",
    "export": "export_service",
    "data_flow": "integration_service",
    "backup": "backup_service",
    "audit_record": "security_service",
    "tombstone": "identity_service",
    "legal_hold": "legal_service",
    "marketing": "marketing_platform",
    "object": "object_storage",
    "cache": "cache_service",
    "email_delivery": "email_delivery_service",
    "telemetry": "telemetry_service",
}


def parse_ts(s):
    if not s:
        return None
    s = str(s).strip()
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00")).astimezone(timezone.utc)
    except ValueError:
        return None


def read_csv(name):
    with open(DATASET / name, encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def prefix_of(resource_id):
    m = re.match(r"^([a-z_]+?)_\d+$", resource_id or "")
    return m.group(1) if m else None


def system_of(resource_id):
    return PREFIX_SYSTEM.get(prefix_of(resource_id))


def norm_phone(v):
    digits = re.sub(r"\D", "", v)
    return "tel:" + digits if len(digits) >= 8 else None


def identifier_keys(value):
    """Return normalised identifier keys found in one scalar value."""
    keys = set()
    if value is None or isinstance(value, bool):
        return keys
    s = str(value).strip()
    if not s or s.lower() in ("null", "none", "-", "—"):
        return keys
    low = s.lower()
    if HASH_RE.match(low):
        keys.add("hash:" + low)
    elif USER_RE.match(low):
        keys.add("uid:" + low)
    elif PHONE_RE.match(s):
        p = norm_phone(s)
        if p:
            keys.add(p)
    for e in EMAIL_RE.findall(s):
        keys.add("email:" + e.lower())
    return keys


def walk_values(obj):
    if isinstance(obj, dict):
        for v in obj.values():
            yield from walk_values(v)
    elif isinstance(obj, (list, tuple)):
        for v in obj:
            yield from walk_values(v)
    else:
        yield obj


def keys_of(obj):
    out = set()
    for v in walk_values(obj):
        out |= identifier_keys(v)
    return out
