"""Conservative detection of explicit instruction overrides, not a security proof.

Reject the whole request instead of editing passages or silently dropping sources.
Only the text inspected here is normalised; original evidence remains untouched.
"""
import re
import unicodedata

GUARD_VERSION = 'instruction-guard-v2'
PATTERNS = tuple(re.compile(pattern, re.IGNORECASE) for pattern in (
    # Require an adjacent model-instruction target. Ordinary rules/evidence
    # elsewhere in an immigration sentence are not an override request.
    r'\b(?:ignore|disregard|forget|override|bypass)\s+(?:all\s+)?(?:(?:previous|above|prior|these|your|earlier)\s+)+(?:instructions?|prompts?)\b',
    r'\b(?:ignore|disregard|forget|override|bypass)\s+(?:the\s+)?(?:all\s+)?(?:system|developer|model|assistant)\s+(?:instructions?|prompts?|rules)\b',
    r'\b(?:ignore|disregard|forget|override|bypass)\s+all\s+(?:instructions?|prompts?)\b',
    r'\b(?:system|developer)\s+override\b',
    r'(?:^|\n)\s*(?:system|developer|assistant)\s*:',
    r'<\|(?:im_start|start_header_id)\|>\s*(?:system|developer|assistant)\b',
    r'\[/?INST\]|<<\s*/?SYS\s*>>',
))


def contains_instruction_override(text: str) -> bool:
    normalised = unicodedata.normalize('NFKC', text)
    normalised = ''.join(c for c in normalised if unicodedata.category(c) != 'Cf')
    # Keep line boundaries for role-spoofing detection, collapse spaces for
    # override instructions split over multiple lines.
    return any(pattern.search(normalised) or pattern.search(' '.join(normalised.split()))
               for pattern in PATTERNS)
