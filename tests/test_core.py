"""Executable acceptance tests for the short-video script agent.

Run with:  python -m unittest discover -s tests -v

All model calls here use MockProvider. These tests prove orchestration,
guardrails and traceability, not real-model decision quality.
"""

import json
import tempfile
import unittest
from pathlib import Path
from typing import Any, Dict, List

from src.agent import ScriptAgent
from src.data import MaterialIndex, load_brand_rules, load_config, load_materials
from src.models import (
    STATUS_CANNOT_SATISFY,
    STATUS_COMPLETED,
    STATUS_INSUFFICIENT_EVIDENCE,
    STATUS_NEEDS_INPUT,
    STATUS_STEP_LIMIT,
    STATUS_TOOL_ERROR,
)
from src.providers.base import Provider
from src.providers.mock import (
    IMPOSSIBLE,
    NORMAL_P02,
    P01_28,
    P01_38,
    P01_SEMANTIC,
    RULE_VIOLATION,
    MockProvider,
)
from src.reviewer import FactReviewer
from src.tools import ToolBox
from src.tools.duration import estimate_script
from src.tools.rules import check_script
from src.trace import Trace
from src.validation import extract_json, validate_decision, validate_request

ROOT = Path(__file__).resolve().parents[1]
CONFIG = load_config()
DATASET = load_materials()
RULES = load_brand_rules()
MATERIALS = MaterialIndex(DATASET)


def request_p02(**overrides: Any) -> Dict[str, Any]:
    raw = {
        "topic": "小影一键成片怎么帮新手快速出片",
        "audience": "刚做短视频的新手",
        "platform": "抖音",
        "target_seconds": 30,
        "style": "口语化、节奏快",
        "product_id": "P02",
    }
    raw.update(overrides)
    normalized, errors = validate_request(raw)
    assert not errors, errors
    assert normalized is not None
    return normalized


def request_p01(**overrides: Any) -> Dict[str, Any]:
    raw = {
        "topic": "小影字幕功能，静音观看也能看懂",
        "audience": "口播创作者",
        "platform": "抖音",
        "target_seconds": 30,
        "style": "自然、口语化",
        "product_id": "P01",
    }
    raw.update(overrides)
    normalized, errors = validate_request(raw)
    assert not errors, errors
    assert normalized is not None
    return normalized


def request_p03(target: int = 25, **overrides: Any) -> Dict[str, Any]:
    raw = {
        "topic": "小影模板库",
        "audience": "旅行博主",
        "platform": "抖音",
        "target_seconds": target,
        "style": "轻快、生活化",
        "product_id": "P03",
    }
    raw.update(overrides)
    normalized, errors = validate_request(raw)
    assert not errors, errors
    assert normalized is not None
    return normalized


def make_agent(
    scenario: str,
    request: Dict[str, Any],
    trace_path: Path = None,
    max_steps: int = None,
    max_tool_calls: int = None,
    faults: Dict[str, List[Dict[str, str]]] = None,
):
    provider = MockProvider(scenario)
    toolbox = ToolBox(MATERIALS, RULES, CONFIG, request=request, faults=faults)
    reviewer = FactReviewer(provider)
    trace = Trace(trace_path) if trace_path else None
    agent = ScriptAgent(
        request,
        provider,
        reviewer,
        toolbox,
        CONFIG,
        trace=trace,
        max_steps=max_steps,
        max_tool_calls=max_tool_calls,
    )
    return agent, trace


def read_events(path: Path) -> List[Dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def step_events(events: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return [event for event in events if event.get("event") == "step"]


class DurationTests(unittest.TestCase):
    def test_p01_first_draft_is_38_seconds(self):
        result = estimate_script(P01_38, CONFIG["duration"])
        self.assertEqual(38.0, result["total_seconds"])
        self.assertEqual([13.8, 12.1, 11.4], [shot["shot_seconds"] for shot in result["shots"]])

    def test_p01_revision_is_28_seconds(self):
        self.assertEqual(28.0, estimate_script(P01_28, CONFIG["duration"])["total_seconds"])

    def test_minimum_shot_duration_wins_over_short_narration(self):
        result = estimate_script(IMPOSSIBLE, CONFIG["duration"])
        self.assertEqual(6.6, result["total_seconds"])
        self.assertEqual([2.0, 2.0, 2.0], [shot["shot_seconds"] for shot in result["shots"]])

    def test_normal_p02_is_28_seconds(self):
        self.assertEqual(28.0, estimate_script(NORMAL_P02, CONFIG["duration"])["total_seconds"])


class ValidationTests(unittest.TestCase):
    def test_missing_platform_is_invalid_input(self):
        normalized, errors = validate_request(
            {"topic": "小影字幕", "audience": "创作者", "target_seconds": 30}
        )
        self.assertIsNone(normalized)
        self.assertEqual(["platform"], [error.field for error in errors])

    def test_target_must_be_an_integer_in_range(self):
        normalized, errors = validate_request(
            {"topic": "x", "platform": "抖音", "target_seconds": 0}
        )
        self.assertIsNone(normalized)
        self.assertEqual(["target_seconds"], [error.field for error in errors])

    def test_aliases_are_normalized(self):
        normalized, errors = validate_request(
            {"topic": "x", "platform": "douyin", "target_seconds": 30}
        )
        self.assertEqual([], errors)
        self.assertEqual("抖音", normalized["platform"])

    def test_extract_json_tolerates_fences_and_text(self):
        self.assertEqual({"action": "finish"}, extract_json('```json\n{"action":"finish"}\n```'))
        self.assertEqual(
            {"action": "finish"},
            extract_json('前置说明 {"action":"finish"} 后置说明'),
        )
        self.assertIsNone(extract_json("no json here"))

    def test_decision_rejects_unknown_action(self):
        decision, errors = validate_decision({"action": "rm -rf", "args": {}, "reason": ""})
        self.assertIsNone(decision)
        self.assertTrue(errors)


class RuleTests(unittest.TestCase):
    def test_well_grounded_script_passes(self):
        result = check_script(NORMAL_P02, request_p02(), RULES, DATASET)
        self.assertTrue(result["ok"], result["errors"])
        self.assertEqual([], result["errors"])
        self.assertEqual(28.0, result["estimate"]["total_seconds"])

    def test_unknown_claim_is_rejected(self):
        script = json.loads(json.dumps(NORMAL_P02))
        script["shots"][0]["claim_ids"] = ["P02-C99"]
        result = check_script(script, request_p02(), RULES, DATASET)
        codes = [error["code"] for error in result["errors"]]
        self.assertIn("unknown_claim", codes)
        self.assertFalse(result["ok"])

    def test_source_claim_mismatch_is_rejected(self):
        script = json.loads(json.dumps(NORMAL_P02))
        script["shots"][0]["source_ids"] = ["P01"]
        result = check_script(script, request_p02(), RULES, DATASET)
        self.assertIn("source_claim_mismatch", [error["code"] for error in result["errors"]])

    def test_ungrounded_capability_is_rejected(self):
        script = json.loads(json.dumps(NORMAL_P02))
        script["shots"][0]["narration"] = "支持自动识别，效率很高。"
        result = check_script(script, request_p02(), RULES, DATASET)
        self.assertIn("ungrounded_capability", [error["code"] for error in result["errors"]])

    def test_forbidden_efficiency_claim_is_rejected(self):
        result = check_script(RULE_VIOLATION, request_p02(), RULES, DATASET)
        codes = [error["code"] for error in result["errors"]]
        self.assertIn("forbidden_phrase", codes)
        self.assertIn("ungrounded_number", codes)

    def test_title_is_checked_for_ungrounded_capability(self):
        script = json.loads(json.dumps(NORMAL_P02))
        script["title"] = "自动识别，一键出片"
        result = check_script(script, request_p02(), RULES, DATASET)
        title_errors = [error for error in result["errors"] if error.get("field") == "title"]
        self.assertTrue(title_errors)
        self.assertIn("ungrounded_capability", [error["code"] for error in title_errors])

    def test_duration_over_and_under(self):
        over = check_script(NORMAL_P02, request_p02(target_seconds=20), RULES, DATASET)
        under = check_script(NORMAL_P02, request_p02(target_seconds=60), RULES, DATASET)
        self.assertIn("duration_over", [error["code"] for error in over["errors"]])
        self.assertIn("duration_under", [error["code"] for error in under["errors"]])

    def test_impossible_target_is_duration_over(self):
        result = check_script(IMPOSSIBLE, request_p03(target=6), RULES, DATASET)
        self.assertIn("duration_over", [error["code"] for error in result["errors"]])
        self.assertAlmostEqual(6.6, result["estimate"]["total_seconds"])


class AgentTests(unittest.TestCase):
    def test_normal_run_completes_with_trace_and_grounding(self):
        with tempfile.TemporaryDirectory() as tmp:
            trace_path = Path(tmp) / "trace.jsonl"
            agent, trace = make_agent("normal", request_p02(), trace_path)
            result = agent.run()
            events = read_events(trace_path)
        self.assertEqual(STATUS_COMPLETED, result["status"])
        self.assertEqual(28.0, result["output"]["estimated_total_seconds"])
        self.assertEqual(3, len(result["output"]["shots"]))
        self.assertEqual("pass", result["review"]["verdict"])
        self.assertEqual(
            {"P02"}, {row["material_id"] for row in result["output"]["materials_used"]}
        )
        actions = [event["action"] for event in step_events(events)]
        self.assertEqual(
            ["search_materials", "draft_script", "check_rules", "review_facts", "finish"],
            actions,
        )
        self.assertEqual(1, len([event for event in events if event["event"] == "run_end"]))

    def test_p01_38_seconds_is_revised_to_28_after_check(self):
        with tempfile.TemporaryDirectory() as tmp:
            trace_path = Path(tmp) / "trace.jsonl"
            agent, _ = make_agent("p01_30s", request_p01(), trace_path)
            result = agent.run()
            events = step_events(read_events(trace_path))
        self.assertEqual(STATUS_COMPLETED, result["status"])
        self.assertEqual(28.0, result["output"]["estimated_total_seconds"])
        self.assertEqual(38.0, events[1]["observation"]["total_seconds"])
        self.assertEqual(["duration_over"], [e["code"] for e in events[2]["observation"]["errors"]])
        self.assertEqual(28.0, events[3]["observation"]["total_seconds"])
        self.assertEqual([], events[4]["observation"]["errors"])
        self.assertEqual("P01", result["output"]["shots"][0]["source_ids"][0])
        self.assertIn("P01-C1", result["output"]["shots"][0]["claim_ids"])

    def test_rule_violation_is_removed_before_finish(self):
        with tempfile.TemporaryDirectory() as tmp:
            trace_path = Path(tmp) / "trace.jsonl"
            agent, _ = make_agent("rule_violation", request_p02(), trace_path)
            result = agent.run()
            events = step_events(read_events(trace_path))
        self.assertEqual(STATUS_COMPLETED, result["status"])
        first_codes = [e["code"] for e in events[2]["observation"]["errors"]]
        self.assertIn("forbidden_phrase", first_codes)
        self.assertIn("ungrounded_number", first_codes)
        final_text = json.dumps(result["output"]["shots"], ensure_ascii=False)
        self.assertNotIn("效率提升", final_text)
        self.assertNotIn("80%", final_text)

    def test_tool_failure_is_observed_and_query_is_rewritten(self):
        with tempfile.TemporaryDirectory() as tmp:
            trace_path = Path(tmp) / "trace.jsonl"
            agent, _ = make_agent(
                "tool_failure",
                request_p03(target=25),
                trace_path,
                faults={"search_materials": [{"code": "tool_timeout", "message": "注入超时"}]},
            )
            result = agent.run()
            events = step_events(read_events(trace_path))
        self.assertEqual(STATUS_COMPLETED, result["status"])
        self.assertFalse(events[0]["ok"])
        self.assertEqual("小影 模板 竖屏", events[1]["args"]["query"])
        self.assertTrue(events[1]["ok"])

    def test_no_material_asks_for_evidence_instead_of_fabricating(self):
        with tempfile.TemporaryDirectory() as tmp:
            trace_path = Path(tmp) / "trace.jsonl"
            agent, _ = make_agent(
                "no_material",
                request_p02(product_id="P99", topic="小影 AI 数字人直播"),
                trace_path,
            )
            result = agent.run()
            events = step_events(read_events(trace_path))
        self.assertEqual(STATUS_INSUFFICIENT_EVIDENCE, result["status"])
        self.assertIn("素材", result["output"]["question"])
        self.assertEqual([0, 0], [event["observation"]["count"] for event in events[:2]])
        self.assertEqual("ask_user", events[2]["action"])

    def test_impossible_duration_returns_cannot_satisfy_with_calculation(self):
        with tempfile.TemporaryDirectory() as tmp:
            trace_path = Path(tmp) / "trace.jsonl"
            agent, _ = make_agent("impossible", request_p03(target=6), trace_path)
            result = agent.run()
            events = step_events(read_events(trace_path))
        self.assertEqual(STATUS_CANNOT_SATISFY, result["status"])
        self.assertEqual(6.6, result["output"]["best_attempt"]["estimated_total_seconds"])
        self.assertIn("6.6", result["message"])
        self.assertIn("duration_over", [e["code"] for e in result["output"]["blocking_errors"]])
        # The model retried once before declaring cannot_satisfy.
        drafts = [event for event in events if event["action"] == "draft_script"]
        self.assertEqual(2, len(drafts))

    def test_semantic_review_catches_unsupported_paraphrase(self):
        with tempfile.TemporaryDirectory() as tmp:
            trace_path = Path(tmp) / "trace.jsonl"
            agent, _ = make_agent("semantic_catch", request_p01(), trace_path)
            result = agent.run()
            reviews = [event for event in read_events(trace_path) if event["event"] == "review"]
        self.assertEqual(STATUS_COMPLETED, result["status"])
        self.assertEqual(["fail", "pass"], [event["verdict"] for event in reviews])
        self.assertTrue(any("不用手动打字" in finding["message"] for finding in reviews[0]["findings"]))
        self.assertEqual(
            ["P01-C1"], sorted({claim for shot in result["output"]["shots"] for claim in shot["claim_ids"]})
        )

    def test_step_limit_returns_explicit_incomplete_state(self):
        with tempfile.TemporaryDirectory() as tmp:
            trace_path = Path(tmp) / "trace.jsonl"
            agent, _ = make_agent("step_limit", request_p02(), trace_path, max_steps=2)
            result = agent.run()
        self.assertEqual(STATUS_STEP_LIMIT, result["status"])
        self.assertEqual(2, result["budget"]["steps_used"])
        self.assertIn("最大决策步数 2", result["message"])
        self.assertIsNotNone(result["output"]["partial_script"])
        self.assertIsNotNone(result["output"]["estimated_total_seconds"])

    def test_tool_call_limit_returns_explicit_incomplete_state(self):
        agent, _ = make_agent("normal", request_p02(), max_tool_calls=1)
        result = agent.run()
        self.assertEqual(STATUS_STEP_LIMIT, result["status"])
        self.assertIn("工具调用达到上限 1", result["message"])

    def test_three_consecutive_tool_errors_return_tool_error(self):
        class SearchOnly(Provider):
            name = "test"
            model = "test"

            def generate(self, system, messages, state=None):
                return {
                    "text": json.dumps(
                        {
                            "action": "search_materials",
                            "args": {"query": "x", "product_id": "P01"},
                            "reason": "retry",
                        }
                    ),
                    "usage": {},
                    "model": "test",
                }

        toolbox = ToolBox(
            MATERIALS,
            RULES,
            CONFIG,
            request=request_p01(),
            faults={
                "search_materials": [
                    {"code": "tool_timeout", "message": "t1"},
                    {"code": "tool_timeout", "message": "t2"},
                    {"code": "tool_timeout", "message": "t3"},
                ]
            },
        )
        agent = ScriptAgent(request_p01(), SearchOnly(), None, toolbox, CONFIG)
        result = agent.run()
        self.assertEqual(STATUS_TOOL_ERROR, result["status"])
        self.assertIn("连续工具调用失败", result["message"])

    def test_finish_gate_rejects_completion_before_script_and_review(self):
        class FinishOnly(Provider):
            name = "test"
            model = "test"

            def generate(self, system, messages, state=None):
                return {
                    "text": json.dumps(
                        {
                            "action": "finish",
                            "args": {"status": "completed", "message": "done"},
                            "reason": "too early",
                        }
                    ),
                    "usage": {},
                    "model": "test",
                }

        toolbox = ToolBox(MATERIALS, RULES, CONFIG, request=request_p02())
        agent = ScriptAgent(request_p02(), FinishOnly(), None, toolbox, CONFIG, max_steps=2)
        result = agent.run()
        self.assertEqual(STATUS_STEP_LIMIT, result["status"])
        self.assertEqual(2, result["budget"]["steps_used"])

    def test_json_repair_is_bounded_and_recorded(self):
        class BadThenAsk(Provider):
            name = "test"
            model = "test"

            def __init__(self):
                self.calls = 0

            def generate(self, system, messages, state=None):
                self.calls += 1
                if self.calls == 1:
                    text = "this is not json"
                else:
                    text = json.dumps(
                        {
                            "action": "ask_user",
                            "args": {"question": "请补充平台", "kind": "needs_input"},
                            "reason": "missing platform",
                        },
                        ensure_ascii=False,
                    )
                return {"text": text, "usage": {}, "model": "test"}

        provider = BadThenAsk()
        toolbox = ToolBox(MATERIALS, RULES, CONFIG, request=request_p02())
        agent = ScriptAgent(request_p02(), provider, None, toolbox, CONFIG, max_steps=1)
        result = agent.run()
        self.assertEqual(STATUS_NEEDS_INPUT, result["status"])
        self.assertEqual(1, result["budget"]["json_repairs_used"])
        self.assertEqual(2, result["budget"]["model_calls"])


class ReviewerTests(unittest.TestCase):
    def test_reviewer_fails_unsupported_paraphrase(self):
        reviewer = FactReviewer(MockProvider("normal"))
        result = reviewer.review(request_p01(), P01_SEMANTIC, MATERIALS.all_facts())
        self.assertEqual("fail", result["verdict"])
        self.assertEqual("error", result["findings"][0]["severity"])

    def test_reviewer_passes_grounded_script(self):
        reviewer = FactReviewer(MockProvider("normal"))
        result = reviewer.review(request_p01(), P01_28, MATERIALS.all_facts())
        self.assertEqual("pass", result["verdict"])
        self.assertEqual([], result["findings"])


class TraceTests(unittest.TestCase):
    def test_step_trace_contains_args_reason_and_observation(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "trace.jsonl"
            trace = Trace(path)
            trace.step(
                step=1,
                action="search_materials",
                args={"query": "小影 字幕"},
                reason="先检索",
                ok=True,
                observation={"query": "小影 字幕", "count": 1, "results": [{"id": "P01"}]},
            )
            trace.close()
            event = read_events(path)[0]
        self.assertEqual(1, event["step"])
        self.assertEqual("search_materials", event["action"])
        self.assertEqual({"query": "小影 字幕"}, event["args"])
        self.assertEqual("先检索", event["reason"])
        self.assertEqual(1, event["observation"]["count"])


if __name__ == "__main__":
    unittest.main()
