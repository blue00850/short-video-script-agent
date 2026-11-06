"""Core data structures for the short-video script agent.

The project intentionally uses only the Python standard library so that a
reviewer can run it without creating a virtual environment or installing
packages. Python 3.8+ is supported.
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


ALLOWED_ACTIONS = {
    "search_materials",
    "get_material",
    "draft_script",
    "estimate_duration",
    "check_rules",
    "review_facts",
    "ask_user",
    "finish",
}

STATUS_COMPLETED = "completed"
STATUS_NEEDS_INPUT = "needs_input"
STATUS_INSUFFICIENT_EVIDENCE = "insufficient_evidence"
STATUS_CANNOT_SATISFY = "cannot_satisfy"
STATUS_TOOL_ERROR = "tool_error"
STATUS_STEP_LIMIT = "step_limit_reached"
STATUS_MODEL_ERROR = "model_error"
STATUS_INVALID_INPUT = "invalid_input"

ALL_STATUSES = {
    STATUS_COMPLETED,
    STATUS_NEEDS_INPUT,
    STATUS_INSUFFICIENT_EVIDENCE,
    STATUS_CANNOT_SATISFY,
    STATUS_TOOL_ERROR,
    STATUS_STEP_LIMIT,
    STATUS_MODEL_ERROR,
    STATUS_INVALID_INPUT,
}

EXIT_CODES = {
    STATUS_COMPLETED: 0,
    STATUS_NEEDS_INPUT: 1,
    STATUS_INSUFFICIENT_EVIDENCE: 1,
    STATUS_CANNOT_SATISFY: 2,
    STATUS_TOOL_ERROR: 3,
    STATUS_MODEL_ERROR: 3,
    STATUS_STEP_LIMIT: 4,
    STATUS_INVALID_INPUT: 5,
}


@dataclass
class Shot:
    visual: str
    narration: str
    source_ids: List[str] = field(default_factory=list)
    claim_ids: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "visual": self.visual,
            "narration": self.narration,
            "source_ids": list(self.source_ids),
            "claim_ids": list(self.claim_ids),
        }


@dataclass
class Script:
    title: str
    shots: List[Shot] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "title": self.title,
            "shots": [
                dict(index=index, **shot.to_dict())
                for index, shot in enumerate(self.shots, start=1)
            ],
        }

    def all_source_ids(self) -> List[str]:
        seen: List[str] = []
        for shot in self.shots:
            for source_id in shot.source_ids:
                if source_id not in seen:
                    seen.append(source_id)
        return seen

    def all_claim_ids(self) -> List[str]:
        seen: List[str] = []
        for shot in self.shots:
            for claim_id in shot.claim_ids:
                if claim_id not in seen:
                    seen.append(claim_id)
        return seen


@dataclass
class Decision:
    action: str
    args: Dict[str, Any] = field(default_factory=dict)
    reason: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {"action": self.action, "args": self.args, "reason": self.reason}


@dataclass
class Budget:
    max_steps: int = 12
    max_tool_calls: int = 10
    max_reviews: int = 2
    max_json_repairs: int = 2
    steps: int = 0
    tool_calls: int = 0
    reviews: int = 0
    json_repairs: int = 0
    model_calls: int = 0

    def step_exhausted(self) -> bool:
        return self.steps >= self.max_steps

    def tool_exhausted(self) -> bool:
        return self.tool_calls >= self.max_tool_calls

    def snapshot(self) -> Dict[str, int]:
        return {
            "steps_used": self.steps,
            "max_steps": self.max_steps,
            "tool_calls_used": self.tool_calls,
            "max_tool_calls": self.max_tool_calls,
            "reviews_used": self.reviews,
            "max_reviews": self.max_reviews,
            "json_repairs_used": self.json_repairs,
            "max_json_repairs": self.max_json_repairs,
            "model_calls": self.model_calls,
        }


@dataclass
class InputError:
    field: str
    message: str

    def to_dict(self) -> Dict[str, str]:
        return {"field": self.field, "message": self.message}
