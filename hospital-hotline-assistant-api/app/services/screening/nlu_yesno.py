"""Shared bilingual yes / no / uncertain classifier for short patient replies.

Extracted from the screening ingest node so the VN name-confirm step (and any
other pre-chat orchestration) can reuse the same bare-affirmation / denial /
uncertainty patterns without duplicating regexes.
"""

from __future__ import annotations

import re
from typing import Literal

YesNoAnswer = Literal["yes", "no", "uncertain", "other"]

# Sequence of affirmation tokens; Thai polite particles join without spaces
# ("ใช่ค่ะ" = ใช่ + ค่ะ), so the separator is optional.
_AFF_TOKEN = r"(?:yes|yeah|yep|sure|ok|okay|ใช่|มี|ครับผม|ครับ|ค่ะ|คะ)"
BARE_AFFIRMATION = re.compile(
    rf"^\s*{_AFF_TOKEN}(?:[\s,.!]*{_AFF_TOKEN})*[\s,.!]*$",
    re.IGNORECASE,
)

# Bare denials — plain "no" answers and the standard denial chips.
# Keep this identical to the clinical ingest patterns so strip_unscoped_denial
# behavior is unchanged; identity-confirm phrases live in _CONFIRM_NO below.
_NEG_CORE = (
    r"(?:no|nope|none(?:\s+of\s+(?:these|those))?|not\s+really|"
    r"no\s+other\s+symptoms?|nothing(?:\s+else)?|i\s+feel\s+(?:completely\s+)?(?:fine|ok(?:ay)?)|"
    r"ไม่ใช่|ไม่มีอาการ(?:เหล่านี้|อื่น)?|ไม่มี|ไม่|เปล่า)"
)
_NEG_RIDER = r"(?:ครับผม|ครับ|ค่ะ|คะ|นะ|เลย|แล้ว|จ้ะ|จ้า|เพิ่มเติม|เพิ่ม)"
_NEG_TOKEN = rf"(?:{_NEG_CORE}|{_NEG_RIDER})"
BARE_DENIAL = re.compile(
    rf"^\s*{_NEG_TOKEN}(?:[\s,.!]*{_NEG_TOKEN})*[\s,.!]*$", re.IGNORECASE
)

# Bare uncertainty ("not sure", "ไม่แน่ใจเลยครับ") — carries no clinical
# information at all; findings must stay unknown so the question re-asks.
_UNC_CORE = (
    r"(?:not\s+sure|don'?t\s+know|dunno|no\s+idea|maybe|perhaps|possibly|unsure|"
    r"ไม่(?:ค่อย)?แน่ใจ|ไม่รู้|ไม่ทราบ|อาจจะ)"
)
_UNC_RIDER = (
    r"(?:honestly|really|i'?m|i\s+am|i|about\s+that|"
    rf"มั้ง|จริง\s?ๆ|เหมือนกัน|{_NEG_RIDER})"
)
_UNC_TOKEN = rf"(?:{_UNC_CORE}|{_UNC_RIDER})"
BARE_UNCERTAINTY = re.compile(
    rf"^\s*{_UNC_TOKEN}(?:[\s,.!?]*{_UNC_TOKEN})*[\s,.!?]*$", re.IGNORECASE
)
UNC_CORE_RE = re.compile(_UNC_CORE, re.IGNORECASE)

# Identity-confirm phrases, composable with the bare tokens above so natural
# compounds classify too: "yes that's me", "ใช่ค่ะ ฉันเอง", "no, wrong person".
# These stay OUT of the clinical BARE_* patterns (imported by ingest) — an
# identity "right/correct" must never count as a symptom affirmation.
_YES_PHRASE = (
    r"(?:that'?s\s+(?:me|right|correct)|this\s+is\s+me|it'?s\s+me|i\s+am|"
    r"correct|right|exactly|of\s+course|certainly|definitely|"
    r"ใช่แล้ว|ถูกต้อง|ถูกแล้ว|ฉันเอง|ผมเอง|ดิฉันเอง|"
    r"ใช่ฉัน|ใช่ผม|ใช่ดิฉัน|ใช่คนนี้|เป็นฉัน|เป็นผม|แน่นอน|อือ)"
)
_YES_RIDER = r"(?:นะ|เลย|แล้ว|จ้ะ|จ้า|เอง)"
_CONFIRM_YES_TOKEN = rf"(?:{_AFF_TOKEN}|{_YES_PHRASE}|{_YES_RIDER})"
CONFIRM_YES = re.compile(
    rf"^\s*{_CONFIRM_YES_TOKEN}(?:[\s,.!]*{_CONFIRM_YES_TOKEN})*[\s,.!]*$",
    re.IGNORECASE,
)

_NO_PHRASE = (
    r"(?:that'?s\s+not\s+(?:me|my\s+name)|that'?s\s+(?:wrong|incorrect)|"
    r"not\s+(?:me|mine|correct|right)|(?:i'?m|i\s+am)\s+not|"
    r"wrong(?:\s+(?:name|person|patient|one))?|different\s+person|"
    r"ไม่ใช่(?:ฉัน|ผม|ดิฉัน|ชื่อ(?:นี้)?)?|คนละคน|ชื่อผิด|ผิดคน|ไม่ถูก(?:ต้อง)?)"
)
_CONFIRM_NO_TOKEN = rf"(?:{_NEG_TOKEN}|{_NO_PHRASE}|{_YES_RIDER})"
CONFIRM_NO = re.compile(
    rf"^\s*{_CONFIRM_NO_TOKEN}(?:[\s,.!]*{_CONFIRM_NO_TOKEN})*[\s,.!]*$",
    re.IGNORECASE,
)
# A "no" needs at least one substantive negative — riders alone don't count.
_NO_CORE_RE = re.compile(rf"(?:{_NEG_CORE}|{_NO_PHRASE})", re.IGNORECASE)


# Resume-choice classifier: "continue the unfinished assessment" vs "start
# over". Spoken answers and the on-screen button labels both route through
# this (labels: "ทำการประเมินต่อ"/"Continue my assessment",
# "เริ่มใหม่"/"Start over").
ResumeChoice = Literal["continue", "start_over", "other"]

_RESUME_CONTINUE_RE = re.compile(
    r"continue|resume|keep\s+going|carry\s+on|pick\s+up|"
    r"ทำต่อ|ต่อเลย|ประเมินต่อ|ทำ(?:การประเมิน)?ต่อ|เอาต่อ|ต่อจากเดิม",
    re.IGNORECASE,
)
_RESUME_STARTOVER_RE = re.compile(
    r"start\s+(?:over|again|new|fresh)|restart|from\s+the\s+beginning|"
    r"เริ่มใหม่|เริ่มต้นใหม่|เอาใหม่|เริ่มกันใหม่",
    re.IGNORECASE,
)


def classify_resume_choice(text: str) -> ResumeChoice:
    """Classify a continue-vs-start-over answer; ambiguous → "other"."""
    cleaned = (text or "").strip()
    if not cleaned:
        return "other"
    cont = bool(_RESUME_CONTINUE_RE.search(cleaned))
    over = bool(_RESUME_STARTOVER_RE.search(cleaned))
    if cont and not over:
        return "continue"
    if over and not cont:
        return "start_over"
    return "other"


def classify_yes_no(text: str) -> YesNoAnswer:
    """Classify a short patient reply as yes / no / uncertain / other.

    Used by ingest stripping helpers and by the VN name-confirm step. Order
    matters: uncertainty is checked before affirmation so "maybe ok" style
    hedges don't count as yes; denial before affirmation so "ไม่ใช่" wins.
    """
    cleaned = (text or "").strip()
    if not cleaned:
        return "other"
    if BARE_UNCERTAINTY.match(cleaned) and UNC_CORE_RE.search(cleaned):
        return "uncertain"
    # Denial needs a substantive negative core first: compounds whose core is
    # negative ("no, that's wrong", "ไม่ใช่ค่ะ") must not fall through to yes.
    if CONFIRM_NO.match(cleaned) and _NO_CORE_RE.search(cleaned):
        return "no"
    # Affirmation after denial, but bare polite particles (ครับ/ค่ะ) are
    # denial *riders* too — the core requirement above keeps them out of
    # "no", so they still land here as the affirmations they are.
    if BARE_AFFIRMATION.match(cleaned) or CONFIRM_YES.match(cleaned):
        return "yes"
    return "other"
