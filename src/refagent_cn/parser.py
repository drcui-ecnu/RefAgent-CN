from __future__ import annotations

import re
from typing import Dict, List, Tuple

ET_AL_TOKENS = {"等", "等.", "et al", "et al.", "etal", "etal."}


def count_chinese_chars(text: str) -> int:
    return len(re.findall(r"[\u4e00-\u9fff]", text or ""))


def is_likely_english_reference(text: str) -> bool:
    """Detect pure English references without treating bilingual Chinese refs as English.

    Earlier versions only treated references with explicit markers such as [J]
    as English references. In practice, many user-provided English references
    omit [J] and look like:
    Horobets O. Research data ... Journal of the Knowledge Economy, 2021, 12(3): 1424-1436.
    This detector therefore accepts references with a year + alphabetic text,
    as long as substantial Chinese text is absent.
    """
    text = (text or "").strip()
    if not text:
        return False
    if count_chinese_chars(text) >= 2:
        return False
    has_letters = bool(re.search(r"[A-Za-z]{5,}", text))
    has_year = bool(re.search(r"\b(?:19|20)\d{2}\b", text))
    has_ref_marker = bool(re.search(r"\[[A-Za-z]+(?:/[A-Za-z]+)?\]", text))
    has_journal_like = bool(re.search(r"\b(Journal|Library|Information|Scientometrics|Proceedings|Reports|Review|Reviews|Management|Knowledge|Data)\b", text, flags=re.I))
    return bool(has_letters and (has_ref_marker or (has_year and has_journal_like)))


def extract_embedded_english_reference(text: str) -> str:
    """Extract a trailing parenthesized English counterpart in a bilingual Chinese reference.

    The English counterpart itself may contain parentheses, e.g. 2014(5): 125-131.
    Therefore this function scans possible opening brackets from right to left
    rather than using a simple non-parentheses regex.
    """
    s = (text or "").strip()
    if not s or s[-1] not in ")]）":
        return ""

    # Use the final closing bracket as the wrapper and find the nearest earlier
    # opening bracket that contains an English bibliographic marker such as [J].
    close_idx = len(s) - 1
    for i in range(close_idx - 1, -1, -1):
        if s[i] not in "(（":
            continue
        content = s[i + 1:close_idx].strip()
        if re.search(r"[A-Za-z]{5,}", content) and re.search(r"\[[A-Za-z]+(?:/[A-Za-z]+)?\]", content):
            return content.rstrip(".") + "."
    return ""


def strip_embedded_english_reference(text: str) -> str:
    """Remove trailing parenthesized English counterpart before Chinese parsing."""
    embedded = extract_embedded_english_reference(text)
    if not embedded:
        return text
    s = (text or "").strip()
    close_idx = len(s) - 1
    for i in range(close_idx - 1, -1, -1):
        if s[i] not in "(（":
            continue
        content = s[i + 1:close_idx].strip()
        if content.rstrip(".") == embedded.rstrip("."):
            return s[:i].strip()
    return text


def split_english_authors_with_et_al(author_part: str) -> Tuple[List[str], bool]:
    author_part = (author_part or "").strip().strip(".")
    if not author_part:
        return [], False
    et_al = bool(re.search(r"\bet\s+al\.?$", author_part, flags=re.I))
    author_part = re.sub(r"\bet\s+al\.?$", "", author_part, flags=re.I).strip(" ,.;")
    parts = [p.strip() for p in re.split(r"\s*,\s*", author_part) if p.strip()]
    return parts, et_al


def english_author_to_apa(name: str) -> str:
    name = (name or "").strip()
    if not name:
        return ""
    if name.lower() in {"et al", "et al."}:
        return "et al."
    parts = [p for p in re.split(r"\s+", name.replace(".", "")) if p]
    if not parts:
        return name
    surname = parts[0].title() if parts[0].isupper() else parts[0]
    initials = []
    for p in parts[1:]:
        if not p:
            continue
        # "YC" -> "Y. C."; "Y" -> "Y."; "Yong" -> "Y."
        if p.isupper() and len(p) > 1:
            initials.extend([ch + "." for ch in p])
        else:
            initials.append(p[0].upper() + ".")
    return f"{surname}, {' '.join(initials)}" if initials else surname


def _find_english_journal_boundary(pre_year: str) -> int:
    """Find likely boundary between English title and journal name.

    This handles references where [J] and the period before journal are omitted,
    e.g. "... official statistics Journal of the Knowledge Economy, 2021".
    Returns the index where the journal name starts, or -1 if unknown.
    """
    text = (pre_year or "").strip()
    if not text:
        return -1

    # Strong, multi-word journal indicators. Use the last match to avoid title words.
    indicators = [
        r"\bThe\s+Journal\s+of\b",
        r"\bJournal\s+of\b",
        r"\bLibrary\s+and\s+Information\b",
        r"\bInformation\s+Studies\s*:\s*Theory\s*&\s*Application\b",
        r"\bData\s+Analysis\s+and\s+Knowledge\s+Discovery\b",
        r"\bDocumentation\s*,\s*Information\s*&\s*Knowledge\b",
        r"\bScience\s+Research\s+Management\b",
        r"\bNew\s+Century\s+Library\b",
        r"\bInformation\s+Resources\s+Management\b",
        r"\bInformation\s+Processing\s*&\s*Management\b",
        r"\bScientific\s+Reports\b",
        r"\bScientometrics\b",
        r"\bActa\s+Editologica\b",
        r"\bRenewable\s+and\s+Sustainable\s+Energy\s+Reviews\b",
        r"\bJournal\s+of\s+the\s+Knowledge\s+Economy\b",
    ]
    matches = []
    for pat in indicators:
        for m in re.finditer(pat, text, flags=re.I):
            matches.append(m.start())
    if matches:
        return max(matches)

    # Fallback: title and journal are often separated by a period.
    dot_idx = text.rfind(". ")
    if dot_idx > 0:
        return dot_idx + 2

    return -1


def _parse_english_tail_after_year(tail: str) -> Tuple[str, str, str]:
    """Parse volume, issue and pages from the part after year."""
    tail = (tail or "").strip().strip(" ,.;")
    volume = ""
    issue = ""
    pages = ""
    if not tail:
        return volume, issue, pages

    # Common: (5): 125-131, meaning issue only and no volume.
    m = re.search(r"^[\(（](?P<issue>[^\)）]+)[\)）]\s*[:：]\s*(?P<pages>[\dA-Za-z+\-–—]+(?:\s*[-–—]\s*[\dA-Za-z+]+)?)", tail)
    if m:
        return "", m.group("issue").strip(), m.group("pages").replace(" ", "")

    # Common: 12(3): 1424-1436 or 70(8): 19-30
    m = re.search(r"(?P<volume>\d+)\s*[\(（](?P<issue>[^\)）]+)[\)）]\s*[:：]\s*(?P<pages>[\dA-Za-z+\-–—]+(?:\s*[-–—]\s*[\dA-Za-z+]+)?)", tail)
    if m:
        return m.group("volume"), m.group("issue").strip(), m.group("pages").replace(" ", "")

    # Common: 107: 516-534
    m = re.search(r"(?P<volume>\d+)\s*[:：]\s*(?P<pages>[\dA-Za-z+\-–—]+(?:\s*[-–—]\s*[\dA-Za-z+]+)?)", tail)
    if m:
        return m.group("volume"), "", m.group("pages").replace(" ", "")

    # Common: 2021, 44(8): 173-179+102 -> tail passed may be 44(8):...
    m = re.search(r"(?P<volume>\d+)\s*[\(（](?P<issue>[^\)）]+)[\)）]", tail)
    if m:
        volume = m.group("volume")
        issue = m.group("issue").strip()
    else:
        m = re.search(r"\b(?P<volume>\d+)\b", tail)
        if m:
            volume = m.group("volume")

    pm = re.search(r"[:：]\s*(?P<pages>[\dA-Za-z+\-–—]+(?:\s*[-–—]\s*[\dA-Za-z+]+)?)", tail)
    if pm:
        pages = pm.group("pages").replace(" ", "")
    return volume, issue, pages


def parse_english_reference(raw_reference: str, ref_id: str = "") -> Dict:
    """Parse a user-provided English reference.

    Supported examples include:
    HE L, CHANG Y C. Research on ...[J]. Library and Information, 2014(5): 125-131.
    Horobets O. Research data as a result of research activities: The role and significance for the official statistics Journal of the Knowledge Economy, 2021, 12(3): 1424-1436.
    Zhang Meng, Mu Dongmei, Zhang Ning, et al. Research ...[J]. Library and Information Service, 2026, 70(8): 19-30.
    """
    raw_original = (raw_reference or "").strip()
    raw = normalize_reference_text(raw_original)
    warnings: List[str] = []
    base = {
        "ref_id": ref_id,
        "raw_reference": raw_original or raw,
        "ref_en_raw": raw_original or raw,
        "input_language": "en",
        "authors_cn": [],
        "authors_et_al": False,
        "authors_en": [],
        "authors_apa": [],
        "title_cn": "",
        "title_en": "",
        "journal_cn": "",
        "journal_en": "",
        "year": "",
        "volume": "",
        "issue": "",
        "pages": "",
        "doi": "",
        "access_date": "",
        "url": "",
        "source_site": "",
        "ref_type_code": "J",
        "reference_type": "journal_article",
        "title_source": "user_provided",
        "title_confidence": 1.0,
        "title_is_official": True,
        "title_is_generated": False,
        "title_need_review": False,
        "title_note": "English title was parsed from user-provided English reference.",
        "parse_warnings": warnings,
    }
    doi_match = ReferenceParser.DOI_PATTERN.search(raw)
    if doi_match:
        base["doi"] = doi_match.group(0)

    # 1) Authors: everything before the first period followed by whitespace.
    am = re.match(r"^\s*(?P<authors>.+?)\.\s+(?P<body>.+?)\s*\.?\s*$", raw)
    if not am:
        warnings.append("english_author_boundary_not_matched")
        return base
    author_part = am.group("authors").strip()
    body = am.group("body").strip()
    authors, et_al = split_english_authors_with_et_al(author_part)
    if et_al:
        authors.append("et al.")

    ref_type_raw = "J"
    title = ""
    journal = ""
    year = ""
    volume = ""
    issue = ""
    pages = ""

    # 2) Preferred pattern with explicit [J] / [EB/OL] markers.
    marker = re.search(r"\[(?P<type>[A-Za-z]+(?:/[A-Za-z]+)?)\]", body)
    access_date = ""
    url = ""
    source_site = ""
    if marker:
        ref_type_raw = marker.group("type").upper()
        ref_type_for_marker = ref_type_raw.split("/")[0]
        title = body[:marker.start()].strip(" .,")
        rest = body[marker.end():].strip(" .,")
        if ref_type_for_marker in {"EB", "DB", "R"} or ref_type_raw in {"EB/OL", "DB/OL", "R/OL"}:
            dm = ReferenceParser.ACCESS_DATE_PATTERN.search(rest)
            if dm:
                access_date = dm.group("date").replace("/", "-").replace("－", "-").replace("—", "-").replace("–", "-")
            um = ReferenceParser.URL_PATTERN.search(rest)
            if um:
                url = um.group(0).rstrip(".")
                source_site = url.split("//", 1)[-1].split("/", 1)[0]
            ym = re.search(r"(19\d{2}|20\d{2})", rest)
            if ym:
                year = ym.group(1)
        else:
            ym = re.search(r"(19\d{2}|20\d{2})", rest)
            if ym:
                journal = rest[:ym.start()].strip(" ,.")
                year = ym.group(1)
                volume, issue, pages = _parse_english_tail_after_year(rest[ym.end():])
            else:
                journal = rest.strip(" ,.")
                warnings.append("english_year_not_found")
    else:
        # 3) Pattern without [J]. Identify year and split title/journal before year.
        ym = re.search(r"(19\d{2}|20\d{2})", body)
        if not ym:
            warnings.append("english_year_not_found")
            title = body.strip(" .,")
        else:
            year = ym.group(1)
            pre_year = body[:ym.start()].strip(" ,.")
            after_year = body[ym.end():]
            boundary = _find_english_journal_boundary(pre_year)
            if boundary >= 0:
                title = pre_year[:boundary].strip(" .,")
                journal = pre_year[boundary:].strip(" .,")
            else:
                # Last-resort fallback: split at final comma-like segment is unavailable,
                # so keep body as title and warn rather than producing empty fields.
                title = pre_year.strip(" .,")
                warnings.append("english_journal_boundary_not_found")
            volume, issue, pages = _parse_english_tail_after_year(after_year)

    journal = re.sub(r"^/+/\s*", "", journal).strip()
    ref_type = ref_type_raw.split("/")[0]
    base.update({
        "authors_en": authors,
        "authors_apa": [english_author_to_apa(a) for a in authors],
        "authors_et_al": et_al,
        "title_en": title,
        "journal_en": journal,
        "year": year,
        "volume": volume,
        "issue": issue,
        "pages": pages,
        "access_date": access_date,
        "url": url,
        "source_site": source_site,
        "ref_type_code": ref_type or "J",
        "ref_type_raw": ref_type_raw,
        "reference_type": "electronic_resource" if (ref_type or "J") in {"EB", "DB", "R"} else ("journal_article" if (ref_type or "J") == "J" else "unknown"),
        "journal_source": "user_provided" if journal else "",
        "journal_match_type": "user_provided" if journal else "none",
        "journal_confidence": 1.0 if journal else 0.0,
    })
    if not title:
        warnings.append("english_title_not_found")
    if not journal and (ref_type or "J") not in {"EB", "DB", "R"}:
        warnings.append("english_journal_not_found")
    if (ref_type or "J") in {"EB", "DB", "R"} and not url:
        warnings.append("english_url_not_found")
    return base


def normalize_reference_text(text: str) -> str:
    """Normalize common Chinese reference punctuation for rule parsing."""
    text = (text or "").strip()
    trans = {
        "．": ".", "。": ".", "，": ",", "；": ";", "：": ":",
        "（": "(", "）": ")", "［": "[", "］": "]",
        "–": "-", "—": "-",
    }
    for k, v in trans.items():
        text = text.replace(k, v)
    return re.sub(r"\s+", " ", text).strip()


def split_authors_with_et_al(author_part: str) -> Tuple[List[str], bool]:
    """split_authors_with_et_al; preserved production heuristic. See reproducibility documentation."""





    author_part = (author_part or "").strip()
    author_part = author_part.replace("，", ",").replace("；", ";")
    et_al = False
    parts = re.split(r"[,;、，；]\s*", author_part)
    authors: List[str] = []
    for raw in parts:
        p = raw.strip().strip(" .。")
        if not p:
            continue
        lowered = p.lower()
        if p in ET_AL_TOKENS or lowered in ET_AL_TOKENS:
            et_al = True
            continue
        # Preserved production heuristic.
        if p.endswith("等") and len(p) > 1:
            p = p[:-1].strip()
            et_al = True
        if re.search(r"\bet\s+al\.?$", p, flags=re.IGNORECASE):
            p = re.sub(r"\bet\s+al\.?$", "", p, flags=re.IGNORECASE).strip(" ,.;")
            et_al = True
        if p:
            authors.append(p)
    return authors, et_al


def split_authors(author_part: str) -> List[str]:
    return split_authors_with_et_al(author_part)[0]


class ReferenceParser:
    """ReferenceParser; preserved production heuristic. See reproducibility documentation."""








    DOI_PATTERN = re.compile(r"\b10\.\d{4,9}/[-._;()/:A-Za-z0-9]+\b")
    URL_PATTERN = re.compile(r"https?://[^\s。)）]+", re.IGNORECASE)
    ACCESS_DATE_PATTERN = re.compile(r"[\[【](?P<date>\d{4}[-－—–/]\d{1,2}[-－—–/]\d{1,2})[\]】]")
    # Support [J], [J/OL], [M], [EB/OL], etc.
    HEAD_PATTERN = re.compile(
        r"^\s*(?P<authors>.+?)\.\s*(?P<title>.+?)\s*\[(?P<type>[A-Za-z]+(?:/[A-Za-z]+)?)\]\s*\.\s*(?P<rest>.+?)\s*\.?\s*$"
    )
    YEAR_PATTERN = re.compile(r"(?P<year>\d{4})")
    VOL_ISSUE_PATTERN = re.compile(r"^\s*(?P<volume>[^\(（:：,，]+?)?\s*(?:[\(（](?P<issue>[^\)）]+)[\)）])?\s*$")

    def parse(self, raw_reference: str, ref_id: str = "") -> Dict:
        raw_reference_original = (raw_reference or "").strip()

        # Pure English references pasted by the user are parsed directly and do not enter LLM generation.
        if is_likely_english_reference(raw_reference_original):
            return parse_english_reference(raw_reference_original, ref_id=ref_id)

        # Bilingual Chinese references may contain an English counterpart in parentheses.
        # Keep the English part as factual user-provided evidence, but parse the Chinese part as the main citation.
        embedded_en_ref = extract_embedded_english_reference(raw_reference_original)
        cn_reference_original = strip_embedded_english_reference(raw_reference_original)

        raw_reference = normalize_reference_text(cn_reference_original)
        warnings: List[str] = []
        doi_match = self.DOI_PATTERN.search(raw_reference)
        doi = doi_match.group(0).rstrip(".。;；,，") if doi_match else ""
        # Remove DOI fragments before structural parsing. Otherwise references such as
        # "16(01):50-62.DOI:10.xxxx" will be split on the DOI colon and pollute
        # volume/issue/page extraction. The DOI value is preserved in `doi`.
        if doi_match:
            raw_reference = (raw_reference[:doi_match.start()] + raw_reference[doi_match.end():]).strip()
            raw_reference = re.sub(r"(?i)\bdoi\s*[:：]\s*", "", raw_reference)
            raw_reference = re.sub(r"[.。;；,，\s]+$", "", raw_reference).strip() + "."

        base = {
            "ref_id": ref_id,
            "raw_reference": cn_reference_original or raw_reference,
            "ref_cn_raw": cn_reference_original or raw_reference,
            "ref_en_raw": embedded_en_ref,
            "input_language": "zh",
            "authors_cn": [],
            "authors_et_al": False,
            "title_cn": "",
            "journal_cn": "",
            "year": "",
            "volume": "",
            "issue": "",
            "pages": "",
            "doi": doi,
            "access_date": "",
            "url": "",
            "source_site": "",
            "ref_type_code": "",
            "reference_type": "unknown",
            "parse_warnings": warnings,
        }

        m = self.HEAD_PATTERN.match(raw_reference)
        if not m:
            warnings.append("parse_pattern_not_matched")
            return base

        authors, authors_et_al = split_authors_with_et_al(m.group("authors"))
        title = m.group("title").strip()
        ref_type_raw = m.group("type").upper()
        ref_type = ref_type_raw.split("/")[0]
        rest = m.group("rest").strip()

        # Rest roughly varies by type:
        # Preserved production heuristic.
        # Preserved production heuristic.
        # Preserved production heuristic.
        # [EB/OL] [access date]. URL
        page_part = ""
        # Preserved production heuristic.
        # the URL contains a colon. Never split page information on URL colons.
        online_url_match = self.URL_PATTERN.search(rest)
        if online_url_match:
            url = online_url_match.group(0).rstrip(".。),，;；")
            source_site = url.split("//", 1)[-1].split("/", 1)[0]
            rest_for_source = rest[:online_url_match.start()].strip(" .。;,，")
        else:
            url = ""
            source_site = ""
            rest_for_source = rest

        # Only split page information for journal-like records without URLs.
        if ":" in rest_for_source and ref_type == "J":
            rest_for_source, page_part = rest_for_source.rsplit(":", 1)
            page_part = page_part.strip().rstrip(".").replace(" ", "")

        parts = [p.strip() for p in re.split(r"[,，]", rest_for_source) if p.strip()]
        journal = ""
        institution = ""
        publisher = ""
        place = ""
        year = ""
        volume = ""
        issue = ""
        access_date = ""
        # url/source_site may have been filled above for [J/OL] records.

        if ref_type == "D":
            # Preserved production heuristic.
            for p0 in parts:
                ym = self.YEAR_PATTERN.search(p0)
                if ym and not year:
                    year = ym.group("year")
                elif not institution:
                    institution = p0.strip(" .。")
            reference_type = "thesis"
        elif ref_type == "M":
            # Preserved production heuristic.
            rest_no_year = rest
            ym = self.YEAR_PATTERN.search(rest)
            if ym:
                year = ym.group("year")
                rest_no_year = rest[:ym.start()].strip(" ,，.;；")
            if ":" in rest_no_year or "：" in rest_no_year:
                place, publisher = re.split(r"[:：]", rest_no_year, maxsplit=1)
                place = place.strip(" ,，.;；")
                publisher = publisher.strip(" ,，.;；")
            elif parts:
                publisher = parts[0].strip(" .。")
            reference_type = "book"
        elif ref_type in {"EB", "DB", "R"} or ref_type_raw in {"EB/OL", "DB/OL", "R/OL"}:
            # Preserved production heuristic.
            dm = self.ACCESS_DATE_PATTERN.search(rest)
            if dm:
                access_date = dm.group("date").replace("/", "-").replace("－", "-").replace("—", "-").replace("–", "-")
            um = self.URL_PATTERN.search(rest)
            if um:
                url = um.group(0).rstrip(".")
                source_site = url.split("//", 1)[-1].split("/", 1)[0]
            ym = self.YEAR_PATTERN.search(rest)
            if ym:
                year = ym.group("year")
            reference_type = "electronic_resource"
        else:
            # Journal article, including online-first [J/OL].
            journal = parts[0].strip(" .。") if parts else ""
            # For online-first refs, keep the journal before the URL and do not
            # force year/volume/pages; they may not be assigned yet.
            if url and ref_type_raw == "J/OL":
                reference_type = "journal_article"
                remaining = []
            else:
                remaining = []
            for p0 in parts[1:]:
                ym = self.YEAR_PATTERN.search(p0)
                if ym and not year:
                    year = ym.group("year")
                    tail = p0[ym.end():].strip(" ,")
                    if tail:
                        remaining.append(tail)
                else:
                    remaining.append(p0)

            if remaining:
                vi_raw = remaining[0]
                vm = self.VOL_ISSUE_PATTERN.match(vi_raw)
                if vm:
                    volume = (vm.group("volume") or "").strip()
                    issue = (vm.group("issue") or "").strip()
                else:
                    volume = vi_raw.strip()
            reference_type = "journal_article" if ref_type == "J" else "unknown"
            if ref_type != "J":
                warnings.append("reference_type_not_fully_supported")

        base.update({
            "authors_cn": authors,
            "authors_et_al": authors_et_al,
            "title_cn": title,
            "journal_cn": journal,
            "institution_cn": institution,
            "publisher_cn": publisher,
            "place_cn": place,
            "year": year,
            "volume": volume,
            "issue": issue,
            "pages": page_part,
            "access_date": access_date,
            "url": url,
            "source_site": source_site,
            "ref_type_code": ref_type,
            "ref_type_raw": ref_type_raw,
            "reference_type": reference_type,
        })

        if embedded_en_ref:
            en_parsed = parse_english_reference(embedded_en_ref, ref_id=ref_id)
            if en_parsed.get("title_en"):
                base.update({
                    "ref_en_raw": embedded_en_ref,
                    "title_en": en_parsed.get("title_en", ""),
                    "title_source": "user_provided_en_embedded",
                    "title_confidence": 1.0,
                    "title_is_official": True,
                    "title_is_generated": False,
                    "title_need_review": False,
                    "title_note": "English title was parsed from the embedded English counterpart provided by the user.",
                })
            if en_parsed.get("journal_en"):
                base.update({
                    "journal_en": en_parsed.get("journal_en", ""),
                    "journal_source": "user_provided_en_embedded",
                    "journal_match_type": "user_provided",
                    "journal_confidence": 1.0,
                })
        return base
