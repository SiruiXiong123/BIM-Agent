"""Quality rules shared by index cleanup and online retrieval."""

from __future__ import annotations

from typing import Any, Mapping

from src.search.models import SearchHit


LOW_QUALITY_IMAGE_PHRASES = (
    "无法识别",
    "未识别图像",
    "模糊不清",
    "图像模糊",
    "无可用信息",
    "无任何可读",
    "无法提取任何有效信息",
    "unreadable",
    "placeholder",
    "indistinct",
    "indiscernible",
    "does not convey any measurable information",
)


def is_low_quality_image_record(record: Mapping[str, Any]) -> bool:
    if record.get("modality") != "image":
        return False
    searchable = "\n".join(
        str(record.get(field) or "")
        for field in ("title", "metadata", "content", "summary")
    ).casefold()
    return not str(record.get("summary") or "").strip() or any(
        phrase.casefold() in searchable for phrase in LOW_QUALITY_IMAGE_PHRASES
    )


def is_low_quality_hit(hit: SearchHit) -> bool:
    return is_low_quality_image_record(hit.model_dump(mode="python"))
