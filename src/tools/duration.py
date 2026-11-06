"""Deterministic duration estimation.

The estimator is intentionally simple and documented:

* Chinese characters are spoken at 4.2 chars/second.
* English words are spoken at 2.5 words/second.
* Every shot has a 0.2s transition.
* Every shot lasts at least 2.0s, even if the narration is shorter.

This is a planning aid, not a replacement for a real TTS measurement. The
project documents that limitation and keeps the constants in data/config.json
so a reviewer can change them.
"""

import re
from typing import Any, Dict, List


CJK_RE = re.compile(r"[\u4e00-\u9fff]")
EN_RE = re.compile(r"[A-Za-z]+(?:[-'][A-Za-z]+)*")


def estimate_script(
    script: Dict[str, Any], duration_config: Dict[str, Any]
) -> Dict[str, Any]:
    zh_rate = float(duration_config.get("zh_chars_per_second", 4.2))
    en_rate = float(duration_config.get("en_words_per_second", 2.5))
    transition = float(duration_config.get("transition_seconds", 0.2))
    min_shot = float(duration_config.get("min_shot_seconds", 2.0))

    shots: List[Dict[str, Any]] = []
    total = 0.0
    for index, shot in enumerate(script.get("shots", []), start=1):
        narration = shot.get("narration", "") if isinstance(shot, dict) else ""
        cjk_chars = len(CJK_RE.findall(narration))
        en_words = len(EN_RE.findall(narration))
        speech_seconds = cjk_chars / zh_rate + en_words / en_rate
        shot_seconds = max(min_shot, speech_seconds)
        total += shot_seconds + transition
        shots.append(
            {
                "index": index,
                "cjk_chars": cjk_chars,
                "en_words": en_words,
                "speech_seconds": round(speech_seconds, 1),
                "shot_seconds": round(shot_seconds, 1),
            }
        )

    return {
        "total_seconds": round(total, 1),
        "shots": shots,
        "method": {
            "zh_chars_per_second": zh_rate,
            "en_words_per_second": en_rate,
            "transition_seconds": transition,
            "min_shot_seconds": min_shot,
        },
    }
