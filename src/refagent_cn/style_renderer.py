from __future__ import annotations

import re
from typing import Any, Dict, List

EN_DASH = "–"
_SMALL_WORDS = {"a", "an", "the", "and", "but", "or", "nor", "for", "so", "yet", "as", "at", "by", "from", "in", "into", "of", "on", "onto", "over", "per", "to", "up", "via", "with", "within", "without", "than"}
_KEEP_UPPER = {"AI", "API", "CNKI", "DOI", "GB/T", "JSON", "LLM", "MLA", "APA", "PDF", "RDF", "SCI", "SSCI", "XML", "OA", "NMF", "LLMS", "GENAI"}
_PROPER_WORDS = {"Chinese", "English", "China", "OpenAI", "DeepSeek", "SiliconFlow", "WeChat", "Xiaohongshu"}


def _is_et_al(value: str) -> bool:
    return (value or "").strip().lower() in {"et al", "et al."}


def _terminal_period(text: str) -> str:
    return "" if (text or "").rstrip().endswith(".") else "."


def _join_authors_plain(authors: List[str]) -> str:
    return ", ".join([a for a in authors if a])


def _join_authors_apa(authors_apa: List[str]) -> str:
    authors = [a for a in authors_apa if a]
    if not authors:
        return ""
    if _is_et_al(authors[-1]):
        if len(authors) == 1:
            return "et al."
        return ", ".join(authors)
    if len(authors) == 1:
        return authors[0]
    if len(authors) == 2:
        return f"{authors[0]}, & {authors[1]}"
    return ", ".join(authors[:-1]) + f", & {authors[-1]}"


def _join_authors_mla(authors_en: List[str]) -> str:
    authors = [a for a in authors_en if a]
    if not authors:
        return ""

    def invert(name: str) -> str:
        if _is_et_al(name):
            return "et al."
        parts = name.split()
        if len(parts) >= 2:
            return f"{parts[0]}, {' '.join(parts[1:])}"
        return name

    if _is_et_al(authors[-1]):
        return f"{invert(authors[0])}, et al."
    if len(authors) == 1:
        return invert(authors[0])
    if len(authors) == 2:
        return f"{invert(authors[0])}, and {authors[1]}"
    return f"{invert(authors[0])}, et al."


def _normalize_pages(pages: str) -> str:
    return (pages or "").strip().replace("-", EN_DASH).replace("—", EN_DASH)


def _strip_terminal_punctuation(text: str) -> str:
    return (text or "").strip().strip(" .。；;，,：:")


def _cap_first_alpha(text: str) -> str:
    chars = list(text)
    for i, ch in enumerate(chars):
        if ch.isalpha():
            chars[i] = ch.upper()
            break
    return "".join(chars)


def _preserve_special_word(original: str, converted: str) -> str:
    stripped = original.strip(".,:;!?()[]{}\"'“”‘’")
    if stripped in _KEEP_UPPER or stripped.upper() in _KEEP_UPPER:
        return original.replace(stripped, stripped.upper())
    if stripped in _PROPER_WORDS:
        return original
    return converted


def _sentence_case_title(title: str) -> str:
    title = _strip_terminal_punctuation(title)
    if not title:
        return ""
    tokens = re.split(r"(\s+)", title)
    out = []
    new_sentence = True
    for token in tokens:
        if token.isspace():
            out.append(token)
            continue
        bare = token.strip(".,:;!?()[]{}\"'“”‘’")
        if not bare:
            out.append(token)
            continue
        if bare in _KEEP_UPPER or bare.upper() in _KEEP_UPPER or bare in _PROPER_WORDS:
            converted = token
        else:
            converted = token.lower()
            if new_sentence:
                converted = _cap_first_alpha(converted)
        out.append(_preserve_special_word(token, converted))
        new_sentence = token.endswith(":") or token.endswith("：")
    return _cap_first_alpha("".join(out).strip())


def _title_case_word(word: str, force_cap: bool = False) -> str:
    m = re.match(r"^([^A-Za-z0-9]*)(.*?)([^A-Za-z0-9]*)$", word)
    if not m:
        return word
    prefix, core, suffix = m.groups()
    if not core:
        return word
    if core in _KEEP_UPPER or core.upper() in _KEEP_UPPER:
        new_core = core.upper()
    elif not force_cap and core.lower() in _SMALL_WORDS:
        new_core = core.lower()
    else:
        parts = core.split("-")
        new_parts = []
        for part in parts:
            if not part:
                new_parts.append(part)
            elif part.upper() in _KEEP_UPPER:
                new_parts.append(part.upper())
            else:
                new_parts.append(part[:1].upper() + part[1:].lower())
        new_core = "-".join(new_parts)
    return prefix + new_core + suffix


def _mla_title_case(title: str) -> str:
    title = _strip_terminal_punctuation(title)
    if not title:
        return ""
    words = title.split()
    converted = []
    for i, word in enumerate(words):
        force = i == 0 or i == len(words) - 1
        if i > 0 and converted and converted[-1].endswith(":"):
            force = True
        converted.append(_title_case_word(word, force_cap=force))
    return " ".join(converted)


def _format_type_code(ref: Dict) -> str:
    code = (ref.get("ref_type_raw") or ref.get("ref_type_code") or "J").strip()
    return code or "J"


def render_gbt7714_en(ref: Dict) -> str:
    authors = _join_authors_plain(ref.get("authors_en", [])) or _join_authors_plain(ref.get("authors_cn", []))
    title = _strip_terminal_punctuation(ref.get("title_en", "").strip() or ref.get("title_cn", "").strip())
    year = ref.get("year", "").strip()
    type_code = _format_type_code(ref)
    ref_type = type_code.upper().split("/")[0]

    if ref_type == "D":
        institution = ref.get("institution_en", "").strip() or ref.get("institution_cn", "").strip()
        return f"{authors}{_terminal_period(authors)} {title}[D]. {institution}, {year}."

    if ref_type == "M":
        publisher = ref.get("publisher_en", "").strip() or ref.get("publisher_cn", "").strip()
        place = ref.get("place_en", "").strip() or ref.get("place_cn", "").strip()
        source = f"{place}: {publisher}" if place and publisher else (publisher or place)
        return f"{authors}{_terminal_period(authors)} {title}[M]. {source}, {year}."

    if ref_type in {"EB", "DB", "R"} or type_code.upper() in {"EB/OL", "DB/OL", "R/OL"}:
        access_date = ref.get("access_date", "").strip()
        url = ref.get("url", "").strip()
        date_part = f" [{access_date}]." if access_date else ""
        url_part = f" {url}." if url else ""
        return f"{authors}{_terminal_period(authors)} {title}[{type_code}].{date_part}{url_part}".strip()

    journal = ref.get("journal_en", "").strip() or ref.get("journal_cn", "").strip()
    volume = ref.get("volume", "").strip()
    issue = ref.get("issue", "").strip()
    pages = ref.get("pages", "").strip()
    vi = ""
    if volume and issue:
        vi = f", {volume}({issue})"
    elif volume:
        vi = f", {volume}"
    elif issue:
        vi = f"({issue})"
    page_part = f": {pages}" if pages else ""

    if type_code.upper() == "J/OL":
        url = ref.get("url", "").strip()
        if year or volume or issue or pages:
            core = f"{authors}{_terminal_period(authors)} {title}[J/OL]. {journal}"
            if year:
                core += f", {year}{vi}{page_part}"
            elif vi or page_part:
                core += f"{vi}{page_part}"
            if url:
                core += f". {url}"
            return _ensure_period(core)
        url_part = f" {url}." if url else ""
        return f"{authors}{_terminal_period(authors)} {title}[J/OL]. {journal}.{url_part}".strip()

    return f"{authors}{_terminal_period(authors)} {title}[{type_code}]. {journal}, {year}{vi}{page_part}."


def _clean_cn_reference(ref: Dict) -> str:
    cn = (ref.get("ref_cn_raw") or ref.get("raw_reference") or "").strip()
    # Remove embedded English counterpart if present.
    cn = re.sub(r"\s*[\(（]\s*[^()（）]{20,}?\[[A-Za-z]+(?:/[A-Za-z]+)?\].*?[\)）]\s*$", "", cn).strip()
    return cn


def _ensure_period(text: str) -> str:
    text = (text or "").strip()
    return text if not text or text.endswith((".", "。")) else text + "."


def render_gbt7714_bilingual(ref: Dict) -> str:
    """render_gbt7714_bilingual; preserved production heuristic. See reproducibility documentation."""





    if (ref.get("input_language") or "").lower() == "en" and not ref.get("ref_cn_raw"):
        return render_gbt7714_en(ref)

    ref_cn = _ensure_period(_clean_cn_reference(ref))
    ref_en = _ensure_period((ref.get("ref_en_raw") or "").strip() or render_gbt7714_en(ref))

    if not ref_cn:
        return ref_en
    if not ref_en:
        return ref_cn
    return f"{ref_cn}\n({ref_en})"

def render_apa_en(ref: Dict) -> str:
    authors = _join_authors_apa(ref.get("authors_apa", [])) or _join_authors_plain(ref.get("authors_en", []))
    year = ref.get("year", "").strip() or "n.d."
    title = _sentence_case_title(ref.get("title_en", "").strip() or ref.get("title_cn", "").strip())
    type_code = _format_type_code(ref).upper().split("/")[0]

    if type_code == "D":
        institution = ref.get("institution_en", "").strip() or ref.get("institution_cn", "").strip()
        bracket = f"[Dissertation, {institution}]" if institution else "[Dissertation]"
        return f"{authors} ({year}). {title} {bracket}."

    if type_code == "M":
        publisher = ref.get("publisher_en", "").strip() or ref.get("publisher_cn", "").strip()
        return f"{authors} ({year}). {title}. {publisher}."

    if type_code in {"EB", "DB", "R"}:
        url = ref.get("url", "").strip()
        access_date = ref.get("access_date", "").strip()
        suffix = f" Retrieved {access_date}, from {url}" if access_date and url else (f" {url}" if url else "")
        return f"{authors} ({year}). {title}.{suffix}".strip()

    journal = ref.get("journal_en", "").strip() or ref.get("journal_cn", "").strip()
    volume = ref.get("volume", "").strip()
    issue = ref.get("issue", "").strip()
    pages = _normalize_pages(ref.get("pages", "").strip())
    vol_issue = f", {volume}({issue})" if volume and issue else (f", {volume}" if volume else (f", ({issue})" if issue else ""))
    pages_part = f", {pages}" if pages else ""
    return f"{authors} ({year}). {title}. {journal}{vol_issue}{pages_part}."


def render_mla_en(ref: Dict) -> str:
    authors = _join_authors_mla(ref.get("authors_en", []))
    title = _mla_title_case(ref.get("title_en", "").strip() or ref.get("title_cn", "").strip())
    type_code = _format_type_code(ref).upper().split("/")[0]
    year = ref.get("year", "").strip()

    if type_code == "D":
        institution = ref.get("institution_en", "").strip() or ref.get("institution_cn", "").strip()
        return f'{authors}{_terminal_period(authors)} "{title}." {institution}, {year}.'

    if type_code == "M":
        publisher = ref.get("publisher_en", "").strip() or ref.get("publisher_cn", "").strip()
        return f'{authors}{_terminal_period(authors)} {title}. {publisher}, {year}.'

    if type_code in {"EB", "DB", "R"}:
        url = ref.get("url", "").strip()
        access_date = ref.get("access_date", "").strip()
        access = f" Accessed {access_date}." if access_date else ""
        return f'{authors}{_terminal_period(authors)} "{title}." Web.{access} {url}.'.strip()

    journal = ref.get("journal_en", "").strip() or ref.get("journal_cn", "").strip()
    volume = ref.get("volume", "").strip()
    issue = ref.get("issue", "").strip()
    pages = _normalize_pages(ref.get("pages", "").strip())
    pages_part = f"pp. {pages}" if pages else ""
    head = f'{authors}{_terminal_period(authors)} "{title}." {journal}' if journal else f'{authors}{_terminal_period(authors)} "{title}."'
    parts = []
    if volume:
        parts.append(f"vol. {volume}")
    if issue:
        parts.append(f"no. {issue}")
    if year:
        parts.append(year)
    if pages_part:
        parts.append(pages_part)
    return head + (", " + ", ".join(parts) if parts else "") + "."


def render_harvard_en(ref: Dict) -> str:
    authors = _join_authors_plain(ref.get("authors_apa", [])) or _join_authors_plain(ref.get("authors_en", []))
    year = ref.get("year", "").strip() or "n.d."
    title = _sentence_case_title(ref.get("title_en", "").strip() or ref.get("title_cn", "").strip())
    type_code = _format_type_code(ref).upper().split("/")[0]

    if type_code == "D":
        institution = ref.get("institution_en", "").strip() or ref.get("institution_cn", "").strip()
        tail = f" PhD thesis, {institution}." if institution else " PhD thesis."
        return f"{authors} {year}, {title},{tail}"

    if type_code == "M":
        publisher = ref.get("publisher_en", "").strip() or ref.get("publisher_cn", "").strip()
        return f"{authors} {year}, {title}, {publisher}." if publisher else f"{authors} {year}, {title}."

    if type_code in {"EB", "DB", "R"}:
        url = ref.get("url", "").strip()
        access_date = ref.get("access_date", "").strip()
        avail = f" Available at: {url}" if url else ""
        acc = f" (Accessed: {access_date})" if access_date else ""
        return f"{authors} {year}, {title}.{avail}{acc}.".strip()

    journal = ref.get("journal_en", "").strip() or ref.get("journal_cn", "").strip()
    volume = ref.get("volume", "").strip()
    issue = ref.get("issue", "").strip()
    pages = _normalize_pages(ref.get("pages", "").strip())
    vol_issue = f", vol. {volume}" if volume else ""
    if issue:
        vol_issue += f", no. {issue}"
    pages_part = f", pp. {pages}" if pages else ""
    journal_part = f", {journal}" if journal else ""
    return f"{authors} {year}, '{title}'{journal_part}{vol_issue}{pages_part}."


class StyleRenderer:
    BUILTIN = ["apa_en", "mla_en", "harvard_en", "gbt7714_en", "gbt7714_bilingual"]
    JOURNAL_AUTO_STYLE = "journal_specific_gbt7714_en"
    SUPPORTED = BUILTIN[:]

    def __init__(self, templates: Dict[str, Any] | None = None) -> None:
        self.templates = templates or {}

    def available_styles(self) -> List[str]:
        styles = list(self.BUILTIN)
        if self.JOURNAL_AUTO_STYLE not in styles:
            styles.append(self.JOURNAL_AUTO_STYLE)
        for key, tpl in (self.templates or {}).items():
            if key == "all" or key in styles:
                continue
            if isinstance(tpl, dict) and tpl.get("enabled", True):
                styles.append(key)
        return styles

    def _context(self, ref: Dict) -> Dict[str, Any]:
        authors_en = _join_authors_plain(ref.get("authors_en", [])) or _join_authors_plain(ref.get("authors_cn", []))
        authors_apa = _join_authors_apa(ref.get("authors_apa", [])) or authors_en
        authors_mla = _join_authors_mla(ref.get("authors_en", [])) or authors_en
        authors_upper_initials = _join_authors_plain(ref.get("authors_upper_initials", [])) or authors_en
        authors_title_initials = _join_authors_plain(ref.get("authors_title_initials", [])) or authors_en
        authors_upper_surname_full_given = _join_authors_plain(ref.get("authors_upper_surname_full_given", [])) or authors_en
        pages = (ref.get("pages") or "").strip()
        pages_dash = _normalize_pages(pages)
        return {
            "authors_en": authors_en,
            "author_period": _terminal_period(authors_en),
            "authors_apa": authors_apa,
            "authors_mla": authors_mla,
            "authors_upper_initials": authors_upper_initials,
            "author_period_upper_initials": _terminal_period(authors_upper_initials),
            "authors_title_initials": authors_title_initials,
            "author_period_title_initials": _terminal_period(authors_title_initials),
            "authors_upper_surname_full_given": authors_upper_surname_full_given,
            "author_period_upper_surname_full_given": _terminal_period(authors_upper_surname_full_given),
            "authors_cn": ", ".join(ref.get("authors_cn", [])) + (", 等" if ref.get("authors_et_al") else ""),
            "title_en": _strip_terminal_punctuation(ref.get("title_en", "") or ref.get("title_cn", "")),
            "title_en_sentence": _sentence_case_title(ref.get("title_en", "") or ref.get("title_cn", "")),
            "title_en_title": _mla_title_case(ref.get("title_en", "") or ref.get("title_cn", "")),
            "title_cn": _strip_terminal_punctuation(ref.get("title_cn", "")),
            "journal_en": ref.get("journal_en", "") or ref.get("journal_cn", ""),
            "journal_cn": ref.get("journal_cn", ""),
            "institution_en": ref.get("institution_en", "") or ref.get("institution_cn", ""),
            "institution_cn": ref.get("institution_cn", ""),
            "publisher_en": ref.get("publisher_en", "") or ref.get("publisher_cn", ""),
            "publisher_cn": ref.get("publisher_cn", ""),
            "place_cn": ref.get("place_cn", ""),
            "year": ref.get("year", ""),
            "volume": ref.get("volume", ""),
            "issue": ref.get("issue", ""),
            "pages": pages,
            "pages_dash": pages_dash,
            "type_code": _format_type_code(ref),
            "doi": ref.get("doi", ""),
            "access_date": ref.get("access_date", ""),
            "url": ref.get("url", ""),
            "source_site": ref.get("source_site", ""),
        }

    def _render_custom(self, ref: Dict, style: str) -> str:
        tpl = (self.templates or {}).get(style)
        if not isinstance(tpl, dict):
            raise ValueError(f"Unsupported style: {style}")
        fmt = str(tpl.get("format") or "").strip()
        base_style = str(tpl.get("base_style") or "").strip()
        if not fmt and base_style in self.BUILTIN:
            return self.render_one(ref, base_style)
        if not fmt:
            raise ValueError(f"Custom style {style} has no format string or valid base_style.")
        ctx = self._context(ref)
        try:
            rendered = fmt.format(**ctx)
        except KeyError as exc:
            raise ValueError(f"Custom style {style} uses unknown placeholder: {exc}") from exc
        return rendered.strip()

    def _render_journal_specific(self, ref: Dict) -> str:
        journal_cn = (ref.get("journal_cn") or "").strip()
        journal_en = (ref.get("journal_en") or "").strip()
        for key, tpl in (self.templates or {}).items():
            if key in {"all", "apa_en", "mla_en", "harvard_en", "gbt7714_en", "gbt7714_bilingual", self.JOURNAL_AUTO_STYLE}:
                continue
            if not isinstance(tpl, dict) or not tpl.get("enabled", True):
                continue
            if (tpl.get("journal_name_cn") or "").strip() == journal_cn or (tpl.get("journal_name_en") or "").strip() == journal_en:
                return self._render_custom(ref, key)
        return render_gbt7714_en(ref)

    def render_one(self, ref: Dict, style: str) -> str:
        style = (style or "gbt7714_en").strip()
        if style == "gbt7714_en":
            return render_gbt7714_en(ref)
        if style == "gbt7714_bilingual":
            return render_gbt7714_bilingual(ref)
        if style == "apa_en":
            return render_apa_en(ref)
        if style == "mla_en":
            return render_mla_en(ref)
        if style == "harvard_en":
            return render_harvard_en(ref)
        if style == self.JOURNAL_AUTO_STYLE:
            return self._render_journal_specific(ref)
        return self._render_custom(ref, style)

    def render_all(self, ref: Dict, include_custom: bool = False) -> Dict[str, str]:
        styles = self.available_styles() if include_custom else self.BUILTIN
        return {style: self.render_one(ref, style) for style in styles}
