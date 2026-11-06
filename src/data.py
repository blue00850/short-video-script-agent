"""Loading and querying the synthetic material library."""

import json
from pathlib import Path
from typing import Any, Dict, List, Optional


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = PROJECT_ROOT / "data"


def _read_json(path: Path) -> Dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def load_materials(data_dir: Optional[Path] = None) -> Dict[str, Any]:
    return _read_json(Path(data_dir or DATA_DIR) / "materials.json")


def load_brand_rules(data_dir: Optional[Path] = None) -> Dict[str, Any]:
    return _read_json(Path(data_dir or DATA_DIR) / "brand_rules.json")


def load_config(data_dir: Optional[Path] = None) -> Dict[str, Any]:
    return _read_json(Path(data_dir or DATA_DIR) / "config.json")


class MaterialIndex:
    """Small deterministic keyword index over synthetic materials.

    This is deliberately simple: the exercise tests agent decisions, not search
    quality. The index is transparent and every hit maps to a claim ID.
    """

    def __init__(self, dataset: Dict[str, Any]):
        self.dataset = dataset
        self.items = {item["id"]: item for item in dataset.get("items", [])}

    def search(
        self,
        query: str,
        product_id: Optional[str] = None,
        limit: int = 3,
    ) -> List[Dict[str, Any]]:
        query_lower = (query or "").strip().lower()
        if not query_lower:
            return []
        results = []
        for item_id, item in self.items.items():
            if product_id and item_id != product_id:
                continue
            haystack = " ".join(
                [item.get("name", ""), " ".join(item.get("keywords", []))]
                + [fact.get("text", "") for fact in item.get("facts", [])]
            ).lower()
            matched = []
            for keyword in item.get("keywords", []):
                if keyword.lower() in query_lower:
                    matched.append(keyword)
            # A direct substring hit on the product title also counts.
            if item.get("name", "").lower() in query_lower:
                matched.append(item.get("name", ""))
            # Whole-query fallback keeps short Chinese queries useful.
            if not matched and query_lower in haystack:
                matched.append(query.strip())
            if matched:
                results.append(
                    {
                        "id": item_id,
                        "name": item.get("name", ""),
                        "matched_keywords": matched,
                        "claim_ids": [
                            fact.get("claim_id") for fact in item.get("facts", [])
                        ],
                        "fact_count": len(item.get("facts", [])),
                    }
                )
        results.sort(key=lambda row: row["id"])
        return results[: max(1, limit)]

    def get(self, item_id: str) -> Optional[Dict[str, Any]]:
        return self.items.get(item_id)

    def all_facts(self) -> List[Dict[str, Any]]:
        facts = []
        for item_id, item in self.items.items():
            for fact in item.get("facts", []):
                facts.append(
                    {
                        "material_id": item_id,
                        "material_name": item.get("name", ""),
                        "claim_id": fact.get("claim_id"),
                        "text": fact.get("text"),
                        "source": fact.get("source"),
                        "usage_constraints": item.get("usage_constraints", []),
                    }
                )
        return facts
