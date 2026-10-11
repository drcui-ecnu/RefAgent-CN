from __future__ import annotations

from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Any, Dict, List


@dataclass
class JournalMatch:
    name_en: str = ""
    source: str = ""
    match_type: str = "none"
    confidence: float = 0.0
    metadata: Dict[str, Any] = None


class JournalKB:
    def __init__(self, records: List[Dict]) -> None:
        self.records = records or []
        self.index = {str(r.get("name_cn", "")).strip(): r for r in self.records if r.get("name_cn")}

    def resolve(self, journal_cn: str) -> JournalMatch:
        journal_cn = (journal_cn or "").strip()
        if not journal_cn:
            return JournalMatch()

        if journal_cn in self.index:
            r = self.index[journal_cn]
            return JournalMatch(
                name_en=str(r.get("name_en", "")).strip(),
                source=str(r.get("source", "journal_kb")).strip(),
                match_type="exact",
                confidence=float(r.get("confidence", 1.0) or 1.0),
                metadata=dict(r.get("metadata", {}) or {}),
            )

        # Conservative fuzzy fallback.
        best = None
        best_score = 0.0
        for r in self.records:
            name = str(r.get("name_cn", "")).strip()
            if not name:
                continue
            score = SequenceMatcher(None, journal_cn, name).ratio()
            if score > best_score:
                best_score = score
                best = r

        if best and best_score >= 0.92:
            return JournalMatch(
                name_en=str(best.get("name_en", "")).strip(),
                source=str(best.get("source", "journal_kb")).strip(),
                match_type="fuzzy",
                confidence=round(best_score, 3),
                metadata=dict(best.get("metadata", {}) or {}),
            )

        return JournalMatch()

@dataclass
class EntityMatch:
    name_en: str = ""
    source: str = ""
    match_type: str = "none"
    confidence: float = 0.0


class EntityKB:
    """Generic Chinese-English entity name resolver for institutions and publishers."""

    def __init__(self, records: List[Dict], entity_type: str = "entity") -> None:
        self.records = records or []
        self.entity_type = entity_type
        self.index = {str(r.get("name_cn", "")).strip(): r for r in self.records if r.get("name_cn")}

    def resolve(self, name_cn: str) -> EntityMatch:
        name_cn = (name_cn or "").strip()
        if not name_cn:
            return EntityMatch()

        if name_cn in self.index:
            r = self.index[name_cn]
            return EntityMatch(
                name_en=str(r.get("name_en", "")).strip(),
                source=str(r.get("source", f"{self.entity_type}_kb")).strip(),
                match_type="exact",
                confidence=float(r.get("confidence", 1.0) or 1.0),
            )

        # Alias exact match.
        for r in self.records:
            aliases = r.get("alias_cn") or []
            if isinstance(aliases, str):
                aliases = [aliases]
            if name_cn in [str(x).strip() for x in aliases if str(x).strip()]:
                return EntityMatch(
                    name_en=str(r.get("name_en", "")).strip(),
                    source=str(r.get("source", f"{self.entity_type}_kb")).strip(),
                    match_type="alias",
                    confidence=float(r.get("confidence", 0.98) or 0.98),
                )

        # Conservative fuzzy fallback.
        best = None
        best_score = 0.0
        for r in self.records:
            name = str(r.get("name_cn", "")).strip()
            if not name:
                continue
            score = SequenceMatcher(None, name_cn, name).ratio()
            if score > best_score:
                best_score = score
                best = r

        if best and best_score >= 0.92:
            return EntityMatch(
                name_en=str(best.get("name_en", "")).strip(),
                source=str(best.get("source", f"{self.entity_type}_kb")).strip(),
                match_type="fuzzy",
                confidence=round(best_score, 3),
            )

        return EntityMatch()
