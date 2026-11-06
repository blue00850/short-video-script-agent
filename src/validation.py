"""Input validation and JSON extraction helpers.

All validation failures are reported as data, never as stack traces, so the
CLI can return a stable machine-readable status.
"""

import json
import re
from typing import Any, Dict, List, Optional, Tuple

from .models import InputError


PLATFORM_ALIASES = {
    "douyin": "抖音",
    "tiktok": "抖音",
    "抖音短视频": "抖音",
    "kuaishou": "快手",
    "bilibili": "B站",
    "b站": "B站",
    "xiaohongshu": "小红书",
    "视频号": "视频号",
}

SUPPORTED_PLATFORMS = ["抖音", "快手", "视频号", "B站", "小红书"]


def _as_str(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


def _as_str_list(value: Any) -> List[str]:
    if not isinstance(value, list):
        return []
    result = []
    for item in value:
        if isinstance(item, str) and item.strip():
            result.append(item.strip())
    return result


def validate_request(raw: Any) -> Tuple[Optional[Dict[str, Any]], List[InputError]]:
    """Normalize a user request. Missing critical fields make it invalid."""
    errors: List[InputError] = []
    if not isinstance(raw, dict):
        return None, [InputError("$", "输入必须是 JSON 对象")]

    topic = _as_str(raw.get("topic"))
    if not topic:
        errors.append(InputError("topic", "缺少主题（topic）"))
    elif len(topic) > 200:
        errors.append(InputError("topic", "主题过长，最多 200 字"))

    platform_raw = _as_str(raw.get("platform"))
    platform = PLATFORM_ALIASES.get(platform_raw.lower(), platform_raw)
    if not platform:
        errors.append(InputError("platform", "缺少投放平台（platform）"))
    elif platform not in SUPPORTED_PLATFORMS:
        errors.append(
            InputError(
                "platform",
                "不支持的平台：%s；可选：%s"
                % (platform, "、".join(SUPPORTED_PLATFORMS)),
            )
        )

    target = raw.get("target_seconds")
    if isinstance(target, bool) or not isinstance(target, int):
        errors.append(InputError("target_seconds", "目标时长必须是整数秒"))
        target = None
    elif target < 1 or target > 600:
        errors.append(InputError("target_seconds", "目标时长需在 1–600 秒之间"))

    audience = _as_str(raw.get("audience")) or "泛短视频创作者"
    style = _as_str(raw.get("style")) or "自然、口语化"
    product_id = _as_str(raw.get("product_id")) or None
    materials_query = _as_str(raw.get("materials_query")) or topic

    brand_keywords = _as_str_list(raw.get("brand_keywords"))
    must_include = _as_str_list(raw.get("must_include"))

    if errors:
        return None, errors

    normalized = {
        "topic": topic,
        "audience": audience,
        "platform": platform,
        "target_seconds": target,
        "style": style,
        "product_id": product_id,
        "materials_query": materials_query,
        "brand_keywords": brand_keywords,
        "must_include": must_include,
    }
    return normalized, []


def parse_script_args(args: Any) -> Tuple[Optional[Dict[str, Any]], List[str]]:
    """Validate a draft_script payload before it enters the tool layer."""
    problems: List[str] = []
    if not isinstance(args, dict):
        return None, ["draft_script.args 必须是对象"]

    title = args.get("title")
    if not isinstance(title, str) or not title.strip():
        problems.append("title 不能为空")
        title = ""

    shots_raw = args.get("shots")
    if not isinstance(shots_raw, list) or not shots_raw:
        problems.append("shots 必须是非空数组")
        shots_raw = []

    if len(shots_raw) > 20:
        problems.append("shots 最多 20 个（规则检查会进一步限制为 8 个）")

    shots = []
    for index, item in enumerate(shots_raw, start=1):
        if not isinstance(item, dict):
            problems.append("第 %d 个镜头必须是对象" % index)
            continue
        visual = item.get("visual")
        narration = item.get("narration")
        if not isinstance(visual, str) or not visual.strip():
            problems.append("第 %d 个镜头缺少 visual" % index)
            visual = ""
        if not isinstance(narration, str) or not narration.strip():
            problems.append("第 %d 个镜头缺少 narration" % index)
            narration = ""
        source_ids = _as_str_list(item.get("source_ids"))
        claim_ids = _as_str_list(item.get("claim_ids"))
        if not source_ids:
            problems.append("第 %d 个镜头缺少 source_ids" % index)
        if not claim_ids:
            problems.append("第 %d 个镜头缺少 claim_ids" % index)
        shots.append(
            {
                "visual": visual.strip(),
                "narration": narration.strip(),
                "source_ids": source_ids,
                "claim_ids": claim_ids,
            }
        )

    if problems:
        return None, problems
    return {"title": title.strip(), "shots": shots}, []


def extract_json(text: str) -> Optional[Dict[str, Any]]:
    """Extract one JSON object from model text, tolerating code fences.

    Only objects are accepted because every model decision is an object.
    """
    if not isinstance(text, str):
        return None
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```[a-zA-Z0-9_-]*\s*", "", cleaned)
        cleaned = re.sub(r"\s*```$", "", cleaned)
    candidates = [cleaned]
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start != -1 and end > start:
        candidates.append(cleaned[start : end + 1])
    for candidate in candidates:
        try:
            value = json.loads(candidate)
        except (ValueError, TypeError):
            continue
        if isinstance(value, dict):
            return value
    return None


def validate_decision(obj: Any) -> Tuple[Optional[Dict[str, Any]], List[str]]:
    from .models import ALLOWED_ACTIONS

    if not isinstance(obj, dict):
        return None, ["响应必须是 JSON 对象"]
    action = obj.get("action")
    if action not in ALLOWED_ACTIONS:
        return None, [
            "action 必须是以下之一：%s" % ", ".join(sorted(ALLOWED_ACTIONS))
        ]
    args = obj.get("args")
    if args is None:
        args = {}
    if not isinstance(args, dict):
        return None, ["args 必须是对象"]
    reason = obj.get("reason", "")
    if reason is None:
        reason = ""
    if not isinstance(reason, str):
        return None, ["reason 必须是字符串"]
    return {"action": action, "args": args, "reason": reason.strip()}, []
