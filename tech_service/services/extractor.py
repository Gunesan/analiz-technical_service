from __future__ import annotations

import re
from typing import Dict, List, Tuple

# Extend this mapping freely
KEYWORDS: Dict[str, List[str]] = {
    "black screen": ["black screen", "blank screen", "no display", "screen is off"],
    "broken screen": ["broken screen", "cracked screen", "shattered glass", "screen cracked"],
    "battery issue": ["battery issue", "battery drain", "won't charge", "not charging", "charging issue", "battery problem"],
    "overheating": ["overheating", "overheat", "too hot", "heating up", "fan working constantly"],
    "no sound": ["no sound", "no audio", "speaker not working", "mute"],
    "won't turn on": ["won't turn on", "not turning on", "doesn't start", "won't start"],
}


def _normalize(text: str) -> str:
    return re.sub(r"[^a-z0-9\s]", " ", text.lower())


def extract_labels(text: str) -> List[Tuple[str, float, str]]:
    """Return list of (label, score, source)."""
    txt = _normalize(text)
    found: Dict[str, float] = {}
    for canonical, synonyms in KEYWORDS.items():
        for s in synonyms:
            if re.search(rf"\b{re.escape(s)}\b", txt):
                score = 1.0 if s == canonical else 0.85
                found[canonical] = max(found.get(canonical, 0.0), score)
    return [(k, v, "rules") for k, v in sorted(found.items(), key=lambda kv: (-kv[1], kv[0]))]