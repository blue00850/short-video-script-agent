"""The ReAct-style writer loop with budgets, trace and a finish gate."""

import json
import time
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from .models import (
    ALLOWED_ACTIONS,
    Budget,
    STATUS_CANNOT_SATISFY,
    STATUS_COMPLETED,
    STATUS_INSUFFICIENT_EVIDENCE,
    STATUS_MODEL_ERROR,
    STATUS_NEEDS_INPUT,
    STATUS_STEP_LIMIT,
    STATUS_TOOL_ERROR,
    Script,
    Shot,
)
from .prompts import WRITER_SYSTEM_PROMPT, build_task_prompt
from .providers.base import Provider, ProviderError
from .reviewer import FactReviewer, ReviewerError
from .tools import ToolBox
from .tools.duration import estimate_script
from .tools.rules import check_script
from .trace import Trace, summarize
from .validation import parse_script_args, validate_decision


def _now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


class ScriptAgent:
    def __init__(
        self,
        request: Dict[str, Any],
        provider: Provider,
        reviewer: Optional[FactReviewer],
        toolbox: ToolBox,
        config: Dict[str, Any],
        trace: Optional[Trace] = None,
        max_steps: Optional[int] = None,
        max_tool_calls: Optional[int] = None,
    ):
        self.request = request
        self.provider = provider
        self.reviewer = reviewer
        self.toolbox = toolbox
        self.config = config
        self.trace = trace
        self.budget = Budget(
            max_steps=int(max_steps or config.get("max_steps", 12)),
            max_tool_calls=int(max_tool_calls or config.get("max_tool_calls", 10)),
            max_reviews=int(config.get("max_reviews", 2)),
            max_json_repairs=int(config.get("max_json_repairs", 2)),
        )
        self.run_id = datetime.now().strftime("%Y%m%dT%H%M%S") + "-" + uuid.uuid4().hex[:6]
        self.started_at = _now()
        self.started_monotonic = time.monotonic()

        self.messages: List[Dict[str, str]] = [
            {
                "role": "user",
                "content": build_task_prompt(
                    request, self.budget.max_steps, self.budget.max_tool_calls
                ),
            }
        ]
        self.history: List[Dict[str, Any]] = []
        self.last_script: Optional[Script] = None
        self.last_estimate: Optional[Dict[str, Any]] = None
        self.last_check: Optional[Dict[str, Any]] = None
        self.last_review: Optional[Dict[str, Any]] = None
        self.reviewer_passed = False
        self.draft_count = 0
        self.consecutive_tool_errors = 0
        self.usage_totals = {
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
        }
        self.state: Dict[str, Any] = {}

    # ------------------------------------------------------------------ public
    def run(self) -> Dict[str, Any]:
        if self.trace:
            self.trace.emit(
                "run_start",
                run_id=self.run_id,
                provider=self.provider.name,
                model=self.provider.model,
                request=self.request,
                max_steps=self.budget.max_steps,
                max_tool_calls=self.budget.max_tool_calls,
            )

        while not self.budget.step_exhausted():
            self.budget.steps += 1
            step_started = time.monotonic()
            self._refresh_state()
            try:
                response = self.provider.generate(
                    WRITER_SYSTEM_PROMPT, self.messages, self.state
                )
                self.budget.model_calls += 1
                self._record_usage(response.get("usage"))
                decision, parse_error = self._decision_with_repairs(response.get("text", ""))
            except ProviderError as exc:
                return self._result(
                    STATUS_MODEL_ERROR,
                    "模型调用失败：%s" % exc.message,
                    {"error": exc.to_dict()},
                )
            except Exception as exc:  # Defensive provider boundary.
                return self._result(
                    STATUS_MODEL_ERROR,
                    "模型调用异常：%s: %s" % (type(exc).__name__, exc),
                    {"error": {"code": "unexpected_provider_error", "message": str(exc)}},
                )

            if not decision:
                return self._result(
                    STATUS_MODEL_ERROR,
                    "模型连续返回不可解析的决策：%s" % (parse_error or "unknown"),
                    {"error": {"code": "invalid_model_output", "message": parse_error or ""}},
                )

            action = decision["action"]
            args = decision["args"]
            reason = decision["reason"]
            self.messages.append(
                {
                    "role": "assistant",
                    "content": json.dumps(decision, ensure_ascii=False),
                }
            )

            if action == "finish":
                terminal = self._handle_finish(args, reason, step_started)
                if terminal:
                    return terminal
                continue
            if action == "ask_user":
                terminal = self._handle_ask_user(args, reason, step_started)
                if terminal:
                    return terminal
                continue
            if action == "review_facts":
                terminal, observation = self._handle_review(reason, step_started)
                if terminal:
                    return terminal
                self._append_observation("review_facts", observation)
                self._record_history(decision, observation, observation.get("ok", False))
                continue

            terminal, observation = self._handle_tool_or_draft(
                action, args, reason, step_started
            )
            if terminal:
                return terminal
            self._append_observation(action, observation)
            self._record_history(decision, observation, observation.get("ok", False))

        return self._step_limit_result(
            "达到最大决策步数 %d，任务未完成。" % self.budget.max_steps
        )

    # ------------------------------------------------------------------ loop
    def _refresh_state(self) -> None:
        self.state = {
            "phase": "writer",
            "request": self.request,
            "step": self.budget.steps,
            "max_steps": self.budget.max_steps,
            "budget": self.budget.snapshot(),
            "history": list(self.history),
            "last_script": self.last_script.to_dict() if self.last_script else None,
            "last_estimate": self.last_estimate,
            "last_check": self.last_check,
            "last_review": self.last_review,
            "draft_count": self.draft_count,
            "review_count": self.budget.reviews,
            "reviewer_passed": self.reviewer_passed,
        }

    def _decision_with_repairs(
        self, text: str
    ) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
        last_error = None
        for attempt in range(self.budget.max_json_repairs + 1):
            from .validation import extract_json

            obj = extract_json(text)
            if obj:
                decision, errors = validate_decision(obj)
                if decision:
                    return decision, None
                last_error = "；".join(errors)
            else:
                last_error = "响应中没有可解析的 JSON 对象"
            if attempt >= self.budget.max_json_repairs:
                break
            self.budget.json_repairs += 1
            self.messages.append({"role": "assistant", "content": text[:4000]})
            self.messages.append(
                {
                    "role": "user",
                    "content": "你的上一条输出不可解析：%s\n请只输出一个 JSON 对象，格式为 "
                    '{"action": "...", "args": {...}, "reason": "..."}，不要 Markdown。'
                    % last_error,
                }
            )
            if self.trace:
                self.trace.emit(
                    "json_repair",
                    step=self.budget.steps,
                    attempt=self.budget.json_repairs,
                    error=last_error,
                )
            try:
                response = self.provider.generate(
                    WRITER_SYSTEM_PROMPT, self.messages, self.state
                )
            except ProviderError as exc:
                raise
            self.budget.model_calls += 1
            self._record_usage(response.get("usage"))
            text = response.get("text", "")
            if self.trace:
                self.trace.emit(
                    "model_call",
                    step=self.budget.steps,
                    phase="writer_repair",
                    model=response.get("model", self.provider.model),
                    usage=response.get("usage", {}),
                )
        return None, last_error

    def _record_usage(self, usage: Any) -> None:
        if not isinstance(usage, dict):
            return
        for key in ("prompt_tokens", "completion_tokens", "total_tokens"):
            value = usage.get(key)
            if isinstance(value, int):
                self.usage_totals[key] += value

    def _handle_tool_or_draft(
        self, action: str, args: Dict[str, Any], reason: str, step_started: float
    ) -> Tuple[Optional[Dict[str, Any]], Dict[str, Any]]:
        if action == "draft_script":
            if self.budget.tool_exhausted():
                return self._step_limit_result(
                    "工具调用达到上限 %d，任务未完成。" % self.budget.max_tool_calls
                ), {}
            self.budget.tool_calls += 1
            observation = self._draft(args)
            self._trace_step(
                action, args, reason, observation, step_started
            )
            if not observation.get("ok"):
                self.consecutive_tool_errors += 1
                if self.consecutive_tool_errors >= 3:
                    return self._tool_error_result(observation), observation
            else:
                self.consecutive_tool_errors = 0
            return None, observation

        if action not in ("search_materials", "get_material", "estimate_duration", "check_rules"):
            observation = {
                "ok": False,
                "error": {
                    "code": "unknown_action",
                    "message": "不支持的本地动作：%s" % action,
                },
            }
            self._trace_step(action, args, reason, observation, step_started)
            self.consecutive_tool_errors += 1
            return None, observation

        if self.budget.tool_exhausted():
            return self._step_limit_result(
                "工具调用达到上限 %d，任务未完成。" % self.budget.max_tool_calls
            ), {}

        self.budget.tool_calls += 1
        observation = self.toolbox.call(action, args)
        if observation.get("ok"):
            self.consecutive_tool_errors = 0
            data = observation.get("data", {})
            if action == "estimate_duration":
                self.last_estimate = data
            if action == "check_rules":
                self.last_check = data
                self.last_estimate = data.get("estimate", self.last_estimate)
        else:
            self.consecutive_tool_errors += 1
            if self.consecutive_tool_errors >= 3:
                self._trace_step(action, args, reason, observation, step_started)
                return self._tool_error_result(observation), observation

        self._trace_step(action, args, reason, observation, step_started)
        return None, observation

    def _draft(self, args: Dict[str, Any]) -> Dict[str, Any]:
        normalized, problems = parse_script_args(args)
        if problems:
            return {
                "ok": False,
                "error": {
                    "code": "invalid_script",
                    "message": "；".join(problems),
                },
            }
        shots = [Shot(**shot) for shot in normalized["shots"]]
        script = Script(title=normalized["title"], shots=shots)
        estimate = estimate_script(script.to_dict(), self.config.get("duration", {}))
        self.last_script = script
        self.last_estimate = estimate
        self.last_check = None
        self.last_review = None
        self.reviewer_passed = False
        self.draft_count += 1
        return {
            "ok": True,
            "data": {"script": script.to_dict(), "estimate": estimate},
        }

    def _handle_review(
        self, reason: str, step_started: float
    ) -> Tuple[Optional[Dict[str, Any]], Dict[str, Any]]:
        if not self.last_script:
            observation = {
                "ok": False,
                "error": {"code": "no_script", "message": "还没有可审核的脚本"},
            }
            self._trace_step("review_facts", {}, reason, observation, step_started)
            return None, observation
        if self.budget.reviews >= self.budget.max_reviews:
            observation = {
                "ok": False,
                "error": {
                    "code": "review_limit",
                    "message": "事实审核次数已达上限 %d" % self.budget.max_reviews,
                },
            }
            self._trace_step("review_facts", {}, reason, observation, step_started)
            return None, observation
        if not self.reviewer:
            observation = {
                "ok": False,
                "error": {"code": "no_reviewer", "message": "未配置事实审核 Agent"},
            }
            self._trace_step("review_facts", {}, reason, observation, step_started)
            return None, observation

        self.budget.reviews += 1
        try:
            result = self.reviewer.review(
                self.request,
                self.last_script.to_dict(),
                self.toolbox.index.all_facts(),
            )
        except ReviewerError as exc:
            observation = {
                "ok": False,
                "error": {"code": exc.code, "message": exc.message},
            }
            self._trace_step("review_facts", {}, reason, observation, step_started)
            return None, observation
        except ProviderError as exc:
            return (
                self._result(
                    STATUS_MODEL_ERROR,
                    "事实审核模型调用失败：%s" % exc.message,
                    {"error": exc.to_dict()},
                ),
                {},
            )

        self._record_usage(result.get("usage"))
        self.last_review = result
        self.reviewer_passed = result.get("verdict") == "pass"
        if self.trace:
            self.trace.emit(
                "review",
                step=self.budget.steps,
                verdict=result.get("verdict"),
                findings=result.get("findings"),
                summary=result.get("summary"),
                model=result.get("model"),
                usage=result.get("usage"),
                elapsed_ms=int((time.monotonic() - step_started) * 1000),
            )
        observation = {"ok": True, "data": result}
        self._trace_step("review_facts", {}, reason, observation, step_started)
        return None, observation

    def _handle_ask_user(
        self, args: Dict[str, Any], reason: str, step_started: float
    ) -> Optional[Dict[str, Any]]:
        question = args.get("question")
        if not isinstance(question, str) or not question.strip():
            observation = {
                "ok": False,
                "error": {"code": "invalid_arguments", "message": "ask_user.question 不能为空"},
            }
            self._trace_step("ask_user", args, reason, observation, step_started)
            self._append_observation("ask_user", observation)
            self._record_history(
                {"action": "ask_user", "args": args, "reason": reason},
                observation,
                False,
            )
            return None
        kind = args.get("kind")
        status = STATUS_INSUFFICIENT_EVIDENCE if kind == "insufficient_evidence" else STATUS_NEEDS_INPUT
        data = {
            "question": question.strip(),
            "missing": args.get("missing") if isinstance(args.get("missing"), list) else [],
            "options": args.get("options") if isinstance(args.get("options"), list) else [],
            "partial_script": self.last_script.to_dict() if self.last_script else None,
        }
        observation = {"ok": True, "data": data}
        self._trace_step("ask_user", args, reason, observation, step_started)
        self._record_history(
            {"action": "ask_user", "args": args, "reason": reason}, observation, True
        )
        return self._result(status, question.strip(), data)

    def _handle_finish(
        self, args: Dict[str, Any], reason: str, step_started: float
    ) -> Optional[Dict[str, Any]]:
        status_arg = args.get("status")
        if status_arg == "completed":
            if not self.last_script:
                return self._reject_finish(
                    args, reason, step_started, "还没有脚本，不能标记完成"
                )
            estimate = estimate_script(
                self.last_script.to_dict(), self.config.get("duration", {})
            )
            fresh = check_script(
                self.last_script.to_dict(),
                self.request,
                self.toolbox.rules,
                self.toolbox.dataset,
                estimate=estimate,
            )
            fresh.pop("claim_lookup", None)
            self.last_estimate = estimate
            self.last_check = fresh
            if not fresh.get("ok"):
                return self._reject_finish(
                    args,
                    reason,
                    step_started,
                    "终检未通过，不能完成：%s"
                    % "；".join(error.get("message", "") for error in fresh.get("errors", [])),
                )
            if not self.reviewer_passed:
                return self._reject_finish(
                    args,
                    reason,
                    step_started,
                    "尚未通过独立事实审核，不能完成",
                )
            message = args.get("message") or "脚本已通过检查。"
            risks = args.get("risks") if isinstance(args.get("risks"), list) else []
            observation = {
                "ok": True,
                "data": {"status": "completed", "message": message},
            }
            self._trace_step("finish", args, reason, observation, step_started)
            self._record_history(
                {"action": "finish", "args": args, "reason": reason}, observation, True
            )
            return self._completed_result(message, risks)

        if status_arg == "cannot_satisfy":
            if not self.last_check:
                return self._reject_finish(
                    args, reason, step_started, "先检查一次，再判定无法满足"
                )
            if self.last_check.get("ok"):
                return self._reject_finish(
                    args, reason, step_started, "检查已通过，不应判定无法满足"
                )
            if self.draft_count < 2:
                return self._reject_finish(
                    args,
                    reason,
                    step_started,
                    "至少完成一次修正尝试后，才能判定无法满足",
                )
            message = args.get("message") or "当前规则下无法满足目标。"
            risks = args.get("risks") if isinstance(args.get("risks"), list) else []
            observation = {
                "ok": True,
                "data": {"status": "cannot_satisfy", "message": message},
            }
            self._trace_step("finish", args, reason, observation, step_started)
            self._record_history(
                {"action": "finish", "args": args, "reason": reason}, observation, True
            )
            return self._cannot_satisfy_result(message, risks)

        return self._reject_finish(
            args, reason, step_started, "finish.status 必须是 completed 或 cannot_satisfy"
        )

    def _reject_finish(
        self,
        args: Dict[str, Any],
        reason: str,
        step_started: float,
        message: str,
    ) -> Optional[Dict[str, Any]]:
        observation = {"ok": False, "error": {"code": "finish_rejected", "message": message}}
        self._trace_step("finish", args, reason, observation, step_started)
        self._append_observation("finish_rejected", observation)
        self._record_history(
            {"action": "finish", "args": args, "reason": reason}, observation, False
        )
        return None

    # ------------------------------------------------------------------ results
    def _completed_result(self, message: str, risks: List[str]) -> Dict[str, Any]:
        script = self.last_script.to_dict() if self.last_script else None
        return self._result(
            STATUS_COMPLETED,
            message,
            {
                "task_status": STATUS_COMPLETED,
                "title": script.get("title") if script else None,
                "shots": script.get("shots") if script else [],
                "estimated_total_seconds": (
                    self.last_estimate.get("total_seconds") if self.last_estimate else None
                ),
                "target_seconds": self.request.get("target_seconds"),
                "platform": self.request.get("platform"),
                "duration_check": (
                    self.last_check.get("checks", {}).get("duration")
                    if self.last_check
                    else None
                ),
                "brand_check": {
                    "ok": self.last_check.get("ok") if self.last_check else None,
                    "errors": self.last_check.get("errors") if self.last_check else [],
                },
                "materials_used": self._materials_used(),
                "risks": risks,
            },
        )

    def _cannot_satisfy_result(self, message: str, risks: List[str]) -> Dict[str, Any]:
        script = self.last_script.to_dict() if self.last_script else None
        return self._result(
            STATUS_CANNOT_SATISFY,
            message,
            {
                "task_status": STATUS_CANNOT_SATISFY,
                "message": message,
                "target_seconds": self.request.get("target_seconds"),
                "best_attempt": {
                    "title": script.get("title") if script else None,
                    "shots": script.get("shots") if script else [],
                    "estimated_total_seconds": (
                        self.last_estimate.get("total_seconds") if self.last_estimate else None
                    ),
                },
                "blocking_errors": self.last_check.get("errors") if self.last_check else [],
                "risks": risks,
            },
        )

    def _step_limit_result(self, message: str) -> Dict[str, Any]:
        script = self.last_script.to_dict() if self.last_script else None
        return self._result(
            STATUS_STEP_LIMIT,
            message,
            {
                "task_status": STATUS_STEP_LIMIT,
                "message": message,
                "partial_script": script,
                "estimated_total_seconds": (
                    self.last_estimate.get("total_seconds") if self.last_estimate else None
                ),
                "checks": self.last_check,
                "risks": ["达到执行上限，脚本未完成全部检查与审核。"],
            },
        )

    def _tool_error_result(self, observation: Dict[str, Any]) -> Dict[str, Any]:
        error = observation.get("error", {})
        return self._result(
            STATUS_TOOL_ERROR,
            "连续工具调用失败：%s" % error.get("message", "unknown"),
            {"task_status": STATUS_TOOL_ERROR, "error": error},
        )

    def _result(self, status: str, message: str, output: Dict[str, Any]) -> Dict[str, Any]:
        if self.trace:
            self.trace.emit(
                "run_end",
                status=status,
                message=message,
                budget=self.budget.snapshot(),
                usage=self.usage_totals,
            )
            self.trace.close()
        return {
            "run_id": self.run_id,
            "status": status,
            "message": message,
            "input": self.request,
            "output": output,
            "check": self.last_check,
            "review": self.last_review,
            "budget": self.budget.snapshot(),
            "usage": self.usage_totals,
            "provider": {
                "name": self.provider.name,
                "model": self.provider.model,
            },
            "trace_path": str(self.trace.path) if self.trace and self.trace.path else None,
            "timing": {
                "started_at": self.started_at,
                "finished_at": _now(),
                "elapsed_seconds": round(time.monotonic() - self.started_monotonic, 2),
            },
        }

    # ------------------------------------------------------------------ helpers
    def _materials_used(self) -> List[Dict[str, Any]]:
        if not self.last_script:
            return []
        claim_lookup = {}
        for item in self.toolbox.dataset.get("items", []):
            for fact in item.get("facts", []):
                claim_lookup[fact["claim_id"]] = {
                    "material_id": item["id"],
                    "material_name": item.get("name", ""),
                    "claim_id": fact["claim_id"],
                    "text": fact.get("text", ""),
                    "source": fact.get("source", ""),
                }
        used = []
        for claim_id in self.last_script.all_claim_ids():
            if claim_id in claim_lookup:
                used.append(claim_lookup[claim_id])
        return used

    def _trace_step(
        self,
        action: str,
        args: Dict[str, Any],
        reason: str,
        observation: Dict[str, Any],
        step_started: float,
    ) -> None:
        if not self.trace:
            return
        error = observation.get("error") if not observation.get("ok") else None
        self.trace.step(
            step=self.budget.steps,
            action=action,
            args=args,
            reason=reason,
            ok=observation.get("ok"),
            observation=(
                observation.get("data")
                if observation.get("ok")
                else observation
            ),
            error=error,
            elapsed_ms=int((time.monotonic() - step_started) * 1000),
        )

    def _record_history(
        self, decision: Dict[str, Any], observation: Dict[str, Any], ok: bool
    ) -> None:
        self.history.append(
            {
                "step": self.budget.steps,
                "action": decision.get("action"),
                "args": decision.get("args"),
                "reason": decision.get("reason"),
                "ok": ok,
                "observation": summarize(
                    observation.get("data") if ok else observation
                ),
            }
        )

    def _append_observation(self, action: str, observation: Dict[str, Any]) -> None:
        payload = json.dumps(observation, ensure_ascii=False)
        if len(payload) > 8000:
            payload = payload[:8000] + "…(truncated)"
        self.messages.append(
            {"role": "user", "content": "Observation from %s:\n%s" % (action, payload)}
        )
