"""Case assembly: identity resolution -> resource discovery -> state at audit_at -> plan."""
import hashlib
import re
from collections import defaultdict

from .common import parse_ts, prefix_of, read_csv, system_of
from .evidence import EvidenceStore, Observation
from . import intent
from .planner import build_steps

LINK_RE = re.compile(r"linked (\S+) \(([^)]*)\) to (\S+) and (user_\d+)")
STATUS_RESULT = {"COMPLETE": "SUCCESS", "PARTIALLY_COMPLETE": "PARTIAL", "NOT_STARTED": "FAILED"}
ATTACH_RE = re.compile(r"confirmed (\S+) \(([^)]*)\) belongs only to (\S+) and (user_\d+)")


class World:
    """Everything that is shared by all cases (loaded once)."""

    def __init__(self, use_llm=False):
        self.use_llm = use_llm
        self.identities = {r["user_id"]: r for r in read_csv("user_identities.csv")}
        self.audit_log = read_csv("user_audit_log.csv")
        self.activities = read_csv("system_activity.csv")
        self.rules = read_csv("deletion_rules.csv")
        self._build_identity_index()
        self._build_catalog()
        self.store = EvidenceStore(self.activities, self.aliases)
        self.activity_by_resource = defaultdict(list)
        for a in self.activities:
            self.activity_by_resource[a["resource_id"]].append(a)
        self._index_owners()

    # ------------------------------------------------------------ identities
    def _build_identity_index(self):
        self.user_keys = defaultdict(set)
        self.email_owner = {}
        self.key_owner = defaultdict(set)
        for uid, r in self.identities.items():
            self._add_key(uid, "uid:" + uid.lower())
            self._add_email(uid, r["email"])
            if r["email_hash"]:
                self._add_key(uid, "hash:" + r["email_hash"].lower())
            self._add_phone(uid, r["phone"])
        for a in self.audit_log:
            uid = a["user_id"]
            for v in (a["old_value"], a["new_value"]):
                if not v:
                    continue
                if a["field_name"] == "email":
                    self._add_email(uid, v)
                elif a["field_name"] == "email_hash":
                    self._add_key(uid, "hash:" + v.lower())
                elif a["field_name"] == "phone":
                    self._add_phone(uid, v)

    def _add_key(self, uid, key):
        self.user_keys[uid].add(key)
        self.key_owner[key].add(uid)

    def _add_email(self, uid, email):
        e = email.strip().lower()
        self.email_owner.setdefault(e, uid)
        self._add_key(uid, "email:" + e)
        self._add_key(uid, "hash:" + hashlib.sha256(e.encode()).hexdigest())
        self._add_key(uid, "hash:" + hashlib.sha256(email.strip().encode()).hexdigest())

    def _add_phone(self, uid, phone):
        digits = re.sub(r"\D", "", phone or "")
        if len(digits) >= 8:
            self._add_key(uid, "tel:" + digits)

    def resolve_user(self, email):
        return self.email_owner.get((email or "").strip().lower())

    # ------------------------------------------------------------ data catalog
    def _build_catalog(self):
        self.aliases = {}
        self.catalog = []   # (time, resource_id, user_id, activity_id)
        for a in self.activities:
            if a["event_type"] != "LINK_RESOURCE_IDENTITY":
                continue
            m = LINK_RE.search(a["details"]) or ATTACH_RE.search(a["details"])
            if not m:
                continue
            rid, alias, email, uid = m.groups()
            if alias and alias != rid:
                self.aliases[alias] = rid
            self.catalog.append((parse_ts(a["event_time"]), rid, uid, a["activity_id"]))

    # ------------------------------------------------------------ owners
    def _index_owners(self):
        """resource -> users that any observation (any time) ties it to."""
        self.owners = defaultdict(set)
        for o in self.store.observations:
            for k in o.keys:
                for uid in self.key_owner.get(k, ()):
                    self.owners[o.resource_id].add(uid)
        for _, rid, uid, _ in self.catalog:
            self.owners[rid].add(uid)

    def assign_accounts(self, requests):
        """Link each deletion subject to their account.

        Identifier evidence wins. Users with no identifier-linked account get the closest unclaimed
        account deletion run by the deletion workflow between requested_at and audit_at, matched to
        the workflow's reported_at time (the workflow's own claim names the account it acted on).
        """
        self.account_of = {}
        self.assigned_by_activity = set()
        self.user_cases = defaultdict(list)
        claimed = set()
        pending = []
        for q in requests:
            uid = self.resolve_user(q["email"])
            if not uid or not intent.authorises_deletion(q["request_text"]):
                continue
            self.user_cases[uid].append((q["case_id"], parse_ts(q["audit_at"])))
            accts = sorted(r for r, us in self.owners.items() if prefix_of(r) == "account" and uid in us)
            if accts:
                self.account_of[q["case_id"]] = accts
                claimed.update(accts)
            else:
                pending.append(q)
        cands = []
        for q in pending:
            req, rep, aud = parse_ts(q["requested_at"]), parse_ts(q["reported_at"]), parse_ts(q["audit_at"])
            for a in self.activities:
                if a["target_system"] != "account_service" or a["event_type"] != "DELETE_RECORD":
                    continue
                t = parse_ts(a["event_time"])
                if not (req <= t <= aud):
                    continue
                if self.owners.get(a["resource_id"]):
                    continue
                # the workflow's reported status is derived from its own job result
                consistent = STATUS_RESULT.get(q["reported_status"]) == a["reported_result"]
                cost = abs((t - rep).total_seconds()) + (0 if consistent else 1800)
                cands.append((cost, a["event_time"], q["case_id"], a["resource_id"]))
        cands.sort()
        done = set()
        for _, _, cid, rid in cands:
            if cid in done or rid in claimed:
                continue
            self.account_of[cid] = [rid]
            self.assigned_by_activity.add((cid, rid))
            claimed.add(rid)
            done.add(cid)


class CaseAudit:
    def __init__(self, world, q):
        self.w = world
        self.q = q
        self.audit_at = parse_ts(q["audit_at"])
        self.requested_at = parse_ts(q["requested_at"])
        self.uid = world.resolve_user(q["email"])
        self.notes = []

    def visible(self, o):
        return o.file_time is not None and o.file_time <= self.audit_at

    def discover(self):
        w, uid = self.w, self.uid
        keys = w.user_keys.get(uid, set())
        # Identity links may come from any capture: which records belong to the subject does not
        # change over time. Their *state* is only ever read from evidence visible at audit_at.
        linked = {}
        for o in w.store.observations:
            if o.keys & keys:
                linked.setdefault(o.resource_id, o.evidence_id)
        for t, rid, cuid, aid in w.catalog:
            if cuid == uid:
                linked.setdefault(rid, aid)
        for rid in w.account_of.get(self.q["case_id"], []):
            linked.setdefault(rid, "activity-assignment")
        # follow resource references (search doc -> source account, restore -> restored copy)
        changed = True
        while changed:
            changed = False
            for o in w.store.observations:
                if o.resource_id in linked:
                    continue
                refs = {k[4:] for k in o.keys if k.startswith("res:")}
                if refs & set(linked):
                    linked[o.resource_id] = o.evidence_id
                    changed = True
        out = {}
        for rid, ev in linked.items():
            if not system_of(rid):
                continue
            if not self.owns_in_time(rid):
                continue
            out[rid] = ev
        return out

    def owns_in_time(self, rid):
        """When one person filed several requests, give each record to the request it was seen for:
        the earliest request whose audit_at is at or after the record's first sighting."""
        cases = self.w.user_cases.get(self.uid, [])
        if len(cases) < 2:
            return True
        if (self.q["case_id"], rid) in self.w.assigned_by_activity:
            return True
        times = [o.ts or o.file_time for o in self.w.store.by_resource.get(rid, []) if o.keys & self.w.user_keys[self.uid]]
        times += [t for t, r, u, _ in self.w.catalog if r == rid and u == self.uid]
        if not times:
            return True
        first = min(times)
        owner = None
        for cid, aud in sorted(cases, key=lambda x: x[1]):
            if aud >= first:
                owner = cid
                break
        if owner is None:
            owner = max(cases, key=lambda x: x[1])[0]
        return owner == self.q["case_id"]

    def state_of(self, rid):
        """Latest visible observation for a resource (SQL snapshots also prove absence)."""
        obs = [o for o in self.w.store.by_resource.get(rid, []) if self.visible(o) and o.state]
        system = system_of(rid)
        present_in = set()
        for o in obs:
            present_in.add(o.evidence_id)
        retained = prefix_of(rid) in ("audit_record", "legal_hold")   # absence proves nothing useful here
        for eid, covered in ({} if retained else self.w.store.sql_coverage).items():
            ft = self.w.store.file_time[eid]
            # a snapshot taken before the request says nothing about whether the deletion happened
            if self.requested_at <= ft <= self.audit_at and system in covered \
                    and rid not in self.w.store.sql_present[eid]:
                obs.append(Observation(eid, ft, ft, system, rid, "ABSENT", set(), "sql_absence", "sql_absence"))
        if not obs:
            return None
        obs.sort(key=lambda o: (o.ts or o.file_time, o.file_time, o.source != "sql_absence", o.evidence_id))
        return obs[-1]

    def run(self):
        q = self.q
        if not intent.authorises_deletion(q["request_text"], use_llm=self.w.use_llm):
            return "NOT_APPLICABLE", [], {"reason": "request does not authorise deletion"}
        if not self.uid:
            return "NOT_APPLICABLE", [], {"reason": "requester identity not found"}
        linked = self.discover()
        # a visible deleted-account tombstone for this subject is evidence that the profile is gone
        uid_key = "uid:" + self.uid
        tomb = [o for o in self.w.store.observations if o.system == "identity_service" and self.visible(o)
                and uid_key in o.keys]
        tomb.sort(key=lambda o: (o.ts or o.file_time, o.evidence_id))
        resources = {}
        for rid in linked:
            latest = self.state_of(rid)
            if latest is None and prefix_of(rid) == "account" and tomb:
                t = tomb[-1]
                latest = Observation(t.evidence_id, t.file_time, t.ts, "account_service", rid, "ABSENT",
                                     set(), "tombstone", "tombstone")
            hints = {o.hint for o in self.w.store.by_resource.get(rid, [])}
            resources[rid] = {"latest": latest, "hints": hints}
        status, steps = build_steps(resources, self.w, self)
        return status, steps, {"user": self.uid, "resources": {r: (v["latest"].state if v["latest"] else None)
                                                               for r, v in resources.items()}}
