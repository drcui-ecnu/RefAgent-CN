from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, asdict
from typing import Any, Dict, List, Optional, Tuple

from .journal_kb import JournalKB
from .parser import ReferenceParser


def norm_key(value: Any) -> str:
    text = unicodedata.normalize("NFKC", str(value or "")).strip().casefold()
    return re.sub(r"[^\w\u4e00-\u9fff]+", "", text)


@dataclass
class FieldValue:
    value: Any
    source: str
    is_official: bool
    is_generated: bool
    need_review: bool
    evidence_id: str = ""
    kb_record_id: str = ""

    def dict(self) -> Dict[str, Any]:
        return asdict(self)


class ExactVerifiedTitleKB:
    """Exact verified resolution only; never performs semantic retrieval."""

    def __init__(self, records: List[Dict[str, Any]]) -> None:
        self.records = records or []
        self.index: Dict[Tuple[str, str, str], Dict[str, Any]] = {}
        for row in self.records:
            if str(row.get("verification_status") or "").lower() != "verified":
                continue
            if not bool(row.get("is_official")):
                continue
            title = row.get("title_cn_clean") or row.get("title_cn")
            k = (norm_key(title), norm_key(row.get("journal_cn")), str(row.get("year") or "").strip())
            if all(k):
                self.index.setdefault(k, row)

    def resolve(self, title_cn: str, journal_cn: str, year: Any) -> Optional[Dict[str, Any]]:
        return self.index.get((norm_key(title_cn), norm_key(journal_cn), str(year or "").strip()))


class SourceAwareHybridV390:
    """Deterministic post-processor for one shared LLM response."""

    VERSION = "3.9.0"

    def __init__(self, journal_records: List[Dict[str, Any]], title_records: List[Dict[str, Any]]) -> None:
        self.parser = ReferenceParser()
        self.journal_kb = JournalKB(journal_records)
        self.title_kb = ExactVerifiedTitleKB(title_records)

    @staticmethod
    def _llm_field(value: Any) -> FieldValue:
        return FieldValue(value, "llm_generated", False, True, True)

    @staticmethod
    def _parsed_field(value: Any, record_id: str) -> FieldValue:
        return FieldValue(value, "parsed_reference", False, False, False, evidence_id=f"parser:{record_id}")

    def derive(self, record_id: str, chinese_reference: str, shared: Dict[str, Any]) -> Dict[str, Any]:
        parsed = self.parser.parse(chinese_reference, ref_id=str(record_id))
        parsed_dict = parsed.to_dict() if hasattr(parsed, "to_dict") else dict(parsed)

        llm_only = {
            "authors": self._llm_field(shared.get("english_authors") or []).dict(),
            "title": self._llm_field(shared.get("english_title") or "").dict(),
            "journal": self._llm_field(shared.get("english_journal") or "").dict(),
            "year": self._llm_field(shared.get("year") or "").dict(),
            "volume": self._llm_field(shared.get("volume") or "").dict(),
            "issue": self._llm_field(shared.get("issue") or "").dict(),
            "pages": self._llm_field(shared.get("pages") or "").dict(),
        }

        title_cn = parsed_dict.get("title_cn") or ""
        journal_cn = parsed_dict.get("journal_cn") or ""
        year = parsed_dict.get("year") or ""

        journal_match = self.journal_kb.resolve(journal_cn)
        if journal_match.name_en and journal_match.match_type in {"exact", "alias"}:
            journal = FieldValue(journal_match.name_en, "journal_kb_verified", True, False, False,
                                 evidence_id=f"journal:{journal_cn}")
        else:
            journal = self._llm_field(shared.get("english_journal") or "")

        title_match = self.title_kb.resolve(title_cn, journal_cn, year)
        if title_match:
            title = FieldValue(title_match.get("title_en_clean") or title_match.get("title_en") or "",
                               "title_kb_verified_exact", True, False, False,
                               evidence_id=f"title:{title_match.get('record_id','')}",
                               kb_record_id=str(title_match.get("record_id") or ""))
        else:
            title = self._llm_field(shared.get("english_title") or "")

        full = {
            "authors": self._llm_field(shared.get("english_authors") or []).dict(),
            "title": title.dict(),
            "journal": journal.dict(),
            "year": self._parsed_field(year, record_id).dict(),
            "volume": self._parsed_field(parsed_dict.get("volume") or "", record_id).dict(),
            "issue": self._parsed_field(parsed_dict.get("issue") or "", record_id).dict(),
            "pages": self._parsed_field(parsed_dict.get("pages") or "", record_id).dict(),
        }
        review_required = any(x["need_review"] for x in full.values())
        return {
            "Record_ID": record_id,
            "Chinese_Reference": chinese_reference,
            "Parsed_Chinese_Authors": parsed_dict.get("authors_cn") or [],
            "Parsed_Chinese_Title": title_cn,
            "Parsed_Chinese_Journal": journal_cn,
            "Parsed_Author_Et_Al": bool(parsed_dict.get("authors_et_al")),
            "Shared_LLM_Output": shared,
            "LLM_Only": llm_only,
            "Full_V390": full,
            "Exact_Title_KB_Hit": bool(title_match),
            "Review_Required": review_required,
            "Risk_Level": "medium" if review_required else "low",
            "Architecture": "source_aware_hybrid_single_shared_generation",
        }
