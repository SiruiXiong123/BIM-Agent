"""Deterministic tokenizer for mixed Chinese regulation text."""

from __future__ import annotations

import re
import unicodedata

import jieba

TOKENIZER_NAME = "zh-mixed:v1"
_NUMBER_RE = re.compile(r"\d{1,3}(?:,\d{3})+(?:\.\d+)?%?|\d+(?:\.\d+)?%?")
_ENGLISH_RE = re.compile(r"[A-Za-z][A-Za-z0-9_-]*")
_CHINESE_RE = re.compile(r"[\u4e00-\u9fff]+")


def normalize_text(text: object) -> str:
    normalized = unicodedata.normalize("NFKC", str(text or ""))
    normalized = normalized.replace("，", ",").replace("。", ".").replace("％", "%")
    normalized = re.sub(r"(?<=\d)\s+(?=[,.\d])", "", normalized)
    normalized = re.sub(r"(?<=[,.])\s+(?=\d)", "", normalized)
    return normalized


def tokenize_zh_mixed(text: object) -> list[str]:
    """Return ordered, deduplicated word and character-bigram tokens."""

    normalized = normalize_text(text)
    tokens = [match.group(0) for match in _NUMBER_RE.finditer(normalized)]
    tokens.extend(match.group(0).lower() for match in _ENGLISH_RE.finditer(normalized))

    for span in _CHINESE_RE.findall(normalized):
        words = [token.strip() for token in jieba.cut_for_search(span) if len(token.strip()) >= 2]
        tokens.extend(words)
        tokens.extend(span[index : index + 2] for index in range(len(span) - 1))

    return list(dict.fromkeys(token for token in tokens if token))
