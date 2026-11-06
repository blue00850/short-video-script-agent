"""Provider interface and errors."""

from typing import Any, Dict, List, Optional


class ProviderError(Exception):
    def __init__(self, code: str, message: str, retryable: bool = False):
        super().__init__(message)
        self.code = code
        self.message = message
        self.retryable = retryable

    def to_dict(self) -> Dict[str, Any]:
        return {"code": self.code, "message": self.message, "retryable": self.retryable}


class Provider:
    name = "base"
    model = "base"

    def generate(
        self,
        system: str,
        messages: List[Dict[str, str]],
        state: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        raise NotImplementedError
