"""JSONL trace writer.

Each line is one auditable event. The trace stores tool arguments, a compact
observation summary, the model's stated one-sentence reason, latency and token
usage. It never stores hidden chain-of-thought.
"""

import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional


def _now() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def summarize(value: Any, max_chars: int = 900) -> Any:
    """Turn a tool result into a compact, still-auditable observation."""
    if isinstance(value, dict):
        if "count" in value and "results" in value:
            return {
                "query": value.get("query"),
                "product_id": value.get("product_id"),
                "count": value.get("count"),
                "results": [
                    {
                        "id": row.get("id"),
                        "name": row.get("name"),
                        "claim_ids": row.get("claim_ids"),
                    }
                    for row in value.get("results", [])
                ],
                "hint": value.get("hint"),
            }
        if "shots" in value and "total_seconds" in value:
            return {
                "total_seconds": value.get("total_seconds"),
                "shot_seconds": [
                    row.get("shot_seconds") for row in value.get("shots", [])
                ],
                "method": value.get("method"),
            }
        if "checks" in value and "errors" in value:
            return {
                "ok": value.get("ok"),
                "errors": value.get("errors"),
                "warnings": value.get("warnings"),
                "duration": value.get("checks", {}).get("duration", {}),
                "structure": value.get("checks", {}).get("structure", {}),
            }
        if "facts" in value and "id" in value:
            return {
                "id": value.get("id"),
                "name": value.get("name"),
                "facts": [
                    {"claim_id": fact.get("claim_id"), "text": fact.get("text")}
                    for fact in value.get("facts", [])
                ],
            }
        if "script" in value and "estimate" in value:
            script = value.get("script", {})
            return {
                "title": script.get("title"),
                "shot_count": len(script.get("shots", [])),
                "shots": [
                    {
                        "index": index,
                        "narration": shot.get("narration", "")[:80],
                        "source_ids": shot.get("source_ids"),
                    }
                    for index, shot in enumerate(script.get("shots", []), start=1)
                ],
                "total_seconds": value.get("estimate", {}).get("total_seconds"),
            }
    try:
        text = json.dumps(value, ensure_ascii=False)
    except (TypeError, ValueError):
        text = repr(value)
    if len(text) <= max_chars:
        return json.loads(text) if text.startswith(("{", "[")) else text
    return text[:max_chars] + "…(truncated)"


class Trace:
    def __init__(self, path: Optional[Path] = None, meta: Optional[Dict[str, Any]] = None):
        self.path = Path(path) if path else None
        self.start = time.monotonic()
        self._handle = None
        if self.path:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self._handle = self.path.open("w", encoding="utf-8")
        if meta:
            self.emit("run_start", **meta)

    def emit(self, event: str, **fields: Any) -> None:
        record = {
            "ts": _now(),
            "elapsed_ms": int((time.monotonic() - self.start) * 1000),
            "event": event,
        }
        record.update(fields)
        if self._handle:
            self._handle.write(json.dumps(record, ensure_ascii=False) + "\n")
            self._handle.flush()

    def step(
        self,
        step: int,
        action: str,
        args: Any,
        reason: str,
        ok: Optional[bool] = None,
        observation: Any = None,
        error: Any = None,
        elapsed_ms: Optional[int] = None,
        usage: Any = None,
    ) -> None:
        fields: Dict[str, Any] = {
            "step": step,
            "action": action,
            "args": args,
            "reason": reason,
        }
        if ok is not None:
            fields["ok"] = ok
        if observation is not None:
            fields["observation"] = summarize(observation)
        if error is not None:
            fields["error"] = error
        if elapsed_ms is not None:
            fields["elapsed_ms"] = elapsed_ms
        if usage:
            fields["usage"] = usage
        self.emit("step", **fields)

    def close(self) -> None:
        if self._handle:
            self._handle.close()
            self._handle = None
