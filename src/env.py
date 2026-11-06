"""Tiny .env loader (standard library only).

The project never prints or commits secrets. Environment variables that are
already set take precedence over values in the file.
"""

import os
from pathlib import Path
from typing import Optional


def load_env(path: Optional[Path] = None) -> None:
    candidates = []
    if path is not None:
        candidates.append(Path(path))
    candidates.extend([Path.cwd() / ".env", Path(__file__).resolve().parents[1] / ".env"])
    for candidate in candidates:
        if not candidate.is_file():
            continue
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
            if key and key not in os.environ:
                os.environ[key] = value
        return
