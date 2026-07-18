"""Generic parsing and matching for explicit regulation references."""

from __future__ import annotations

from dataclasses import dataclass
import re
import unicodedata


@dataclass(frozen=True, slots=True)
class RegulationReferenceLocator:
    """One explicit article, table, figure, chapter, or appendix locator."""

    raw: str
    normalized: str
    core: str
    prefers_visual: bool = False


_REFERENCE_PATTERNS = (
    r"(?:表|table)\s*[a-z]?\d+(?:\s*[.．。-]\s*\d+)+",
    r"(?:第\s*)?\d+(?:\s*[.．。-]\s*\d+)+(?:\s*条)",
    r"(?:第\s*)?\d+\s*章",
    r"(?:图|figure|fig\.?)\s*[a-z]?\d+(?:\s*[.．。-]\s*\d+)*",
    r"(?:附录|附件|appendix)\s*[a-z一二三四五六七八九十0-9]+",
)


def extract_reference_locators(value: str) -> list[RegulationReferenceLocator]:
    """Extract explicit locators without knowing any project-specific number."""

    normalized_value = unicodedata.normalize("NFKC", str(value or "")).casefold()
    found: list[RegulationReferenceLocator] = []
    seen: set[str] = set()
    for pattern in _REFERENCE_PATTERNS:
        for match in re.finditer(pattern, normalized_value, flags=re.IGNORECASE):
            raw = match.group(0)
            normalized = normalize_reference_text(raw)
            if normalized in seen:
                continue
            seen.add(normalized)
            core = re.sub(
                r"^(?:表|table|图|figure|fig\.?|附录|附件|appendix|第)",
                "",
                normalized,
            )
            core = re.sub(r"(?:条|章)$", "", core)
            found.append(
                RegulationReferenceLocator(
                    raw=raw,
                    normalized=normalized,
                    core=core or normalized,
                    prefers_visual=bool(
                        re.match(
                            r"^(?:表|table|图|figure|fig\.?)", normalized
                        )
                    ),
                )
            )
    return found


def normalize_reference_text(value: str) -> str:
    """Normalize punctuation and whitespace for stable locator matching."""

    normalized = unicodedata.normalize("NFKC", str(value or "")).casefold()
    return re.sub(r"\s+", "", normalized).replace("．", ".").replace("。", ".")


def reference_match_priority(
    locator: RegulationReferenceLocator,
    value: str,
    *,
    modality: str,
) -> int | None:
    """Return a lower-is-better exact-reference match priority."""

    haystack = normalize_reference_text(value)
    exact = locator.normalized in haystack
    core = bool(locator.core) and locator.core in haystack
    if not exact and not core:
        return None
    visual_bonus = locator.prefers_visual and modality in {"table", "image"}
    if exact and visual_bonus:
        return 0
    if exact:
        return 1
    if visual_bonus:
        return 2
    return 3
