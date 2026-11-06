"""Tiny .env loader (standard library only).

The project never prints or commits secrets. Environment variables that are
already set take precedence over values in the file.
"""

import os
from pathlib import Path
from typing import Dict, Optional


def load_env(path: Optional[Path] = None) -> Dict[str, str]:
    """Load the first available .env file.

    Values already present in the process environment win.  The parsed values
    are returned as well as written to ``os.environ`` so callers can use
    ``load_env().get("LLM_API_KEY")`` without a second lookup.
    """
    candidates = []
    if path is not None:
        candidates.append(Path(path))
    candidates.extend([Path.cwd() / ".env", Path(__file__).resolve().parents[1] / ".env"])
    for candidate in candidates:
        if not candidate.is_file():
            continue
        values: Dict[str, str] = {}
        try:
            lines = candidate.read_text(encoding="utf-8").splitlines()
        except OSError:
            continue
        for line in lines:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            if line.startswith("export "):
                line = line[len("export ") :].strip()
            key, value = line.split("=", 1)
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            if not key:
                continue
            if key not in os.environ:
                os.environ[key] = value
            values[key] = os.environ[key]
        return values
    return {}
