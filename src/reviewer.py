"""Independent fact-review agent.

The reviewer gets a fresh context containing only the request, the latest
script and the full claim catalogue. It never sees the writer's history.
"""

from typing import Any, Dict, List

from .prompts import REVIEWER_SYSTEM_PROMPT, build_reviewer_prompt
from .providers.base import Provider
from .validation import extract_json


class ReviewerError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


class FactReviewer:
    def __init__(self, provider: Provider):
        self.provider = provider
        self.name = "fact-reviewer"

    def review(
        self,
        request: Dict[str, Any],
        script: Dict[str, Any],
        fact_catalog: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        prompt = build_reviewer_prompt(request, script, fact_catalog)
        response = self.provider.generate(
            REVIEWER_SYSTEM_PROMPT,
            [{"role": "user", "content": prompt}],
            state={
                "phase": "reviewer",
                "request": request,
                "script": script,
                "fact_catalog": fact_catalog,
            },
        )
        text = response.get("text", "")
        obj = extract_json(text)
        if not obj:
            raise ReviewerError("invalid_json", "审核 Agent 没有返回可解析的 JSON")
        verdict = obj.get("verdict")
        if verdict not in ("pass", "fail"):
            raise ReviewerError("invalid_verdict", "审核 verdict 必须是 pass 或 fail")
        findings = obj.get("findings") or []
        if not isinstance(findings, list):
            raise ReviewerError("invalid_findings", "审核 findings 必须是数组")
        normalized = []
        for item in findings:
            if not isinstance(item, dict):
                continue
            severity = item.get("severity", "warning")
            if severity not in ("error", "warning", "info"):
                severity = "warning"
            normalized.append(
                {
                    "severity": severity,
                    "shot": item.get("shot"),
                    "claim": str(item.get("claim", ""))[:500],
                    "message": str(item.get("message", ""))[:1000],
                }
            )
        has_error = any(item["severity"] == "error" for item in normalized)
        if has_error and verdict == "pass":
            verdict = "fail"
        if verdict == "fail" and not has_error:
            normalized.append(
                {
                    "severity": "error",
                    "shot": None,
                    "claim": "",
                    "message": "审核判定 fail，但没有给出 error 级别的具体原因。",
                }
            )
        return {
            "verdict": verdict,
            "findings": normalized,
            "summary": str(obj.get("summary", ""))[:1000],
            "model": response.get("model", getattr(self.provider, "model", "")),
            "usage": response.get("usage", {}),
        }
