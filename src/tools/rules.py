"""Brand-rule, grounding and duration checks.

The checker is the last line of defence against fabricated product facts. It
does not try to understand language; it enforces traceable mappings:

    narration capability -> cited claim ID -> claim text

A semantic reviewer (a second model role) catches paraphrases that the
mechanical checker cannot.
"""

import re
from typing import Any, Dict, List, Optional, Tuple

from .duration import estimate_script


NUMBER_RE = re.compile(r"(?<![A-Za-z0-9])(\d+(?:\.\d+)?)(%?)")
TIMING_UNITS = ("秒", "分钟", "帧", "个", "条", "字", "年", "月", "日", "岁", "次", "位", "种", "款", "倍", "分", "小时")


def _normalize(text: str) -> str:
    return re.sub(r"\s+", "", (text or "").lower())


def _error(code: str, message: str, field: str = "", shot: Optional[int] = None) -> Dict[str, Any]:
    item: Dict[str, Any] = {"code": code, "message": message}
    if field:
        item["field"] = field
    if shot is not None:
        item["shot"] = shot
    return item


def _build_claim_lookup(rules: Dict[str, Any], dataset: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    lookup: Dict[str, Dict[str, Any]] = {}
    for item in dataset.get("items", []):
        for fact in item.get("facts", []):
            lookup[fact["claim_id"]] = {
                "material_id": item["id"],
                "material_name": item.get("name", ""),
                "text": fact.get("text", ""),
                "source": fact.get("source", ""),
                "usage_constraints": item.get("usage_constraints", []),
            }
    return lookup


def _number_is_exempt(text: str, match: re.Match) -> bool:
    start, end = match.start(), match.end()
    before = text[start - 1] if start > 0 else ""
    after = text[end : end + 1]
    after_two = text[end : end + 2]
    # Ratios such as 9:16 and version-like tokens are not spoken claims.
    if before == ":" or after == ":":
        return True
    # Dimensions / model numbers attached to Latin letters (1080P) are
    # handled by the capability lexicon instead.
    if after.isalpha():
        return True
    # Timing and structural quantities are not product facts.
    stripped = after_two.lstrip()
    for unit in TIMING_UNITS:
        if stripped.startswith(unit):
            return True
    return False


def check_script(
    script: Dict[str, Any],
    request: Dict[str, Any],
    rules: Dict[str, Any],
    dataset: Dict[str, Any],
    estimate: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    global_rules = rules.get("global", {})
    platforms = rules.get("platforms", {})
    claim_lookup = _build_claim_lookup(rules, dataset)

    if estimate is None:
        estimate = estimate_script(script, {})
    total = float(estimate.get("total_seconds", 0.0))
    target = int(request.get("target_seconds", 0))
    platform = request.get("platform", "")

    errors: List[Dict[str, Any]] = []
    warnings: List[Dict[str, Any]] = []
    checks: Dict[str, Any] = {}

    # 1. Structure.
    shots = script.get("shots", []) if isinstance(script, dict) else []
    min_shots = int(global_rules.get("min_shots", 3))
    max_shots = int(global_rules.get("max_shots", 8))
    structure_ok = True
    if not isinstance(script.get("title"), str) or not script.get("title", "").strip():
        errors.append(_error("missing_title", "脚本缺少标题", "title"))
        structure_ok = False
    if len(shots) < min_shots:
        errors.append(
            _error("min_shots", "镜头数 %d 少于品牌规则要求的 %d" % (len(shots), min_shots))
        )
        structure_ok = False
    if len(shots) > max_shots:
        errors.append(
            _error("max_shots", "镜头数 %d 多于品牌规则要求的 %d" % (len(shots), max_shots))
        )
        structure_ok = False

    # 2. Claim traceability + capability grounding, per shot.
    all_cited_text = ""
    cited_claims: List[str] = []
    unknown_sources: List[str] = []
    for index, shot in enumerate(shots, start=1):
        if not isinstance(shot, dict):
            errors.append(_error("invalid_shot", "镜头必须是对象", shot=index))
            continue
        source_ids = shot.get("source_ids", []) or []
        claim_ids = shot.get("claim_ids", []) or []
        if not source_ids:
            errors.append(_error("missing_source", "镜头 %d 没有 source_ids" % index, shot=index))
            structure_ok = False
        if not claim_ids:
            errors.append(_error("missing_claim", "镜头 %d 没有 claim_ids" % index, shot=index))
            structure_ok = False

        shot_cited_text = ""
        for claim_id in claim_ids:
            claim = claim_lookup.get(claim_id)
            if not claim:
                errors.append(
                    _error(
                        "unknown_claim",
                        "镜头 %d 引用了不存在的 claim_id：%s" % (index, claim_id),
                        shot=index,
                    )
                )
                continue
            cited_claims.append(claim_id)
            shot_cited_text += claim["text"] + "\n"
            if claim["material_id"] not in source_ids:
                errors.append(
                    _error(
                        "source_claim_mismatch",
                        "镜头 %d 的 claim %s 属于素材 %s，但 source_ids 中没有它"
                        % (index, claim_id, claim["material_id"]),
                        shot=index,
                    )
                )
        for source_id in source_ids:
            if not any(
                claim["material_id"] == source_id for claim in claim_lookup.values()
            ):
                if source_id not in unknown_sources:
                    unknown_sources.append(source_id)
                errors.append(
                    _error(
                        "unknown_material",
                        "镜头 %d 引用了不存在的素材 ID：%s" % (index, source_id),
                        shot=index,
                    )
                )
        all_cited_text += shot_cited_text

        narration = shot.get("narration", "")
        for token in global_rules.get("capability_lexicon", []):
            if _normalize(token) in _normalize(narration) and _normalize(token) not in _normalize(shot_cited_text):
                errors.append(
                    _error(
                        "ungrounded_capability",
                        "镜头 %d 提到“%s”，但所引 claim 中没有依据" % (index, token),
                        shot=index,
                    )
                )

    checks["claims"] = {
        "ok": not any(error["code"] in {"unknown_claim", "unknown_material", "source_claim_mismatch"} for error in errors),
        "cited_claim_ids": sorted(set(cited_claims)),
        "unknown_sources": unknown_sources,
    }

    # 2b. The title is part of the deliverable too: it must not smuggle in a
    # capability or a number that no cited claim supports.
    title = script.get("title", "") or ""
    ungrounded_title: List[str] = []
    for token in global_rules.get("capability_lexicon", []):
        if _normalize(token) in _normalize(title) and _normalize(token) not in _normalize(all_cited_text):
            ungrounded_title.append(token)
            errors.append(
                _error(
                    "ungrounded_capability",
                    "标题提到“%s”，但脚本所引 claim 中没有依据" % token,
                    "title",
                )
            )
    for match in NUMBER_RE.finditer(title):
        if _number_is_exempt(title, match):
            continue
        raw = match.group(0)
        if raw not in all_cited_text and match.group(1) not in all_cited_text:
            ungrounded_title.append(raw)
            errors.append(
                _error(
                    "ungrounded_number",
                    "标题的数字“%s”在所引 claim 中找不到依据" % raw,
                    "title",
                )
            )
    checks["title"] = {"ok": not ungrounded_title, "ungrounded": ungrounded_title}

    # 3. Required phrases from the brief.
    full_text = (script.get("title", "") or "") + "\n" + "\n".join(
        (shot.get("narration", "") + " " + shot.get("visual", ""))
        for shot in shots
        if isinstance(shot, dict)
    )
    missing_required = []
    for phrase in request.get("must_include", []) or []:
        if phrase and _normalize(phrase) not in _normalize(full_text):
            missing_required.append(phrase)
    if missing_required:
        errors.append(
            _error(
                "missing_required_phrase",
                "缺少用户要求必须出现的内容：%s" % "、".join(missing_required),
                "must_include",
            )
        )

    # 4. Forbidden phrases and patterns.
    forbidden_hits: List[Dict[str, str]] = []
    for phrase in global_rules.get("forbidden_phrases", []):
        if _normalize(phrase) in _normalize(full_text):
            forbidden_hits.append({"type": "phrase", "value": phrase})
    for pattern in global_rules.get("forbidden_patterns", []):
        match = re.search(pattern, full_text)
        if match:
            forbidden_hits.append({"type": "pattern", "value": match.group(0)})
    seen_hits = set()
    unique_hits: List[Dict[str, str]] = []
    for hit in forbidden_hits:
        key = _normalize(hit["value"])
        if key in seen_hits:
            continue
        seen_hits.add(key)
        unique_hits.append(hit)
    for hit in unique_hits:
        errors.append(
            _error("forbidden_phrase", "命中品牌禁用表达：%s" % hit["value"], "text")
        )
    checks["forbidden"] = {"ok": not unique_hits, "hits": unique_hits}

    # 5. Numbers must be traceable, except timing/structure quantities.
    ungrounded_numbers: List[Dict[str, Any]] = []
    for index, shot in enumerate(shots, start=1):
        if not isinstance(shot, dict):
            continue
        narration = shot.get("narration", "")
        shot_text = ""
        for claim_id in shot.get("claim_ids", []) or []:
            claim = claim_lookup.get(claim_id)
            if claim:
                shot_text += claim["text"] + "\n"
        for match in NUMBER_RE.finditer(narration):
            if _number_is_exempt(narration, match):
                continue
            raw = match.group(0)
            if raw not in shot_text and match.group(1) not in shot_text:
                ungrounded_numbers.append({"shot": index, "value": raw})
                errors.append(
                    _error(
                        "ungrounded_number",
                        "镜头 %d 的数字“%s”在所引 claim 中找不到依据" % (index, raw),
                        shot=index,
                    )
                )
    checks["numbers"] = {"ok": not ungrounded_numbers, "ungrounded": ungrounded_numbers}

    # 6. Duration vs target and platform limits.
    tolerance_ratio = float(global_rules.get("duration_tolerance_low_ratio", 0.8))
    low_bound = round(target * tolerance_ratio, 2)
    duration_ok = True
    if target and total > target + 0.05:
        duration_ok = False
        errors.append(
            _error(
                "duration_over",
                "预计 %.1f 秒，超过目标 %d 秒" % (total, target),
                "target_seconds",
            )
        )
    if target and total < low_bound - 0.05:
        duration_ok = False
        errors.append(
            _error(
                "duration_under",
                "预计 %.1f 秒，低于目标 %d 秒可接受下限 %.1f 秒"
                % (total, target, low_bound),
                "target_seconds",
            )
        )

    platform_rule = platforms.get(platform, {})
    platform_ok = True
    if platform_rule:
        if total < float(platform_rule.get("min_seconds", 0)):
            platform_ok = False
            errors.append(
                _error(
                    "platform_duration",
                    "%s 要求至少 %s 秒，当前 %.1f 秒"
                    % (platform, platform_rule.get("min_seconds"), total),
                    "platform",
                )
            )
        if total > float(platform_rule.get("max_seconds", 10 ** 9)):
            platform_ok = False
            errors.append(
                _error(
                    "platform_duration",
                    "%s 要求不超过 %s 秒，当前 %.1f 秒"
                    % (platform, platform_rule.get("max_seconds"), total),
                    "platform",
                )
            )
    checks["duration"] = {
        "ok": duration_ok,
        "total_seconds": total,
        "target_seconds": target,
        "accepted_low_seconds": low_bound,
        "delta_seconds": round(total - target, 1) if target else None,
        "estimate": estimate,
    }
    checks["platform"] = {"ok": platform_ok, "platform": platform, "rule": platform_rule}
    checks["structure"] = {"ok": structure_ok, "shot_count": len(shots)}

    return {
        "ok": not errors,
        "errors": errors,
        "warnings": warnings,
        "checks": checks,
        "estimate": estimate,
        "claim_lookup": claim_lookup,
    }
