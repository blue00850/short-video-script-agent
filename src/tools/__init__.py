"""Local tool implementations and a fault-injectable dispatcher."""

from typing import Any, Dict, List, Optional

from ..data import MaterialIndex
from .duration import estimate_script
from .rules import check_script


LOCAL_TOOLS = {"search_materials", "get_material", "estimate_duration", "check_rules"}


class ToolBox:
    def __init__(
        self,
        materials: MaterialIndex,
        brand_rules: Dict[str, Any],
        config: Dict[str, Any],
        request: Optional[Dict[str, Any]] = None,
        faults: Optional[Dict[str, List[Dict[str, str]]]] = None,
    ):
        self.index = materials
        self.dataset = materials.dataset
        self.rules = brand_rules
        self.config = config
        self.request = request or {}
        self.faults = {
            name: list(items) for name, items in (faults or {}).items() if items
        }
        self.call_count = 0

    def _take_fault(self, name: str) -> Optional[Dict[str, str]]:
        queue = self.faults.get(name)
        if queue:
            return queue.pop(0)
        return None

    def call(self, name: str, args: Any) -> Dict[str, Any]:
        self.call_count += 1
        if name not in LOCAL_TOOLS:
            return {
                "ok": False,
                "error": {
                    "code": "unknown_tool",
                    "message": "工具 %s 不存在；可用工具：%s"
                    % (name, ", ".join(sorted(LOCAL_TOOLS))),
                },
            }
        fault = self._take_fault(name)
        if fault:
            return {"ok": False, "error": fault}
        if not isinstance(args, dict):
            return {
                "ok": False,
                "error": {"code": "invalid_arguments", "message": "args 必须是对象"},
            }
        try:
            if name == "search_materials":
                return self._search(args)
            if name == "get_material":
                return self._get(args)
            if name == "estimate_duration":
                return self._estimate(args)
            if name == "check_rules":
                return self._check(args)
        except Exception as exc:  # Defensive: a tool must never crash the run.
            return {
                "ok": False,
                "error": {
                    "code": "internal_error",
                    "message": "%s: %s" % (type(exc).__name__, exc),
                },
            }
        return {
            "ok": False,
            "error": {"code": "unknown_tool", "message": "未实现的工具"},
        }

    def _search(self, args: Dict[str, Any]) -> Dict[str, Any]:
        query = args.get("query")
        if not isinstance(query, str) or not query.strip():
            return {
                "ok": False,
                "error": {"code": "invalid_arguments", "message": "query 不能为空"},
            }
        product_id = args.get("product_id")
        if product_id is not None and not isinstance(product_id, str):
            product_id = None
        limit = args.get("limit", 3)
        if isinstance(limit, bool) or not isinstance(limit, int):
            limit = 3
        limit = max(1, min(limit, 10))
        results = self.index.search(query.strip(), product_id=product_id, limit=limit)
        data: Dict[str, Any] = {
            "query": query.strip(),
            "product_id": product_id,
            "count": len(results),
            "results": results,
        }
        if not results:
            data["hint"] = "没有匹配素材；可以改写查询或去掉 product_id 重试一次，仍无结果则 ask_user。"
        return {"ok": True, "data": data}

    def _get(self, args: Dict[str, Any]) -> Dict[str, Any]:
        material_id = args.get("id") or args.get("material_id")
        if not isinstance(material_id, str) or not material_id.strip():
            return {
                "ok": False,
                "error": {"code": "invalid_arguments", "message": "id 不能为空"},
            }
        item = self.index.get(material_id.strip())
        if not item:
            return {
                "ok": False,
                "error": {
                    "code": "material_not_found",
                    "message": "素材 %s 不存在" % material_id,
                },
            }
        return {"ok": True, "data": item}

    def _estimate(self, args: Dict[str, Any]) -> Dict[str, Any]:
        script = args.get("script")
        if not isinstance(script, dict) or not isinstance(script.get("shots"), list):
            return {
                "ok": False,
                "error": {
                    "code": "invalid_arguments",
                    "message": "script.shots 必须是数组",
                },
            }
        estimate = estimate_script(script, self.config.get("duration", {}))
        return {"ok": True, "data": estimate}

    def _check(self, args: Dict[str, Any]) -> Dict[str, Any]:
        script = args.get("script")
        if not isinstance(script, dict) or not isinstance(script.get("shots"), list):
            return {
                "ok": False,
                "error": {
                    "code": "invalid_arguments",
                    "message": "script.shots 必须是数组",
                },
            }
        estimate = estimate_script(script, self.config.get("duration", {}))
        request = self.request
        if isinstance(args.get("request"), dict):
            request = args["request"]
        result = check_script(
            script,
            request,
            self.rules,
            self.dataset,
            estimate=estimate,
        )
        # The claim lookup is an internal index, not a useful observation.
        result.pop("claim_lookup", None)
        return {"ok": True, "data": result}
