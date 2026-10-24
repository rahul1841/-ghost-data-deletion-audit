"""Does the request text authorise deletion?

Multilingual rules decide almost every request. Anything the rules cannot decide confidently
is optionally sent to Claude (`--llm`); without a model it falls back to the rule score.
"""
import re

from . import llm

# strong deletion vocabulary (en, es, pt, fr, de, it, ja, ko, zh)
DELETE_PATTERNS = [
    r"\bdelet", r"\beras", r"\bpermanent(ly)? (account )?(delet|remov|clos)", r"\bclose(d)? (my|this|the) account",
    r"\b(would like|want) it closed", r"\bclose the account", r"\bclose (it|everything)",
    r"\bremove (my|the|this) (account|profile|personal)", r"\bremove .{0,40}(profile|account)",
    r"\b(account|profile).{0,60}\bremov", r"\bdisconnected my account",
    r"elimin", r"exclus", r"exclu[ií]", r"suppr", r"l[öo]sch", r"cancell", r"削除", r"삭제", r"删除",
    r"\bforget me\b", r"right to be forgotten", r"\bdeletion\b", r"\bremov", r"\b(is|are) gone\b",
]
# phrases that say the customer is NOT asking for deletion; these override deletion words
OTHER_PATTERNS = [
    r"\b(send me|need) a copy\b", r"\bdownload my\b", r"\bportable format\b", r"\bwhat personal information\b",
    r"\bmarketing lists only\b", r"\bstop (the )?promotional\b", r"\bunsubscribe\b", r"\bopt[- ]?out\b",
    r"\bmisspelled\b", r"\bout of date\b", r"\bchange the email\b", r"\breset(ting)? the login\b",
    r"\bleave my profile\b", r"\bdo not (delete|close|remove)\b", r"\bdon'?t delete\b", r"\bkeep (my|the) account\b",
    r"\bnot (asking for|a request to|requesting) (deletion|erase|delete)", r"\bwithout removing\b",
    r"\bstill (need|want|use) (the|my|it)\b", r"\bcontinue using\b", r"\bleave the account active\b",
    r"\binformation request\b",
]


def score(text):
    t = (text or "").lower().replace("’", "'")
    pos = sum(1 for p in DELETE_PATTERNS if re.search(p, t))
    neg = sum(1 for p in OTHER_PATTERNS if re.search(p, t))
    return pos, neg


def rule_decision(text):
    """Return (authorises_deletion: bool, confident: bool)."""
    pos, neg = score(text)
    if neg:
        return False, True
    if pos:
        return True, True
    return False, False


LLM_SYSTEM = ("You classify customer privacy requests. Answer with exactly one word: DELETE if the "
              "customer asks to delete, erase or close their account or personal data (including asking "
              "to verify or finish an earlier deletion), otherwise OTHER (access, export, correction, "
              "marketing opt-out, login help, etc.).")


def authorises_deletion(text, use_llm=False):
    decision, confident = rule_decision(text)
    if confident or not use_llm or not llm.available():
        return decision
    answer = llm.complete([{"type": "text", "text": text}], max_tokens=256, purpose="intent", system=LLM_SYSTEM)
    if "DELETE" in (answer or "").upper():
        return True
    if "OTHER" in (answer or "").upper():
        return False
    return decision
