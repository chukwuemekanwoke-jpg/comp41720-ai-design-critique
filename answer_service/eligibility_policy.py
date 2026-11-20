"""Bounded English policy checks, not a general safety classifier."""
import re
import unicodedata

POLICY_VERSION = 'eligibility-policy-v1'


def normalise(text: str) -> str:
    text = unicodedata.normalize('NFKC', text)
    return ' '.join(''.join(c for c in text if unicodedata.category(c) != 'Cf').split()).lower()


# Inspect the question only. Official evidence can legitimately discuss eligibility.
PERSONAL_REQUESTS = tuple(re.compile(p) for p in (
    r'\b(?:am i|are we|would i be|will i be)\s+(?:not\s+)?eligible\b',
    r'\b(?:do i|do we|would i|will i)\s+qualify\b',
    r'\b(?:whether|if)\s+(?:i qualify|i am (?:not )?eligible)\b',
    r'\b(?:will|would)\s+my\s+(?:\w+\s+){0,3}(?:application|renewal|permission)\s+(?:be\s+)?(?:approved|refused|rejected|succeed|successful)\b',
    r'\b(?:approve|reject|refuse)\s+my\s+(?:\w+\s+){0,3}application\b',
))


def requests_personal_decision(question: str) -> bool:
    return any(p.search(normalise(question)) for p in PERSONAL_REQUESTS)


CLAIMS = re.compile(
    r'\byou\s+(?:are\s+(?:not\s+)?eligible|(?:do\s+not\s+|don.t\s+)?qualify)\b'
    r'|\byour\s+(?:\w+\s+){0,3}(?:application|renewal|permission)\s+'
    r'(?:has been|is|will be|was)\s+(?:approved|refused|rejected|successful)\b'
)


def contains_personal_decision(text: str) -> bool:
    text = normalise(text)
    for match in CLAIMS.finditer(text):
        # Keep explicit uncertainty and conditional general guidance available.
        prefix = text[:match.start()]
        if re.search(r'\b(?:whether|if)\s*$', prefix):
            continue
        return True
    return False
