"""Command-line entry point.

Examples:
    python -m src.cli --provider mock --mock-scenario p01_30s \
        --input examples/p01_30s/input.json \
        --out examples/p01_30s/output.json \
        --trace examples/p01_30s/trace.jsonl

    python -m src.cli --provider deepseek --input examples/p01_30s/input.json
"""

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

from .agent import ScriptAgent
from .data import MaterialIndex, load_brand_rules, load_config, load_materials
from .env import load_env
from .models import EXIT_CODES, STATUS_INVALID_INPUT
from .providers.mock import MockProvider
from .providers.openai_compat import OpenAICompatProvider
from .reviewer import FactReviewer
from .tools import LOCAL_TOOLS, ToolBox
from .trace import Trace
from .validation import validate_request

SCENARIOS = [
    "normal",
    "p01_30s",
    "no_material",
    "tool_failure",
    "impossible",
    "rule_violation",
    "semantic_catch",
    "step_limit",
]

FAULT_PRESETS = {
    "timeout": {
        "code": "tool_timeout",
        "message": "素材检索服务超时（注入故障）",
    },
    "unavailable": {
        "code": "tool_unavailable",
        "message": "素材检索服务暂不可用（注入故障）",
    },
}


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="short-video-script-agent",
        description="生成有事实依据、满足时长限制的可编辑短视频脚本。",
    )
    parser.add_argument("--input", help="请求 JSON 文件；与命令行参数二选一")
    parser.add_argument("--topic", help="视频主题")
    parser.add_argument("--audience", help="目标受众")
    parser.add_argument("--platform", help="投放平台，如 抖音/视频号/B站")
    parser.add_argument("--target-seconds", type=int, help="目标时长（秒，1-600）")
    parser.add_argument("--style", help="风格")
    parser.add_argument("--product-id", help="限定产品素材 ID，如 P01")
    parser.add_argument(
        "--must-include",
        action="append",
        default=[],
        help="必须包含的短语，可重复",
    )
    parser.add_argument(
        "--provider",
        choices=["mock", "deepseek", "openai", "auto"],
        default="mock",
        help="模型 provider；默认 mock 以保证离线可运行",
    )
    parser.add_argument(
        "--mock-scenario",
        choices=SCENARIOS,
        default="normal",
        help="Mock 决策脚本，仅用于离线演示与测试",
    )
    parser.add_argument("--model", help="覆盖 LLM_MODEL")
    parser.add_argument("--base-url", help="覆盖 LLM_BASE_URL")
    parser.add_argument("--api-key", help="覆盖 LLM_API_KEY（不建议写在命令历史里）")
    parser.add_argument("--max-steps", type=int, help="最大决策步数（1-30）")
    parser.add_argument("--max-tool-calls", type=int, help="最大工具调用数")
    parser.add_argument(
        "--fault",
        action="append",
        default=[],
        metavar="TOOL[=KIND]",
        help="注入一次工具故障，如 --fault search_materials=timeout",
    )
    parser.add_argument("--out", help="结果 JSON 输出路径；默认 runs/latest.json")
    parser.add_argument("--trace", help="Trace JSONL 输出路径；默认与结果同目录")
    parser.add_argument("--json", action="store_true", help="只输出完整结果 JSON")
    return parser


def _read_request(args: argparse.Namespace) -> Dict[str, Any]:
    if args.input:
        path = Path(args.input)
        with path.open("r", encoding="utf-8") as handle:
            raw = json.load(handle)
        if not isinstance(raw, dict):
            raise ValueError("输入文件必须是 JSON 对象")
        return raw
    raw: Dict[str, Any] = {}
    if args.topic:
        raw["topic"] = args.topic
    if args.audience:
        raw["audience"] = args.audience
    if args.platform:
        raw["platform"] = args.platform
    if args.target_seconds is not None:
        raw["target_seconds"] = args.target_seconds
    if args.style:
        raw["style"] = args.style
    if args.product_id:
        raw["product_id"] = args.product_id
    if args.must_include:
        raw["must_include"] = args.must_include
    return raw


def _parse_faults(values: List[str]) -> Dict[str, List[Dict[str, str]]]:
    faults: Dict[str, List[Dict[str, str]]] = {}
    for value in values:
        name, _, kind = value.partition("=")
        name = name.strip()
        kind = (kind or "timeout").strip()
        if name not in LOCAL_TOOLS:
            raise ValueError("未知工具 %s；可用：%s" % (name, ", ".join(sorted(LOCAL_TOOLS))))
        if kind not in FAULT_PRESETS:
            raise ValueError("未知故障 %s；可用：%s" % (kind, ", ".join(FAULT_PRESETS)))
        faults.setdefault(name, []).append(dict(FAULT_PRESETS[kind]))
    return faults


def _build_provider(args: argparse.Namespace):
    provider = args.provider
    if provider == "auto":
        provider = "deepseek" if (args.api_key or load_env().get("LLM_API_KEY")) else "mock"
    if provider == "mock":
        return MockProvider(args.mock_scenario)
    env = load_env()
    api_key = args.api_key or env.get("LLM_API_KEY")
    if not api_key:
        raise ValueError("缺少 LLM_API_KEY；请复制 .env.example 为 .env 并填写，或使用 --provider mock")
    base_url = args.base_url or env.get("LLM_BASE_URL") or "https://api.deepseek.com"
    model = args.model or env.get("LLM_MODEL") or "deepseek-chat"
    return OpenAICompatProvider(
        api_key=api_key,
        base_url=base_url,
        model=model,
        timeout=int(env.get("LLM_TIMEOUT", "90")),
        temperature=0.2,
        max_tokens=2000,
    )


def _default_paths(args: argparse.Namespace):
    if args.out:
        out = Path(args.out)
    else:
        out = Path("runs") / "latest.json"
    if args.trace:
        trace = Path(args.trace)
    else:
        trace = out.with_name(out.stem + ".trace.jsonl")
    out.parent.mkdir(parents=True, exist_ok=True)
    trace.parent.mkdir(parents=True, exist_ok=True)
    return out, trace


def _write_invalid_input(
    raw: Dict[str, Any], errors: List[Any], out: Path, trace_path: Path
) -> Dict[str, Any]:
    trace = Trace(trace_path)
    trace.emit(
        "validation_error",
        errors=[error.to_dict() for error in errors],
    )
    trace.close()
    result = {
        "run_id": None,
        "status": STATUS_INVALID_INPUT,
        "message": "输入缺少关键信息或格式不正确，任务未开始。",
        "input": raw,
        "output": {
            "task_status": STATUS_INVALID_INPUT,
            "errors": [error.to_dict() for error in errors],
        },
        "check": None,
        "review": None,
        "budget": None,
        "usage": None,
        "provider": None,
        "trace_path": str(trace_path),
        "timing": None,
    }
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return result


def _print_summary(result: Dict[str, Any], out: Path) -> None:
    output = result.get("output") or {}
    print("status: %s" % result.get("status"))
    print("message: %s" % result.get("message"))
    if output.get("title"):
        print("title: %s" % output["title"])
    if output.get("estimated_total_seconds") is not None:
        print(
            "duration: %s s / target %s s"
            % (output.get("estimated_total_seconds"), output.get("target_seconds"))
        )
    if output.get("shots"):
        print("shots: %d" % len(output["shots"]))
    if result.get("check"):
        print("check_ok: %s" % result["check"].get("ok"))
    if result.get("review"):
        print("review: %s" % result["review"].get("verdict"))
    budget = result.get("budget") or {}
    if budget:
        print(
            "budget: steps %s/%s, tool_calls %s/%s, reviews %s/%s"
            % (
                budget.get("steps_used"),
                budget.get("max_steps"),
                budget.get("tool_calls_used"),
                budget.get("max_tool_calls"),
                budget.get("reviews_used"),
                budget.get("max_reviews"),
            )
        )
    print("result: %s" % out)
    print("trace: %s" % result.get("trace_path"))


def main(argv: Optional[List[str]] = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    out, trace_path = _default_paths(args)

    try:
        raw = _read_request(args)
    except Exception as exc:
        print("读取输入失败：%s" % exc, file=sys.stderr)
        return 5

    request, errors = validate_request(raw)
    if errors:
        result = _write_invalid_input(raw, errors, out, trace_path)
        if args.json:
            print(json.dumps(result, ensure_ascii=False, indent=2))
        else:
            _print_summary(result, out)
        return EXIT_CODES[STATUS_INVALID_INPUT]

    if args.max_steps is not None and not 1 <= args.max_steps <= 30:
        parser.error("--max-steps 必须在 1..30 之间")
    if args.max_tool_calls is not None and args.max_tool_calls < 1:
        parser.error("--max-tool-calls 必须大于 0")

    try:
        faults = _parse_faults(args.fault)
        provider = _build_provider(args)
    except Exception as exc:
        print("初始化失败：%s" % exc, file=sys.stderr)
        return 3

    config = load_config()
    materials = MaterialIndex(load_materials())
    rules = load_brand_rules()
    toolbox = ToolBox(materials, rules, config, request=request, faults=faults)
    reviewer = FactReviewer(provider)
    trace = Trace(trace_path)
    agent = ScriptAgent(
        request,
        provider,
        reviewer,
        toolbox,
        config,
        trace=trace,
        max_steps=args.max_steps,
        max_tool_calls=args.max_tool_calls,
    )
    result = agent.run()
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        _print_summary(result, out)
    return EXIT_CODES.get(result["status"], 3)


if __name__ == "__main__":
    sys.exit(main())
