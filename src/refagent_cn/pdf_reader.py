from __future__ import annotations

import re
import shutil
import subprocess
import tempfile
import unicodedata
from pathlib import Path
from typing import Any, Dict, List, Tuple


# ASCII-only URL matching avoids swallowing Chinese explanatory paragraphs
# after CNKI online-first URLs when PDF extraction removes line breaks.
URL_ASCII_RE = re.compile(r"https?://[A-Za-z0-9._~:/?#\[\]@!$&'()*+,;=%-]+", re.I)

COMMON_JOURNAL_EN_CN = {
    "library and information service": "图书情报工作",
    "journal of library science in china": "中国图书馆学报",
    "data analysis and knowledge discovery": "数据分析与知识发现",
    "chinese journal of scientific and technical periodicals": "中国科技期刊研究",
    "information studies: theory & application": "情报理论与实践",
    "information studies:theory & application": "情报理论与实践",
    "journal of information resources management": "信息资源管理学报",
    "information resources management journal": "信息资源管理学报",
}


def _nfkc(text: str) -> str:
    text = unicodedata.normalize("NFKC", text or "")
    text = text.replace("\u00a0", " ").replace("\u200b", "")
    text = text.replace("ﬀ", "ff").replace("ﬁ", "fi").replace("ﬂ", "fl")
    return text


def _normalize_line(line: str) -> str:
    line = _nfkc(line).strip()
    line = re.sub(r"\s+", " ", line)
    return line


def _normalize_text(text: str) -> str:
    text = _nfkc(text)
    text = text.replace("．", ".").replace("。", ".")
    text = text.replace("，", ",").replace("：", ":")
    text = text.replace("（", "(").replace("）", ")")
    text = text.replace("［", "[").replace("］", "]")
    text = text.replace("－", "-").replace("–", "-").replace("—", "-")
    text = text.replace("∥", "//")
    return text


def _selected_page_indices(n: int, front_pages: int, back_pages: int) -> List[int]:
    indices = list(range(min(front_pages, n)))
    for i in range(max(0, n - back_pages), n):
        if i not in indices:
            indices.append(i)
    return indices


def _extract_with_pymupdf(raw: bytes, front_pages: int, back_pages: int) -> Tuple[str, int, str]:
    try:
        import fitz  # PyMuPDF
    except Exception:
        return "", 0, "PyMuPDF 未安装。请运行 pip install PyMuPDF 后再读取 PDF。"
    try:
        doc = fitz.open(stream=raw, filetype="pdf")
        n = len(doc)
        pages: List[str] = []
        for i in _selected_page_indices(n, front_pages, back_pages):
            try:
                t = doc[i].get_text("text") or ""
                pages.append(f"\n--- PDF_PAGE_{i + 1} ---\n{t}")
            except Exception:
                continue
        doc.close()
        return "\n".join(pages), n, ""
    except Exception as exc:
        return "", 0, f"PDF 读取失败：{type(exc).__name__}: {exc}"


def _extract_with_pdftotext(raw: bytes, front_pages: int, back_pages: int, page_count: int = 0) -> Tuple[str, str]:
    if not shutil.which("pdftotext"):
        return "", ""
    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as f:
            f.write(raw)
            tmp_path = f.name

        ranges: List[Tuple[int, int]] = []
        if page_count > 0:
            ranges.append((1, min(front_pages, page_count)))
            b1, b2 = max(1, page_count - back_pages + 1), page_count
            if b1 > ranges[0][1]:
                ranges.append((b1, b2))
        else:
            ranges.append((1, front_pages))

        chunks: List[str] = []
        for start, end in ranges:
            proc = subprocess.run(
                ["pdftotext", "-layout", "-f", str(start), "-l", str(end), tmp_path, "-"],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=15,
            )
            if proc.returncode == 0:
                txt = proc.stdout.decode("utf-8", errors="ignore")
                for off, part in enumerate(txt.split("\f")):
                    part = part.strip("\n")
                    if part.strip():
                        chunks.append(f"\n--- PDF_PAGE_{start + off} ---\n{part}")
        return "\n".join(chunks), ""
    except Exception:
        return "", ""
    finally:
        if tmp_path:
            try:
                Path(tmp_path).unlink(missing_ok=True)
            except Exception:
                pass


def extract_pdf_text(raw: bytes, front_pages: int = 5, back_pages: int = 5) -> Tuple[str, str]:
    """Extract text from selected front/back pages.

    PyMuPDF is preferred for Chinese journal PDFs because it usually preserves
    front-page title/author metadata better than pdftotext. pdftotext remains a
    selected-page fallback, not a whole-document scan, to avoid bibliography
    lines contaminating title/journal extraction.
    """
    pymu_text, page_count, warning = _extract_with_pymupdf(raw, front_pages, back_pages)
    cjk_count = len(re.findall(r"[\u4e00-\u9fff]", pymu_text or ""))
    if pymu_text and cjk_count >= 20:
        return pymu_text, ""

    pdf_text, _ = _extract_with_pdftotext(raw, front_pages, back_pages, page_count=page_count)
    if pdf_text:
        return pdf_text, ""
    if pymu_text:
        return pymu_text, ""
    return "", warning or "PDF 文本层为空或无法读取；如为扫描件，请先 OCR。"


def _front_text(text: str, max_pages: int = 3) -> str:
    if not text:
        return ""
    parts = re.split(r"\n--- PDF_PAGE_(\d+) ---\n", text)
    if len(parts) <= 1:
        return text[:10000]
    out: List[str] = []
    for i in range(1, len(parts), 2):
        try:
            page_no = int(parts[i])
        except Exception:
            page_no = 999
        if page_no <= max_pages:
            out.append(parts[i + 1])
    return "\n".join(out) or text[:10000]


def _strip_english_citation_block(ref: str) -> str:
    ref = ref or ""
    ref = re.split(r"\s*[（(]\s*Citation\s*[:：]", ref, maxsplit=1, flags=re.I)[0]
    ref = re.sub(r"\s*[（(]\s*[A-Z][A-Za-z ,.'\-]+?\[[A-Z](?:/[A-Z]+)?\].*?[）)]\s*$", "", ref, flags=re.I)
    return ref.strip()


def _normalize_embedded_urls(text: str) -> str:
    if not text:
        return text

    def repl(m: re.Match) -> str:
        url = re.sub(r"\s+", "", m.group(0))
        return url.rstrip(".。),，;；")

    return re.sub(r"https?\s*:\s*/\s*/\s*[A-Za-z0-9._~:/?#\[\]@!$&'()*+,;=%\-\s]+", repl, text)


def _clean_reference(ref: str) -> str:
    ref = _strip_english_citation_block(_normalize_text(ref))
    ref = _normalize_embedded_urls(ref)
    ref = re.sub(r"\s+", " ", ref).strip()
    ref = re.sub(r"(?<=[\u4e00-\u9fff])\s+(?=[\u4e00-\u9fff])", "", ref)

    if "[J/OL]" not in ref.upper() and not re.search(r"\[(?:EB|DB|R)/OL\]", ref, flags=re.I):
        ref = re.sub(r"\s*https?://\S+\s*$", "", ref).strip()

    url_map: List[str] = []

    def _url_hold(m: re.Match) -> str:
        url = m.group(0).rstrip(".。),，;；")
        url_map.append(url)
        return f"__URL_HOLD_{len(url_map)-1}__"

    ref = URL_ASCII_RE.sub(_url_hold, ref)
    ref = re.sub(r"\s*([.,:;\[\]\(\)])\s*", lambda m: m.group(1) if m.group(1) in "[]()" else m.group(1) + " ", ref)
    for i, url in enumerate(url_map):
        ref = ref.replace(f"__URL_HOLD_{i}__", url)

    ref = re.sub(r"\s+", " ", ref).strip()
    ref = ref.replace("[ J ]", "[J]").replace("[ J/OL ]", "[J/OL]").replace("[J / OL]", "[J/OL]")
    ref = _strip_english_citation_block(ref).strip()

    if "[J/OL]" in ref.upper():
        m = URL_ASCII_RE.search(ref)
        if m:
            ref = ref[:m.end()].rstrip(" .。") + "."
    if ref and not ref.endswith("."):
        ref += "."
    return ref


def _looks_like_reference(ref: str) -> bool:
    ref = _normalize_text(ref)
    if not re.search(r"\[[A-Z](?:/[A-Z]+)?\]", ref):
        return False
    if not (re.search(r"20\d{2}|19\d{2}", ref) or "[J/OL]" in ref.upper() or "HTTP" in ref.upper()):
        return False
    if not re.search(r"[\u4e00-\u9fff]{2,}", ref):
        return False
    if len(ref) > 520:
        return False
    if any(x in ref for x in ["网络首发:在编辑部工作流程", "出版确认:", "录用定稿指内容"]):
        return False
    return bool(re.search(r".+?\..+?\[[A-Z]+(?:/[A-Z]+)?\]\..+", ref))


def extract_citation_format(text: str) -> List[str]:
    refs: List[str] = []
    if not text:
        return refs

    front = _front_text(text, max_pages=3)
    joined = _normalize_text(front)
    joined = re.sub(r"\s+", " ", joined)

    for m in re.finditer(r"引用(?:本文|格式)\s*[:：]\s*", joined):
        after = joined[m.end():m.end() + 1400]

        online = re.search(r".+?\[J/OL\]\s*[.．]?.{0,180}?https?://[A-Za-z0-9._~:/?#\[\]@!$&'()*+,;=%-]+", after, flags=re.I)
        if online:
            cand = _clean_reference(online.group(0))
            if _looks_like_reference(cand):
                refs.append(cand)
                continue

        bib_end = re.search(
            r"\[[A-Z](?:/[A-Z]+)?\]\s*[.．]\s*.{0,220}?"
            r"(?:20\d{2}|19\d{2})\s*[,，]\s*.{0,160}?"
            r"\d+\s*[-–—－]\s*\d+(?:\s*[,，]\s*\d+)?",
            after,
            flags=re.I,
        )
        if bib_end:
            cand = after[:bib_end.end()]
            cand = re.split(r"\s*[（(]\s*(?:Citation\s*[:：])?[A-Z][A-Za-z]", cand)[0]
            cand = _clean_reference(cand)
            if _looks_like_reference(cand):
                refs.append(cand)
                continue

    lines = [_normalize_line(x) for x in front.splitlines()]
    stop_words = ["网络首发", "出版确认", "摘 要", "摘要", "ABSTRACT", "关键词", "KEY WORDS", "收稿日期"]
    for i, line in enumerate(lines):
        if "引用格式" not in line and "引用本文" not in line:
            continue
        chunks: List[str] = []
        m = re.search(r"引用(?:本文|格式)\s*[:：]\s*(.*)$", line)
        if m and m.group(1).strip():
            chunks.append(m.group(1).strip())
        for nxt in lines[i + 1:i + 10]:
            nxt = nxt.strip()
            if not nxt or any(w in nxt for w in stop_words):
                break
            if re.match(r"^[（(]\s*(Citation\s*[:：])?[A-Z]", nxt):
                break
            chunks.append(nxt)
            cand_now = _clean_reference(" ".join(chunks))
            if _looks_like_reference(cand_now):
                break
        cand = _clean_reference(" ".join(chunks))
        if _looks_like_reference(cand):
            refs.append(cand)

    # Group possible duplicates by author-title-type and keep the shortest
    # clean candidate. This removes variants that still carry an English
    # parenthesized citation tail.
    best_by_key: Dict[str, str] = {}
    for r in refs:
        r = _clean_reference(r)
        if not r or "Citation:" in r or "Citation：" in r:
            continue
        r = _strip_english_citation_block(r)
        mkey = re.match(r"^(?P<head>.+?\..+?\[[A-Z](?:/[A-Z]+)?\])", r)
        key = re.sub(r"\s+", "", (mkey.group("head") if mkey else r[:160]))
        old = best_by_key.get(key)
        if old is None:
            best_by_key[key] = r
        elif "[J/OL]" in r.upper() and URL_ASCII_RE.search(r) and not URL_ASCII_RE.search(old):
            best_by_key[key] = r
        elif not ("[J/OL]" in old.upper() and URL_ASCII_RE.search(old)) and len(r) < len(old):
            best_by_key[key] = r
    # Prefer online-first references with a protected URL over later placeholder
    # formal references such as "70(X): 00-00" for the same article.
    grouped: Dict[str, str] = {}
    def _article_title_key(ref_line: str) -> str:
        head = re.sub(r"\[[A-Z](?:/[A-Z]+)?\].*$", "", ref_line)
        parts = [x.strip() for x in head.split(".") if x.strip()]
        if len(parts) >= 2:
            return re.sub(r"\s+", "", parts[-1])
        return re.sub(r"\s+", "", head)

    for r in best_by_key.values():
        art_key = _article_title_key(r)
        old = grouped.get(art_key)
        if old is None:
            grouped[art_key] = r
            continue
        r_online = "[J/OL]" in r.upper() and URL_ASCII_RE.search(r)
        old_online = "[J/OL]" in old.upper() and URL_ASCII_RE.search(old)
        r_placeholder = bool(re.search(r"\b(?:XX|X|00)\b|00\s*[-–—－]\s*00", r, flags=re.I))
        old_placeholder = bool(re.search(r"\b(?:XX|X|00)\b|00\s*[-–—－]\s*00", old, flags=re.I))
        if r_online and not old_online:
            grouped[art_key] = r
        elif r_online == old_online and old_placeholder and not r_placeholder:
            grouped[art_key] = r
        elif r_online == old_online and r_placeholder == old_placeholder and len(r) < len(old):
            grouped[art_key] = r
    return list(grouped.values())


def _clean_english_title(title: str) -> str:
    title = _nfkc(title).strip()
    title = title.replace("：", ":")
    title = re.sub(r"\s+", " ", title)
    title = title.strip(" .;，,。\"'“”‘’`")
    title = re.sub(r"^(Title|English Title|英文题名|英文标题)\s*[:：]\s*", "", title, flags=re.I)
    title = re.sub(r"\s+([:;,.])", r"\1", title)
    title = re.sub(r"([,:;])(?=\S)", r"\1 ", title)
    title = re.sub(r"\s+", " ", title).strip()
    return title.rstrip(".")


def _repair_english_spacing(s: str) -> str:
    s = _nfkc(s or "")
    s = s.replace("⁃", "-").replace("‐", "-").replace("‑", "-")
    s = re.sub(r"-\s+", "", s)  # repair line-break hyphenation in PDF text
    s = re.sub(r"\s+", " ", s).strip()

    # Some JLSC PDFs embed English titles as nearly unspaced glyph streams,
    # e.g. "TheLogicalStartingPoint...SystemofChineseLibraryScience".
    if len(s) > 25:
        s = re.sub(r"(?<=[a-z])(?=[A-Z])", " ", s)
        s = re.sub(r"\bThe(?=[A-Z])", "The ", s)
        s = re.sub(r"\bthe(?=[A-Z])", "the ", s)
        s = re.sub(r"\bof(?=the\b)", "of ", s, flags=re.I)
        s = re.sub(r"\bof\s*the", "of the", s, flags=re.I)
        s = re.sub(r"(?<=[a-z])ofthe(?=\b|[A-Z])", " of the", s)
        s = re.sub(r"(?<=[a-z])of(?=[A-Z])", " of ", s)
        s = re.sub(r"\band(?=[A-Z])", "and ", s)
        s = re.sub(r"\bfor(?=[A-Z])", "for ", s)
        s = re.sub(r"\bin(?=[A-Z])", "in ", s)
        s = re.sub(r"\bSystemof", "System of", s)
        s = re.sub(r"\bLibraryScience", "Library Science", s)
        s = re.sub(r"\bChineseLibrary", "Chinese Library", s)
        s = re.sub(r"\bDevelopmentApproach", "Development Approach", s)
        s = re.sub(r"\s+", " ", s).strip()
    return s


def _mostly_english(line: str) -> bool:
    line = _repair_english_spacing(line).strip()
    if not line:
        return False
    letters = sum(ch.isalpha() and ord(ch) < 128 for ch in line)
    cjk = sum("\u4e00" <= ch <= "\u9fff" for ch in line)
    digits = sum(ch.isdigit() for ch in line)
    return letters >= 12 and letters > cjk * 3 and letters > digits


def _looks_like_english_author_or_affiliation(line: str) -> bool:
    raw_line = _nfkc(line or "").strip()
    compact_raw = re.sub(r"\s+", "", raw_line)
    # Glued author lines in PDF text, e.g. "KEPing,ZHANGYuzhen".
    if "," in compact_raw and re.fullmatch(r"[A-Z][A-Za-z]+(?:,[A-Z][A-Za-z]+){1,12}\*?", compact_raw):
        return True

    line = _repair_english_spacing(line or "")
    low = line.lower()
    if any(x in low for x in ["school of", "university", "institute", "academy", "college", "china)", "orcid", "email"]):
        return True
    if re.match(r"^\d+\s*[\(（]?[A-Z]", line):
        return True
    raw = line.replace("&", " ").replace("＆", " ")
    tokens = [t.strip(",.;:()（）*0123456789") for t in raw.split() if t.strip(",.;:()（）*0123456789")]
    if not tokens:
        return False
    has_list_punct = ("," in line or "&" in line or "＆" in line)
    uppercase_surnames = sum(1 for t in tokens if re.match(r"^[A-Z]{2,}$", t))
    titlecase_names = sum(1 for t in tokens if re.match(r"^[A-Z][a-z]+$", t) or re.match(r"^[A-Z][A-Za-z]+[0-9]?$", t))
    # English author lines in these PDFs usually contain an uppercase surname
    # (ZHANG Xiaolin) or a comma-separated author list. Plain title-case noun
    # phrases such as "Gaussian Discrete Embedding" must remain eligible titles.
    if uppercase_surnames >= 1 and titlecase_names >= 1 and not re.search(r"\b(of|the|in|and|for|from|under|based|with|on|by|to|toward|towards)\b", low):
        return True
    if has_list_punct and titlecase_names >= 2 and not re.search(r"\b(of|the|in|and|for|from|under|based|with|on|by|to|toward|towards)\b", low):
        return True
    return False


def _bad_english_title_line(line: str) -> bool:
    line = _repair_english_spacing(line)
    u = line.upper().strip()
    bad = [
        "ABSTRACT", "KEY WORDS", "KEYWORDS", "DOI", "ISSN", "CN ", "HTTP", "HTTPS",
        "EMAIL", "E-MAIL", "ORCID", "CORRESPONDENCE", "FIG.", "FIGURE", "TABLE", "VOL.", "NO.", "PAGE", "PAGES",
        "AUTHOR", "RECEIVED", "REVISED", "FOUNDATION", "FUNDAMENTAL RESEARCH",
    ]
    if any(b in u for b in bad):
        return True
    if _looks_like_english_author_or_affiliation(line):
        return True
    low = re.sub(r"\s+", " ", line.lower()).strip(" .")
    if low in COMMON_JOURNAL_EN_CN:
        return True
    if low.startswith("data analysis and knowledge discovery") and len(low.split()) <= 6:
        return True
    if low.startswith("journal of library science in china") and len(low.split()) <= 7:
        return True
    if low.startswith("library and information service") and len(low.split()) <= 6:
        return True
    if re.search(r"\[\s*[JMC](?:/OL)?\s*\]", line, flags=re.I):
        return True
    if re.search(r"20\d{2}\s*[,，]\s*\d+\s*[\(（]\d+[\)）]", line):
        return True

    tokens = [t.strip(",.;:()（）") for t in line.replace("＆", "&").split() if t.strip()]
    if len(tokens) >= 3 and len(line) < 140:
        upper_surnames = sum(1 for t in tokens if re.match(r"^[A-Z]{2,}$", t))
        titlecase_names = sum(1 for t in tokens if re.match(r"^[A-Z][a-z]+(?:-[A-Z][a-z]+)?$", t))
        if upper_surnames >= 1 and titlecase_names >= 1:
            lower_line = line.lower()
            if ":" not in line and not re.search(r"\b(of|the|in|and|for|from|under|based|with|on|by|to)\b", lower_line):
                return True
        capital_like = sum(1 for t in tokens if re.match(r"^[A-Z][A-Za-z\-]+$", t))
        # Do not reject plain title-case noun phrases here; author-like
        # cases are handled by _looks_like_english_author_or_affiliation().
    return False


def _valid_english_title(title: str) -> bool:
    title = _clean_english_title(_repair_english_spacing(title))
    # Never accept mixed Chinese/English body fragments as an English title.
    if re.search(r"[\u4e00-\u9fff、，。；；：：《》【】]", title):
        return False
    words = title.split()
    if not (4 <= len(words) <= 42):
        return False
    if _bad_english_title_line(title):
        return False
    if re.match(r"^\d+(\.\d+)?\s+", title):
        return False
    if re.search(r"/\s*(Introduction|Methods|Results|Discussion|Analysis)$", title, re.I):
        return False
    return True


def extract_english_title_from_citation(text: str) -> str:
    if not text:
        return ""
    front = _front_text(text, max_pages=3)
    t = _normalize_text(front)
    t = re.sub(r"\s+", " ", t)

    candidates: List[str] = []
    for m in re.finditer(r"Citation\s*[:：]\s*(?P<eng>[A-Z].{25,900}?\[\s*J(?:/OL)?\s*\].{0,260})", t, flags=re.I):
        candidates.append(m.group("eng"))
    for m in re.finditer(r"[（(]\s*(?P<eng>[A-Z].{25,900}?\[\s*J(?:/OL)?\s*\].{0,260})", t, flags=re.I):
        candidates.append(m.group("eng"))
    # Preserved production heuristic.
    # volume parentheses such as 2026, 10(3): 1-13.
    for m in re.finditer(r"(?P<eng>[A-Z][A-Za-z ,.'\-]+?\.\s+[A-Z][^.]{10,500}?\[\s*J(?:/OL)?\s*\]\.\s+[A-Z][A-Za-z &:.(),0-9;\-]+)", t, flags=re.I):
        candidates.append(m.group("eng"))

    for eng in candidates:
        jm = re.search(r"(?P<before>.+?)\s*\[\s*J(?:/OL)?\s*\]", eng, flags=re.I)
        if not jm:
            continue
        before = re.sub(r"^Citation\s*[:：]\s*", "", jm.group("before").strip(), flags=re.I)
        parts = [x.strip() for x in re.split(r"\.\s+", before) if x.strip()]
        cand = parts[-1] if len(parts) >= 2 else before
        cand = _clean_english_title(_repair_english_spacing(cand))
        if _valid_english_title(cand):
            return cand
    return ""


def extract_english_title_from_frontmatter(text: str) -> str:
    front = _front_text(text, max_pages=3)
    lines = [_normalize_line(x) for x in front.splitlines() if _normalize_line(x)]
    if not lines:
        return ""

    idx = next((i for i, line in enumerate(lines) if "ABSTRACT" in _nfkc(line).upper()), -1)
    if idx < 0:
        return ""

    collected: List[str] = []
    for j in range(idx - 1, max(-1, idx - 18), -1):
        prev = lines[j].strip()
        if not prev:
            continue
        if _looks_like_english_author_or_affiliation(prev):
            if collected:
                break
            continue
        if _bad_english_title_line(prev):
            if collected:
                break
            continue
        if _mostly_english(prev) and 8 <= len(prev) <= 240:
            collected.insert(0, prev)
            continue
        if collected:
            break
    if collected:
        title = _clean_english_title(_repair_english_spacing(" ".join(collected)))
        if _valid_english_title(title):
            return title
    return ""


def extract_english_title_from_top_block(text: str) -> str:
    front = _front_text(text, max_pages=3)
    lines = [_normalize_line(x) for x in front.splitlines() if _normalize_line(x)]
    groups: List[str] = []
    current: List[str] = []
    for line in lines[:120]:
        if "ABSTRACT" in _nfkc(line).upper() or re.match(r"^\s*(摘\s*要|摘要)\b", line):
            if current:
                groups.append(" ".join(current)); current = []
            break
        if any(k in line for k in ["网络首发论文", "引用格式", "题目:", "作者:", "网络首发日期"]):
            if current:
                groups.append(" ".join(current)); current = []
            continue
        if _looks_like_english_author_or_affiliation(line) or _bad_english_title_line(line):
            if current:
                groups.append(" ".join(current)); current = []
            continue
        if any(k in line for k in ["School of", "University", "Email", "ORCID", "Corresponding", "摘要", "关键词"]):
            if current:
                groups.append(" ".join(current)); current = []
            continue
        if _mostly_english(line) and 10 <= len(line) <= 220:
            current.append(line)
        else:
            if current:
                groups.append(" ".join(current)); current = []
    if current:
        groups.append(" ".join(current))

    for g in groups:
        cand = _clean_english_title(_repair_english_spacing(g))
        if _valid_english_title(cand):
            return cand
    return ""


def extract_english_title(text: str) -> str:
    by_citation = extract_english_title_from_citation(text)
    if by_citation:
        return by_citation
    by_front = extract_english_title_from_frontmatter(text)
    if by_front:
        return by_front
    return extract_english_title_from_top_block(text)


def _clean_author_line(line: str) -> str:
    line = _normalize_line(line)
    line = re.split(r"(?:\d+\s*[）)]\s*[\u4e00-\u9fff]{4,}|收稿日期|基金项目|作者简介|通讯作者|E-mail|Email|ORCID)", line, maxsplit=1)[0]
    line = line.replace("■", " ").replace("▋", " ").replace("*", " ").replace("＊", " ")
    line = re.sub(r"\d+\s*[)）]?", " ", line)
    line = re.sub(r"[A-Za-z0-9@._:/\\-]+", " ", line)
    line = re.sub(r"[，,、;；&＆]\s*", " ", line)
    raw_tokens = [re.sub(r"[^\u4e00-\u9fff]", "", x) for x in re.split(r"\s+", line) if x.strip()]
    raw_tokens = [x for x in raw_tokens if x and x not in {"摘要", "关键词", "分类号", "基金", "作者", "通讯作者"}]

    tokens: List[str] = []
    i = 0
    while i < len(raw_tokens):
        tok = raw_tokens[i]
        if len(tok) == 1 and i + 1 < len(raw_tokens) and len(raw_tokens[i + 1]) == 1:
            tokens.append(tok + raw_tokens[i + 1])
            i += 2
        else:
            tokens.append(tok)
            i += 1

    names = []
    for p0 in tokens:
        if 2 <= len(p0) <= 4 and p0 not in {"中国", "北京", "上海", "天津", "研究", "大学", "学院", "杂志社", "出版社"}:
            names.append(p0)
    return ",".join(names[:10])


def _valid_title_line(line: str) -> bool:
    line = _normalize_line(line)
    compact = re.sub(r"\s+", "", line)
    if not re.search(r"[\u4e00-\u9fff]", line):
        return False
    if any(x in line for x in ["ISSN", "DOI", "http", "收稿日期", "基金项目", "作者简介", "关键词", "分类号", "摘 要", "摘要", "网络首发", "引用格式", "引用本文", "Vol.", "No."]):
        return False
    if re.search(r"^(总第.*卷|第.*期)$", compact):
        return False
    if re.match(r"^20\d{2}\s*年.*第.*期", line):
        return False
    if re.search(r"(中国科技期刊研究|图书情报工作|数据分析与知识发现|中国图书馆学报)\s*[,，]?(?:20\d{2}|XXXX|XX|第|总|Vol\.)", line):
        return False
    if line in {"图书情报工作", "数据分析与知识发现", "中国图书馆学报", "中国科技期刊研究"}:
        return False
    if "■" in line or "▋" in line:
        return False
    if re.search(r"\d{6}|大学|学院|研究所|北京市|上海市|武汉|长春|天津", line) and len(line) > 30:
        return False
    return 2 <= len(compact) <= 90


def _chinese_numeral_to_int(s: str) -> int:
    s = _nfkc(s or "").strip()
    if s.isdigit():
        return int(s)
    trans = {"〇": "0", "零": "0", "一": "1", "二": "2", "两": "2", "三": "3", "四": "4", "五": "5", "六": "6", "七": "7", "八": "8", "九": "9"}
    digits = "".join(trans.get(ch, "") for ch in s)
    return int(digits) if digits else 0


def _extract_pdf_page_range(lines: List[str]) -> str:
    pages: List[int] = []
    three_digit_pages: List[int] = []
    joined_lines = "\n".join(lines[:120])

    m = re.search(r"[,，:：]\s*(?P<pages>\d+\s*[-–—－]\s*\d+)\s+\d+\b", joined_lines)
    if m:
        return m.group("pages").replace(" ", "").replace("–", "-").replace("—", "-").replace("－", "-")

    for line in lines:
        line_n = _normalize_line(line)
        if re.fullmatch(r"0\d{2}", line_n):
            val = int(line_n)
            if 1 <= val <= 999:
                three_digit_pages.append(val)
                continue
        if re.fullmatch(r"\d{1,3}", line_n):
            val = int(line_n)
            if 1 <= val <= 999:
                pages.append(val)
                continue
        m2 = re.match(r"^\s*(\d{2}\s+\d)\b", line_n)
        if m2:
            val = int(re.sub(r"\D+", "", m2.group(1)))
            if 1 <= val <= 999:
                three_digit_pages.append(val)
    candidates = three_digit_pages if len(set(three_digit_pages)) >= 2 else pages
    if candidates:
        return f"{min(candidates)}-{max(candidates)}" if min(candidates) != max(candidates) else str(candidates[0])
    return ""


def _clean_chinese_title(title: str) -> str:
    title = _normalize_line(title)
    title = re.sub(r"\s+", "", title)
    title = title.replace("：", ":")
    return title.strip(" .。")


def _extract_journal_year_volume_issue(joined: str, journal_names: List[str] | None = None) -> Tuple[str, str, str, str]:
    joined = _normalize_text(joined)
    journal = year = volume = issue = ""

    m = re.search(r"(?P<journal>[\u4e00-\u9fff]{2,30})\s*[,，]\s*(?P<year>20\d{2}|XXXX|XX)\s*[,，]\s*(?P<vol>\d+|XX)\s*[\(（](?P<issue>\d+|XX)[\)）]", joined)
    if m:
        journal = m.group("journal").replace("《", "").replace("》", "")
        year = "" if m.group("year") in {"XXXX", "XX"} else m.group("year")
        volume = "" if m.group("vol") == "XX" else m.group("vol")
        issue = "" if m.group("issue") == "XX" else m.group("issue")
        return journal, year, volume, issue

    m2 = re.search(r"Vol\.\s*(?P<vol>\d+)\s*[.。]?\s*No\.\s*(?P<no>\d+)", joined, flags=re.I)
    if m2:
        volume, issue = m2.group("vol"), m2.group("no")
    if not volume:
        vm = re.search(r"总第(?P<vol>[一二三四五六七八九〇零\d]+)卷", joined)
        if vm:
            volume = str(_chinese_numeral_to_int(vm.group("vol")) or "")
    if not issue:
        im = re.search(r"第(?P<issue>[一二三四五六七八九〇零\d]+)期", joined)
        if im:
            issue = str(_chinese_numeral_to_int(im.group("issue")) or "")

    low = re.sub(r"\s+", " ", joined.lower())
    compact_low = re.sub(r"\s+", "", low)
    for en, cn in COMMON_JOURNAL_EN_CN.items():
        if en in low or re.sub(r"\s+", "", en) in compact_low:
            journal = cn
            break
    if not journal and journal_names:
        for name in journal_names:
            if name and name in joined:
                journal = name
                break

    y = re.search(r"(20\d{2})\s*年", joined)
    if y:
        year = y.group(1)
    else:
        y2 = re.search(r"\b(20\d{2})\s+(?:\d{1,2}\s+)?(?:January|February|March|April|May|June|July|August|September|October|November|December)\b", joined, flags=re.I)
        if y2:
            year = y2.group(1)
    return journal, year, volume, issue


def _is_abstract_start(lines: List[str], i: int) -> bool:
    line = _normalize_line(lines[i])
    if re.match(r"^\s*(摘\s*要|摘要)\b", line):
        return True
    if line == "摘" and i + 1 < len(lines) and _normalize_line(lines[i + 1]) == "要":
        return True
    return False


def _looks_like_author_candidate_line(line: str) -> bool:
    line_n = _normalize_line(line)
    compact = re.sub(r"\s+", "", line_n)
    if not re.search(r"[\u4e00-\u9fff]", line_n):
        return False
    if re.search(r"^(总第.*卷|第.*期|20\d{2}年|XXXX年|Vol\.|DOI|ISSN)", compact, flags=re.I):
        return False
    if any(x in compact for x in ["与", "的", "研究", "构建", "背景", "路径", "选择", "机遇", "挑战"]):
        return False
    if any(x in line_n for x in ["作者简介", "通信作者", "基金项目", "DOI", "关键词", "分类号", "收稿日期"]):
        return False
    if re.search(r"大学|学院|研究所|北京市|上海市|武汉|天津|长春|邮编|\d{6}", line_n):
        return False
    cand = _clean_author_line(line_n)
    if not cand:
        return False
    names = cand.split(",")
    return 1 <= len(names) <= 8 and all(2 <= len(n) <= 4 for n in names)


def _extract_title_author_from_front(lines: List[str]) -> Tuple[str, str]:
    abstract_idx = next((i for i in range(min(180, len(lines))) if _is_abstract_start(lines, i)), -1)
    limit = abstract_idx if abstract_idx > 0 else min(90, len(lines))
    win = lines[:limit]

    author_idx = -1
    author_line = ""
    for i, line in enumerate(win):
        if "■" in line or "▋" in line:
            combo = [line]
            for nxt in win[i + 1:i + 6]:
                if re.search(r"\d+\s*[)）].*(大学|学院|研究所|北京市|上海市|武汉|天津|长春)", nxt):
                    break
                if _normalize_line(nxt) in {"摘", "要"} or re.match(r"^\s*(摘\s*要|摘要|ABSTRACT)", _normalize_line(nxt), re.I):
                    break
                combo.append(nxt)
            cand = _clean_author_line(" ".join(combo))
            if cand:
                author_idx = i
                author_line = cand
                break

    if author_idx < 0:
        for i, line in enumerate(win):
            if not _looks_like_author_candidate_line(line):
                continue
            before_valid = any(_valid_title_line(x) for x in win[max(0, i - 5):i])
            if before_valid:
                combo = [line]
                for k in range(i + 1, min(len(win), i + 8)):
                    nxt = win[k]
                    if _is_abstract_start(win, k):
                        break
                    if _looks_like_author_candidate_line(nxt):
                        combo.append(nxt)
                        continue
                    break
                author_idx = i
                author_line = _clean_author_line(" ".join(combo))
                break

    title = ""
    if author_idx > 0:
        title_lines: List[str] = []
        for j in range(author_idx - 1, max(-1, author_idx - 8), -1):
            cand = win[j]
            compact = re.sub(r"\s+", "", _normalize_line(cand))
            if _valid_title_line(cand) or (title_lines and 1 <= len(compact) <= 8 and re.search(r"[\u4e00-\u9fff]", compact)):
                title_lines.insert(0, cand)
            elif title_lines:
                break
        # Remove header-like lines that may be directly above the real title.
        while title_lines and not _valid_title_line(title_lines[0]):
            title_lines.pop(0)
        title = "".join(title_lines)

    if not title:
        valid = [l for l in win if _valid_title_line(l)]
        if valid:
            title = max(valid, key=lambda x: len(re.sub(r"\s+", "", x)))

    return _clean_chinese_title(title), author_line

def extract_reference_from_metadata(text: str, journal_names: List[str] | None = None) -> str:
    raw_lines = [_normalize_line(x) for x in (text or "").splitlines()]
    lines = [x for x in raw_lines if x and not x.startswith("--- PDF_PAGE_")]
    if not lines:
        return ""

    front = _front_text(text, max_pages=3)
    front_lines = [_normalize_line(x) for x in front.splitlines()]
    front_lines = [x for x in front_lines if x and not x.startswith("--- PDF_PAGE_")]

    joined_front = "\n".join(front_lines[:240])
    joined_all = "\n".join(lines)

    journal, year, volume, issue = _extract_journal_year_volume_issue(joined_front, journal_names=journal_names)
    if not journal or not year or not volume or not issue:
        j2, y2, v2, i2 = _extract_journal_year_volume_issue(joined_all[:12000], journal_names=journal_names)
        journal = journal or j2
        year = year or y2
        volume = volume or v2
        issue = issue or i2

    pages = _extract_pdf_page_range(lines)
    if not pages:
        for pat in [r"起止页码\s*[:：]\s*(?P<pages>\d+\s*[-–—－]\s*\d+)", r"Pages\s*[:：]\s*(?P<pages>\d+\s*[-–—－]\s*\d+)"]:
            mm = re.search(pat, joined_all)
            if mm:
                pages = mm.group("pages").replace(" ", "").replace("–", "-").replace("—", "-").replace("－", "-")
                break

    title, authors = _extract_title_author_from_front(front_lines)
    if not (title and authors):
        title2, authors2 = _extract_title_author_from_front(lines[:180])
        title = title or title2
        authors = authors or authors2

    online_url = ""
    um = re.search(r"网络首发(?:时间|地址)?[^\n]{0,120}(https?://[A-Za-z0-9._~:/?#\[\]@!$&'()*+,;=%-]+)", joined_all)
    if not um:
        um = URL_ASCII_RE.search(joined_all)
    if um:
        online_url = um.group(1) if um.lastindex else um.group(0)

    if not (authors and title and journal):
        return ""

    if online_url and not year:
        return _clean_reference(f"{authors}. {title}[J/OL]. {journal}. {online_url}.")
    if year and volume and issue and pages:
        return _clean_reference(f"{authors}. {title}[J]. {journal}, {year}, {volume}({issue}): {pages}.")
    if year and pages:
        return _clean_reference(f"{authors}. {title}[J]. {journal}, {year}: {pages}.")
    if year:
        return _clean_reference(f"{authors}. {title}[J]. {journal}, {year}.")
    if pages:
        return _clean_reference(f"{authors}. {title}[J]. {journal}: {pages}.")
    return _clean_reference(f"{authors}. {title}[J]. {journal}.")


def _journal_names_hit_from_kb(text: str, journal_kb: List[Dict[str, Any]] | None = None) -> List[str]:
    hits: List[str] = []
    if not text:
        return hits
    front = _front_text(text, max_pages=3)
    front_norm = re.sub(r"\s+", " ", _normalize_text(front)).lower()
    compact = re.sub(r"\s+", "", front_norm)

    for en, cn in COMMON_JOURNAL_EN_CN.items():
        if en in front_norm or re.sub(r"\s+", "", en) in compact:
            if cn not in hits:
                hits.append(cn)

    for x in (journal_kb or []):
        cn = str(x.get("name_cn", "")).strip()
        en = str(x.get("name_en", "")).strip()
        aliases = x.get("alias_en") or []
        if isinstance(aliases, str):
            aliases = [aliases]
        hit = bool(cn and cn in front)
        if not hit and en:
            en_low = en.lower()
            hit = en_low in front_norm or re.sub(r"\s+", "", en_low) in compact
        if not hit:
            for a in aliases:
                aa = str(a).strip().lower()
                if aa and (aa in front_norm or re.sub(r"\s+", "", aa) in compact):
                    hit = True
                    break
        if hit and cn and cn not in hits:
            hits.append(cn)
    return hits


def pdf_bytes_to_refs_and_title_entries(raw: bytes, journal_kb: List[Dict[str, Any]] | None = None) -> Dict[str, Any]:
    text, warning = extract_pdf_text(raw)
    journal_names = _journal_names_hit_from_kb(text, journal_kb=journal_kb) if text else []

    refs = extract_citation_format(text) if text else []
    extraction_mode = "citation_format" if refs else ""

    if not refs and text:
        fallback = extract_reference_from_metadata(text, journal_names=journal_names)
        if fallback:
            refs = [fallback]
            extraction_mode = "metadata_fallback"

    title_en = extract_english_title(text) if text else ""
    title_source = "pdf_citation_or_frontmatter" if title_en else ""

    if text and not refs and not warning:
        warning = (
            "未能从 PDF 中可靠提取完整中文引用。"
            "当前版本已尝试“引用格式/引用本文”、CNKI 网络首发首页、正式出版首页元数据、"
            "页眉页码和中英文题名区解析；如 PDF 为扫描件或版式特殊，请手动粘贴参考文献。"
        )

    return {
        "text": text,
        "warning": warning,
        "references": refs,
        "title_en": title_en,
        "title_source": title_source,
        "extraction_mode": extraction_mode,
        "title_entries": [],
    }


# ---------------------------------------------------------------------------
# v3.8.8.5.5 universal PDF metadata overrides
# ---------------------------------------------------------------------------
# The functions below intentionally override earlier heuristic functions. They
# make the PDF fallback less journal-specific by using structural zones
# (header/title/author/affiliation/abstract/English-title) instead of a small
# list of fixed journal layouts.

_COMMON_CN_SURNAMES = set("赵钱孙李周吴郑王冯陈褚卫蒋沈韩杨朱秦尤许何吕施张孔曹严华金魏陶姜戚谢邹喻柏水窦章云苏潘葛奚范彭郎鲁韦昌马苗凤花方俞任袁柳鲍史唐费廉岑薛雷贺倪汤滕殷罗毕郝邬安常乐于时傅皮卞齐康伍余元卜顾孟平黄和穆萧尹姚邵湛汪祁毛禹狄米贝明臧计伏成戴谈宋庞熊纪舒屈项祝董梁杜阮蓝闵席季麻强贾路娄危江童颜郭梅盛林刁钟徐邱骆高夏蔡田胡凌霍虞万支柯昝管卢莫经房裘缪干解应宗丁宣邓郁单杭洪包诸左石崔吉龚程邢滑裴陆荣翁荀羊於惠甄曲家封芮羿储靳汲邴糜松井段富巫乌焦巴弓牧隗山谷车侯宓蓬全郗班仰秋仲伊宫宁仇栾暴甘斜厉戎祖武符刘景詹束龙叶幸司韶郜黎蓟薄印宿白怀蒲台从鄂索咸籍赖卓蔺屠蒙池乔阳胥能苍双闻莘党翟谭贡劳逄姬申扶堵冉宰郦雍璩桑桂濮牛寿通边扈燕冀郏浦尚农温别庄晏柴瞿阎充慕连茹习宦艾鱼容向古易慎戈廖庾终暨居衡步都耿满弘匡国文寇广禄阙东欧殳沃利蔚越夔隆师巩厍聂晁勾敖融冷訾辛阚那简饶空曾毋沙乜养鞠须丰巢关蒯相查后荆红游竺权逯盖益桓公")
_COMPOUND_CN_SURNAMES = ("欧阳", "司马", "上官", "诸葛", "东方", "皇甫", "尉迟", "公孙", "令狐", "司徒", "司空", "夏侯", "澹台", "慕容", "长孙", "宇文", "司寇", "南宫", "轩辕", "仲孙", "闻人")
_NON_AUTHOR_WORDS = {
    "现代情报", "情报学报", "情报资料工作", "图书馆杂志", "中国科技期刊研究", "图书情报工作", "数据分析与知识发现",
    "中国图书馆学报", "探索", "法学", "摘要", "摘", "要", "关键词", "分类号", "中图分类号", "文献标识码", "文章编号",
    "理论探讨", "研究论文", "引言", "专题", "专栏", "河南", "湖南", "北京", "上海", "天津", "武汉", "长春", "哈尔滨",
}
_AFFILIATION_WORDS = ("大学", "学院", "研究所", "研究院", "实验室", "中心", "医院", "杂志社", "出版社", "公司", "北京市", "上海市", "天津市", "重庆市", "省", "市", "邮编", "School", "University", "Institute", "College", "Academy", "Laboratory", "Center", "Centre")


def _has_cn_surname(name: str) -> bool:
    name = re.sub(r"[^\u4e00-\u9fff]", "", _nfkc(name or ""))
    if not name:
        return False
    return name.startswith(_COMPOUND_CN_SURNAMES) or name[0] in _COMMON_CN_SURNAMES


def _is_possible_cn_person_name(name: str) -> bool:
    name = re.sub(r"[^\u4e00-\u9fff]", "", _nfkc(name or ""))
    if not (2 <= len(name) <= 4):
        return False
    if name in _NON_AUTHOR_WORDS:
        return False
    if any(w in name for w in ("情报", "期刊", "杂志", "图书", "数据", "研究", "理论", "工作", "现代", "信息", "管理", "资源", "科学", "技术", "文章", "分类", "关键词", "摘要")):
        return False
    return _has_cn_surname(name)


def _split_long_cn_name_token(token: str) -> List[str]:
    token = re.sub(r"[^\u4e00-\u9fff]", "", token or "")
    if not token:
        return []
    if _is_possible_cn_person_name(token):
        return [token]
    # Greedy split for glued author strings. Prefer 3-char names, fall back to
    # 2-char names when the next character is not a common surname.
    out: List[str] = []
    i = 0
    while i < len(token):
        matched = ""
        for n in (4, 3, 2):
            part = token[i:i+n]
            if _is_possible_cn_person_name(part):
                # Avoid consuming the first char of the next surname for common
                # 2-char names unless this is the only possible segment.
                if n == 3 and i + n < len(token) and token[i+n] in _COMMON_CN_SURNAMES:
                    matched = part
                    break
                matched = part
                break
        if matched:
            out.append(matched)
            i += len(matched)
        else:
            i += 1
    return out


def _cn_name_tokens_from_line(line: str) -> Tuple[List[str], bool]:
    """Extract person-name candidates from one line.

    Returns (names, should_stop_after_line). If an affiliation begins in the
    line, names before the affiliation are kept and the caller should stop.
    """
    line = _normalize_line(line)
    if not line:
        return [], False
    if any(x in line for x in ("作者简介", "通信作者", "基金项目", "收稿日期", "修回日期", "DOI", "关键词", "分类号", "文章编号")):
        return [], False
    stop_after = False
    # Preserved production heuristic.
    aff_pos = None
    for mark in ("（", "(", "［", "["):
        p = line.find(mark)
        if p >= 0 and any(w in line[p:] for w in _AFFILIATION_WORDS):
            aff_pos = p if aff_pos is None else min(aff_pos, p)
    if aff_pos is not None:
        line = line[:aff_pos]
        stop_after = True
    elif any(w in line for w in _AFFILIATION_WORDS) and len(re.sub(r"[^\u4e00-\u9fff]", "", line)) > 4:
        return [], True

    # Remove footnote numbers, e-mails, English text, and separators.
    line = re.sub(r"[A-Za-z@._:/\\-]+", " ", line)
    line = re.sub(r"\d+\s*(?:[,，、]\s*\d+)*", " ", line)
    line = line.replace("*", " ").replace("＊", " ").replace("■", " ").replace("▋", " ")
    parts = [p for p in re.split(r"[\s,，、;；&＆]+", line) if p.strip()]
    tokens: List[str] = []
    for p in parts:
        cjk = re.sub(r"[^\u4e00-\u9fff]", "", p)
        if not cjk or cjk in _NON_AUTHOR_WORDS:
            continue
        if len(cjk) == 1:
            tokens.append(cjk)
        elif len(cjk) <= 4 and _is_possible_cn_person_name(cjk):
            tokens.append(cjk)
        elif len(cjk) > 4:
            tokens.extend(_split_long_cn_name_token(cjk))

    names: List[str] = []
    pending = ""
    for tok in tokens:
        if len(tok) == 1:
            if pending:
                cand = pending + tok
                if _is_possible_cn_person_name(cand):
                    names.append(cand)
                pending = ""
            elif tok in _COMMON_CN_SURNAMES:
                pending = tok
            continue
        if pending:
            cand = pending + tok[:1]
            if _is_possible_cn_person_name(cand):
                names.append(cand)
                rest = tok[1:]
                if _is_possible_cn_person_name(rest):
                    names.append(rest)
                pending = ""
                continue
            pending = ""
        if _is_possible_cn_person_name(tok):
            names.append(tok)
    return names, stop_after


def _extract_cn_person_names_from_lines(lines: List[str], max_lines: int = 16) -> List[str]:
    names: List[str] = []
    for line in lines[:max_lines]:
        line_n = _normalize_line(line)
        if not line_n:
            continue
        if _is_abstract_start([line_n], 0) or "关键词" in line_n:
            break
        line_names, stop = _cn_name_tokens_from_line(line_n)
        for n in line_names:
            if n not in names:
                names.append(n)
        if stop and names:
            break
    return names


def _valid_title_line(line: str) -> bool:
    line = _normalize_line(line)
    compact = re.sub(r"\s+", "", line)
    if not re.search(r"[\u4e00-\u9fff]", line):
        return False
    if not (6 <= len(compact) <= 90):
        return False
    bad_fragments = [
        "ISSN", "CN ", "DOI", "http", "www.", "收稿日期", "修回日期", "基金项目", "作者简介", "通信作者",
        "关键词", "分类号", "中图分类号", "文献标识码", "文章编号", "摘 要", "摘要", "网络首发", "引用格式",
        "引用本文", "Vol.", "No.", "版权所有", "Reproduction", "Corresponding",
    ]
    if any(x in line for x in bad_fragments):
        return False
    if re.fullmatch(r"(第)?\d{1,4}", compact):
        return False
    if re.match(r"^(20\d{2}|XXXX|XX)\s*年", compact) or re.search(r"20\d{2}年\d{1,2}月", compact):
        return False
    if re.search(r"^(第)?[一二三四五六七八九十百千万\d]+卷(第)?[一二三四五六七八九十百千万\d]+期$", compact):
        return False
    if re.search(r"^(总第.*卷|第.*期|Vol\.|No\.)", compact, flags=re.I):
        return False
    if compact in _NON_AUTHOR_WORDS:
        return False
    if len(compact) <= 8 and any(x in compact for x in ("情报", "学报", "期刊", "杂志", "图书馆", "探索", "法学")):
        return False
    if re.search(r"大学|学院|研究所|研究院|实验室|中心|北京市|上海市|武汉|长春|天津|哈尔滨|郑州|南京|苏州|\d{6}", line):
        return False
    if "■" in line or "▋" in line:
        return False
    return True


def _looks_like_author_candidate_line(line: str) -> bool:
    line_n = _normalize_line(line)
    if not re.search(r"[\u4e00-\u9fff]", line_n):
        return False
    if not line_n or line_n in _NON_AUTHOR_WORDS:
        return False
    if _valid_title_line(line_n):
        return False
    names, _ = _cn_name_tokens_from_line(line_n)
    if not names:
        return False
    cjk = re.sub(r"[^\u4e00-\u9fff]", "", line_n)
    # Reject long prose lines where a personal name appears in an author bio.
    if len(cjk) > 18 and not any(sep in line_n for sep in " ，,、;；&＆"):
        return False
    return True


def _extract_title_block_before(win: List[str], author_idx: int) -> str:
    title_lines: List[str] = []
    for j in range(author_idx - 1, max(-1, author_idx - 10), -1):
        cand = win[j]
        compact = re.sub(r"\s+", "", _normalize_line(cand))
        if not compact or compact in {"*", "＊", "·", "·专", "题·", "专", "题"}:
            continue
        if _valid_title_line(cand):
            title_lines.insert(0, cand)
            continue
        # Allow a second line of a split title even if short, but only after
        # a longer title line has already been collected.
        if title_lines and 2 <= len(compact) <= 20 and re.search(r"[\u4e00-\u9fff]", compact):
            if not _looks_like_author_candidate_line(cand) and not any(w in cand for w in _AFFILIATION_WORDS):
                title_lines.insert(0, cand)
                continue
        if title_lines:
            break
    while title_lines and not _valid_title_line(title_lines[0]):
        title_lines.pop(0)
    return _clean_chinese_title("".join(title_lines))


def _extract_title_author_from_front(lines: List[str]) -> Tuple[str, str]:
    lines = [_normalize_line(x) for x in lines if _normalize_line(x)]
    abstract_idx = next((i for i in range(min(220, len(lines))) if _is_abstract_start(lines, i)), -1)
    limit = abstract_idx if abstract_idx > 0 else min(120, len(lines))
    win = lines[:limit]

    candidates: List[Tuple[int, str, List[str]]] = []
    for i, line in enumerate(win):
        names = _extract_cn_person_names_from_lines(win[i:i+14], max_lines=14)
        if not names:
            continue
        # Need at least one plausible title immediately before this author block.
        title = _extract_title_block_before(win, i)
        if not title:
            continue
        # Avoid treating journal/header + date as title/author.
        if title in _NON_AUTHOR_WORDS or re.search(r"20\d{2}年", title):
            continue
        candidates.append((i, title, names))

    if candidates:
        # Prefer the candidate closest to the abstract; it is usually the real
        # title/author block even when the page starts with an introduction.
        i, title, names = max(candidates, key=lambda x: (x[0], len(x[1])))
        return _clean_chinese_title(title), ",".join(names[:12])

    # Fallback: choose the longest valid Chinese title before abstract.
    valid = [(i, l) for i, l in enumerate(win) if _valid_title_line(l)]
    if valid:
        i, t = max(valid, key=lambda x: len(re.sub(r"\s+", "", x[1])))
        names = _extract_cn_person_names_from_lines(win[i+1:i+16], max_lines=15)
        return _clean_chinese_title(t), ",".join(names[:12])
    return "", ""


def _extract_journal_year_volume_issue(joined: str, journal_names: List[str] | None = None) -> Tuple[str, str, str, str]:
    joined = _normalize_text(joined)
    lines = [_normalize_line(x) for x in joined.splitlines() if _normalize_line(x)]
    head = "\n".join(lines[:90])
    journal = year = volume = issue = ""

    # 1) Prefer journal KB hits already detected from the PDF front pages.
    if journal_names:
        journal = journal_names[0]

    # 2) Map English journal names visible in the header to Chinese names.
    low = re.sub(r"\s+", " ", head.lower())
    compact_low = re.sub(r"\s+", "", low)
    for en, cn in COMMON_JOURNAL_EN_CN.items():
        if en in low or re.sub(r"\s+", "", en) in compact_low:
            journal = journal or cn
            break

    # 3) If still unknown, infer a short Chinese journal line around an English
    # journal title or a header line with year/volume information.
    if not journal:
        for i, line in enumerate(lines[:30]):
            compact = re.sub(r"\s+", "", line)
            if re.search(r"20\d{2}年", compact) and len(compact) <= 30:
                cand = re.sub(r"20\d{2}年.*$", "", compact)
                if 2 <= len(cand) <= 12:
                    journal = cand
                    break
            if i + 1 < len(lines) and _mostly_english(lines[i+1]) and len(compact) <= 12:
                if any(x in compact for x in ("学报", "期刊", "情报", "图书", "杂志", "法学", "探索")):
                    journal = compact
                    break

    # 4) Extract year / volume / issue from header, independent of journal.
    ym = re.search(r"(20\d{2})\s*年", head)
    if ym:
        year = ym.group(1)
    else:
        ym = re.search(r"\b(20\d{2})\b", head)
        if ym:
            year = ym.group(1)

    vm = re.search(r"第\s*(?P<vol>\d+)\s*卷", head)
    if vm:
        volume = vm.group("vol")
    else:
        vm = re.search(r"Vol\.\s*(?P<vol>\d+)", head, flags=re.I)
        if vm:
            volume = vm.group("vol")
        else:
            vm = re.search(r"[,，]\s*(?P<vol>\d+)\s*[\(（](?P<issue>\d+)[\)）]\s*[:：]\s*\d+", head)
            if vm:
                volume = vm.group("vol")
                issue = vm.group("issue")

    im = re.search(r"第\s*(?P<issue>\d+)\s*期", head)
    if im:
        issue = im.group("issue")
    elif not issue:
        im = re.search(r"No\.\s*(?P<issue>\d+)", head, flags=re.I)
        if im:
            issue = im.group("issue")

    return journal, year, volume, issue


def _extract_pdf_page_range(lines: List[str]) -> str:
    page_nums: List[int] = []
    joined_lines = "\n".join(lines[:220])

    # Explicit page range in headers, e.g. 45(2): 165-179
    m = re.search(r"[\(（]\d+[\)）]\s*[:：]\s*(?P<pages>\d+\s*[-–—－]\s*\d+)", joined_lines)
    if m:
        return m.group("pages").replace(" ", "").replace("–", "-").replace("—", "-").replace("－", "-")

    # Article-number pattern common in Chinese journals:
    # 1008-0821（2026）04-0011-11 -> start page 11, length 11 => 11-21.
    m = re.search(r"\(?(?:20\d{2})\)?\s*\)?\s*\d{2}\s*[-－]\s*0*(?P<start>\d{1,4})\s*[-－]\s*(?P<count>\d{1,3})", joined_lines)
    if m:
        start = int(m.group("start"))
        count = int(m.group("count"))
        if start > 0 and 1 <= count <= 80:
            end = start + count - 1
            return f"{start}-{end}" if end != start else str(start)

    for line in lines:
        line_n = _normalize_line(line)
        # Footers such as "— 11", "— 12 —", or standalone page numbers.
        m2 = re.fullmatch(r"[—\-–－]*\s*(\d{1,4})\s*[—\-–－]*", line_n)
        if m2:
            val = int(m2.group(1))
            if 1 <= val <= 9999:
                page_nums.append(val)
                continue
        m3 = re.search(r"[—\-–－]\s*(\d{1,4})\s*$", line_n)
        if m3:
            val = int(m3.group(1))
            if 1 <= val <= 9999:
                page_nums.append(val)

    # Remove obvious years/issue numbers if they slipped in.
    page_nums = [p for p in page_nums if p < 1900]
    if len(set(page_nums)) >= 2:
        return f"{min(page_nums)}-{max(page_nums)}"
    if len(set(page_nums)) == 1:
        return str(page_nums[0])
    return ""


def _looks_like_english_author_or_affiliation(line: str) -> bool:
    raw_line = _nfkc(line or "").strip()
    compact_raw = re.sub(r"\s+", "", raw_line)
    if not raw_line:
        return False
    low = raw_line.lower()
    if any(x in low for x in ["school of", "university", "institute", "academy", "college", "china)", "orcid", "email", "corresponding author"]):
        return True
    if re.match(r"^\d+\s*[\(（]?[A-Z]", raw_line):
        return True

    line = _repair_english_spacing(raw_line)
    # Remove affiliation numbers and punctuation used for author footnotes.
    clean = re.sub(r"\d+(?:[,，]\d+)*|\*|＆|&|\band\b", " ", line, flags=re.I)
    words = [w.strip(",.;:()（）") for w in clean.split() if w.strip(",.;:()（）")]
    if not words:
        return False
    if len(words) <= 12:
        titlecase = [bool(re.match(r"^[A-Z][a-zA-Z\-']+$", w)) for w in words]
        small_words = {"of", "the", "in", "and", "for", "from", "under", "based", "with", "on", "by", "to", "toward", "towards", "as"}
        has_connector = any(w.lower() in small_words for w in words)
        # Name lists normally contain title-case tokens and no title connectors.
        if all(titlecase) and not has_connector and len(words) >= 2:
            return True
    if "," in raw_line and re.fullmatch(r"[A-Z][A-Za-z]+(?:\s+[A-Z][A-Za-z]+)?(?:\s*,\s*[A-Z][A-Za-z]+(?:\s+[A-Z][A-Za-z]+)?)*", re.sub(r"\d+|\*", "", raw_line).strip()):
        return True
    return False


# v3.8.8.5.5 patch B: safer abstract and journal/title detection

_EN_TITLE_KEYWORDS = {
    "data", "policy", "policies", "security", "governance", "fairness", "ethics", "public", "digital", "economy", "economic",
    "analysis", "evolution", "evolutionary", "construction", "method", "methods", "model", "models", "framework",
    "technology", "system", "systems", "knowledge", "information", "library", "libraries", "journal", "journals",
    "research", "study", "studies", "issue", "issues", "risk", "risks", "quality", "element", "elements", "chain",
    "industrial", "intelligent", "generation", "generative", "artificial", "intelligence", "network", "opinion",
    "social", "source", "sources", "rules", "traditional", "cataloging", "standard", "standards", "semantic",
    "representation", "embedding", "perspective", "context", "era", "logic", "problem", "identification", "agile",
    "collaborative", "multidimensional", "measurement", "empirical",
}


def _is_abstract_start(lines: List[str], i: int) -> bool:
    line = _normalize_line(lines[i]) if i < len(lines) else ""
    compact = re.sub(r"\s+", "", line)
    if re.match(r"^(摘\s*要|摘要)\b", line) or compact.startswith("摘要") or compact.startswith("摘要:") or compact.startswith("摘要："):
        return True
    if compact == "摘" and i + 1 < len(lines):
        nxt = re.sub(r"\s+", "", _normalize_line(lines[i + 1]))
        if nxt.startswith("要"):
            return True
    return False


def _journal_names_hit_from_kb(text: str, journal_kb: List[Dict[str, Any]] | None = None) -> List[str]:
    hits: List[str] = []
    if not text:
        return hits
    front = _front_text(text, max_pages=3)
    lines = [_normalize_line(x) for x in front.splitlines() if _normalize_line(x)]
    head_lines = lines[:120]
    head_text = "\n".join(head_lines)
    head_norm = re.sub(r"\s+", " ", _normalize_text(head_text)).lower()
    compact_head = re.sub(r"\s+", "", head_norm)

    for en, cn in COMMON_JOURNAL_EN_CN.items():
        if en in head_norm or re.sub(r"\s+", "", en) in compact_head:
            if cn not in hits:
                hits.append(cn)

    for x in (journal_kb or []):
        cn = str(x.get("name_cn", "")).strip()
        en = str(x.get("name_en", "")).strip()
        aliases = x.get("alias_en") or []
        if isinstance(aliases, str):
            aliases = [aliases]
        if not cn:
            continue
        hit = False
        compact_cn = re.sub(r"\s+", "", cn)
        # Chinese journal names: require line-level header evidence. This avoids
        # Preserved production heuristic.
        for idx, line in enumerate(head_lines[:80]):
            compact_line = re.sub(r"\s+", "", line)
            if compact_line == compact_cn:
                hit = True
                break
            if compact_line.startswith(compact_cn) and re.search(r"20\d{2}年|第\d+卷|第\d+期", compact_line):
                hit = True
                break
            if idx <= 12 and len(compact_cn) >= 4 and compact_cn in compact_line and len(compact_line) <= len(compact_cn) + 12:
                hit = True
                break
        # English journal names: require the English name as a visible header
        # line, not merely an occurrence in a bibliography or prose.
        if not hit and en:
            en_low = re.sub(r"\s+", " ", en.lower()).strip()
            en_compact = re.sub(r"\s+", "", en_low)
            for line in head_lines[:100]:
                line_low = re.sub(r"\s+", " ", _normalize_text(line).lower()).strip()
                line_compact = re.sub(r"\s+", "", line_low)
                if line_low == en_low or line_compact == en_compact:
                    hit = True
                    break
                if len(en_low) >= 12 and en_low in line_low and len(line_low) <= len(en_low) + 40:
                    hit = True
                    break
        if not hit:
            for a in aliases:
                aa = str(a).strip().lower()
                if not aa:
                    continue
                aa_compact = re.sub(r"\s+", "", aa)
                for line in head_lines[:100]:
                    line_low = re.sub(r"\s+", " ", _normalize_text(line).lower()).strip()
                    if line_low == aa or re.sub(r"\s+", "", line_low) == aa_compact:
                        hit = True
                        break
                if hit:
                    break
        if hit and cn not in hits:
            hits.append(cn)
    return hits


def _looks_like_english_author_or_affiliation(line: str) -> bool:
    raw_line = _nfkc(line or "").strip()
    if not raw_line:
        return False
    low = raw_line.lower()
    if any(x in low for x in ["school of", "university", "institute", "academy", "college", "china)", "orcid", "email", "corresponding author", "department of", "laboratory"]):
        return True
    if re.match(r"^\d+\s*[\(（]?[A-Z]", raw_line):
        return True

    # Remove footnote digits and common separators.
    clean = re.sub(r"\d+(?:[,，]\d+)*|\*|＆|&|\band\b", " ", raw_line, flags=re.I)
    words = [w.strip(",.;:()（）") for w in clean.split() if w.strip(",.;:()（）")]
    if not words:
        return False
    word_lows = {w.lower() for w in words}
    if word_lows & _EN_TITLE_KEYWORDS:
        return False
    if len(words) <= 12:
        titlecase = [bool(re.match(r"^[A-Z][a-zA-Z\-']+$", w)) for w in words]
        small_words = {"of", "the", "in", "and", "for", "from", "under", "based", "with", "on", "by", "to", "toward", "towards", "as"}
        has_connector = any(w.lower() in small_words for w in words)
        if all(titlecase) and not has_connector and len(words) >= 2:
            return True
    return False


# v3.8.8.5.5 patch C: remove prose false positives and support split author lines

def _valid_title_line(line: str) -> bool:
    line = _normalize_line(line)
    compact = re.sub(r"\s+", "", line)
    if not re.search(r"[\u4e00-\u9fff]", line):
        return False
    if not (6 <= len(compact) <= 90):
        return False
    bad_fragments = [
        "ISSN", "CN ", "DOI", "http", "www.", "收稿日期", "修回日期", "基金项目", "作者简介", "通信作者",
        "关键词", "分类号", "中图分类号", "文献标识码", "文章编号", "摘 要", "摘要", "网络首发", "引用格式",
        "引用本文", "Vol.", "No.", "版权所有", "Reproduction", "Corresponding", "研究方向", "E-mail", "Email",
    ]
    if any(x in line for x in bad_fragments):
        return False
    if re.search(r"[\[［【]\s*\d+\s*[\]］】]", line):
        return False
    if line.rstrip().endswith(("。", "，", "；", "、", ";", ",")):
        return False
    if re.fullmatch(r"(第)?\d{1,4}", compact):
        return False
    if re.match(r"^(20\d{2}|XXXX|XX)\s*年", compact) or re.search(r"20\d{2}年\d{1,2}月", compact):
        return False
    if re.search(r"^(第)?[一二三四五六七八九十百千万\d]+卷(第)?[一二三四五六七八九十百千万\d]+期$", compact):
        return False
    if re.search(r"^(总第.*卷|第.*期|Vol\.|No\.)", compact, flags=re.I):
        return False
    if compact in _NON_AUTHOR_WORDS:
        return False
    if len(compact) <= 8 and any(x in compact for x in ("情报", "学报", "期刊", "杂志", "图书馆", "探索", "法学")):
        return False
    if re.search(r"大学|学院|研究所|研究院|实验室|中心|北京市|上海市|武汉|长春|天津|哈尔滨|郑州|南京|苏州|\d{6}", line):
        return False
    if "■" in line or "▋" in line:
        return False
    return True


def _raw_cn_name_parts_from_line(line: str) -> Tuple[List[str], bool]:
    line = _normalize_line(line)
    if not line:
        return [], False
    if any(x in line for x in ("作者简介", "通信作者", "基金项目", "收稿日期", "修回日期", "DOI", "关键词", "分类号", "文章编号")):
        return [], False
    stop_after = False
    aff_pos = None
    for mark in ("（", "(", "［", "["):
        p = line.find(mark)
        if p >= 0 and any(w in line[p:] for w in _AFFILIATION_WORDS):
            aff_pos = p if aff_pos is None else min(aff_pos, p)
    if aff_pos is not None:
        line = line[:aff_pos]
        stop_after = True
    elif any(w in line for w in _AFFILIATION_WORDS) and len(re.sub(r"[^\u4e00-\u9fff]", "", line)) > 4:
        return [], True

    line = re.sub(r"[A-Za-z@._:/\\-]+", " ", line)
    line = re.sub(r"\d+\s*(?:[,，、]\s*\d+)*", " ", line)
    line = line.replace("*", " ").replace("＊", " ").replace("■", " ").replace("▋", " ")
    parts = [p for p in re.split(r"[\s,，、;；&＆]+", line) if p.strip()]
    out: List[str] = []
    for p in parts:
        cjk = re.sub(r"[^\u4e00-\u9fff]", "", p)
        if not cjk or cjk in _NON_AUTHOR_WORDS:
            continue
        if len(cjk) == 1:
            if cjk in _COMMON_CN_SURNAMES:
                out.append(cjk)
        elif len(cjk) <= 4:
            if _is_possible_cn_person_name(cjk):
                out.append(cjk)
        # Do not split long continuous Chinese strings; this was the source of
        # Preserved production heuristic.
    return out, stop_after


def _extract_cn_person_names_from_lines(lines: List[str], max_lines: int = 16) -> List[str]:
    names: List[str] = []
    pending = ""
    for line in lines[:max_lines]:
        line_n = _normalize_line(line)
        if not line_n:
            continue
        if _is_abstract_start([line_n], 0) or "关键词" in line_n:
            break
        parts, stop = _raw_cn_name_parts_from_line(line_n)
        for part in parts:
            if len(part) == 1:
                if pending:
                    cand = pending + part
                    if _is_possible_cn_person_name(cand) and cand not in names:
                        names.append(cand)
                    pending = ""
                else:
                    pending = part
                continue
            if pending:
                cand = pending + part[:1]
                if _is_possible_cn_person_name(cand) and cand not in names:
                    names.append(cand)
                    rest = part[1:]
                    if _is_possible_cn_person_name(rest) and rest not in names:
                        names.append(rest)
                    pending = ""
                    continue
                pending = ""
            if _is_possible_cn_person_name(part) and part not in names:
                names.append(part)
        if stop and names:
            break
    return names


def _cn_name_tokens_from_line(line: str) -> Tuple[List[str], bool]:
    parts, stop = _raw_cn_name_parts_from_line(line)
    names: List[str] = []
    pending = ""
    for part in parts:
        if len(part) == 1:
            if pending:
                cand = pending + part
                if _is_possible_cn_person_name(cand):
                    names.append(cand)
                pending = ""
            else:
                pending = part
        else:
            if _is_possible_cn_person_name(part):
                names.append(part)
    return names, stop


def _looks_like_author_candidate_line(line: str) -> bool:
    line_n = _normalize_line(line)
    if not re.search(r"[\u4e00-\u9fff]", line_n):
        return False
    if not line_n or line_n in _NON_AUTHOR_WORDS:
        return False
    if _valid_title_line(line_n):
        return False
    names, _ = _cn_name_tokens_from_line(line_n)
    return bool(names)


def _extract_title_author_from_front(lines: List[str]) -> Tuple[str, str]:
    lines = [_normalize_line(x) for x in lines if _normalize_line(x)]
    abstract_idx = next((i for i in range(min(240, len(lines))) if _is_abstract_start(lines, i)), -1)
    limit = abstract_idx if abstract_idx > 0 else min(120, len(lines))
    win = lines[:limit]

    candidates: List[Tuple[int, str, List[str], int]] = []
    for i, line in enumerate(win):
        compact = re.sub(r"\s+", "", line)
        line_names = _extract_cn_person_names_from_lines([line], max_lines=1)
        marker_start = compact in {"*", "＊"} or re.fullmatch(r"\d+(?:[,，]\d+)*", compact or "") is not None
        if not line_names and not marker_start:
            continue
        title = _extract_title_block_before(win, i)
        if not title or title in _NON_AUTHOR_WORDS or re.search(r"20\d{2}年", title):
            continue
        names = _extract_cn_person_names_from_lines(win[i:i+16], max_lines=16)
        if not names:
            continue
        score = len(names) * 100 + len(title) - i
        candidates.append((i, title, names, score))

    if candidates:
        i, title, names, score = max(candidates, key=lambda x: x[3])
        return _clean_chinese_title(title), ",".join(names[:12])

    valid = [(i, l) for i, l in enumerate(win) if _valid_title_line(l)]
    if valid:
        i, t = max(valid, key=lambda x: len(re.sub(r"\s+", "", x[1])))
        names = _extract_cn_person_names_from_lines(win[i+1:i+16], max_lines=15)
        return _clean_chinese_title(t), ",".join(names[:12])
    return "", ""


def _looks_like_english_author_or_affiliation(line: str) -> bool:
    raw_line = _nfkc(line or "").strip()
    if not raw_line:
        return False
    low = raw_line.lower()
    affiliation_terms = [
        "school of", "university", "institute", "academy", "college", "china)", "china;", "china,", "orcid", "email",
        "corresponding author", "department of", "laboratory", "beijing", "shanghai", "tianjin", "zhengzhou",
        "nanjing", "suzhou", "harbin", "wuhan", "hunan", "henan", "province",
    ]
    if any(x in low for x in affiliation_terms):
        return True
    if re.search(r"\b\d{5,6}\b", raw_line):
        return True
    if re.match(r"^\d+\s*[\(（]?[A-Z]", raw_line):
        return True

    clean = re.sub(r"\d+(?:[,，]\d+)*|\*|＆|&|\band\b", " ", raw_line, flags=re.I)
    words = [w.strip(",.;:()（）") for w in clean.split() if w.strip(",.;:()（）")]
    if not words:
        return False
    word_lows = {w.lower() for w in words}
    if word_lows & _EN_TITLE_KEYWORDS:
        return False
    if len(words) <= 12:
        titlecase = [bool(re.match(r"^[A-Z][a-zA-Z\-']+$", w)) for w in words]
        small_words = {"of", "the", "in", "and", "for", "from", "under", "based", "with", "on", "by", "to", "toward", "towards", "as"}
        has_connector = any(w.lower() in small_words for w in words)
        if all(titlecase) and not has_connector and len(words) >= 2:
            return True
    return False


# v3.8.8.5.5 patch D: split single-character given names and marker-aware pages

def _raw_cn_name_parts_from_line(line: str) -> Tuple[List[str], bool]:
    original = _normalize_line(line)
    line = original
    if not line:
        return [], False
    if any(x in line for x in ("作者简介", "通信作者", "基金项目", "收稿日期", "修回日期", "DOI", "关键词", "分类号", "文章编号")):
        return [], False
    # Long prose lines should not be segmented into pseudo names.
    cjk_total = re.sub(r"[^\u4e00-\u9fff]", "", line)
    if len(cjk_total) > 18 and not any(w in line for w in _AFFILIATION_WORDS):
        return [], False

    stop_after = False
    aff_pos = None
    for mark in ("（", "(", "［", "["):
        p = line.find(mark)
        if p >= 0 and any(w in line[p:] for w in _AFFILIATION_WORDS):
            aff_pos = p if aff_pos is None else min(aff_pos, p)
    if aff_pos is not None:
        line = line[:aff_pos]
        stop_after = True
    elif any(w in line for w in _AFFILIATION_WORDS) and len(re.sub(r"[^\u4e00-\u9fff]", "", line)) > 4:
        return [], True

    line = re.sub(r"[A-Za-z@._:/\\-]+", " ", line)
    line = re.sub(r"\d+\s*(?:[,，、]\s*\d+)*", " ", line)
    line = line.replace("*", " ").replace("＊", " ").replace("■", " ").replace("▋", " ")
    parts = [p for p in re.split(r"[\s,，、;；&＆]+", line) if p.strip()]
    out: List[str] = []
    for p in parts:
        cjk = re.sub(r"[^\u4e00-\u9fff]", "", p)
        if not cjk or cjk in _NON_AUTHOR_WORDS:
            continue
        if len(cjk) == 1:
            out.append(cjk)
        elif len(cjk) <= 4 and _is_possible_cn_person_name(cjk):
            out.append(cjk)
    return out, stop_after


def _extract_pdf_page_range(lines: List[str]) -> str:
    # Preserve page-marker context if available.
    raw_lines = [_normalize_line(x) for x in lines]
    joined_lines = "\n".join(raw_lines[:260])

    m = re.search(r"[\(（]\d+[\)）]\s*[:：]\s*(?P<pages>\d+\s*[-–—－]\s*\d+)", joined_lines)
    if m:
        return m.group("pages").replace(" ", "").replace("–", "-").replace("—", "-").replace("－", "-")

    m = re.search(r"\(?(?:20\d{2})\)?\s*\)?\s*\d{2}\s*[-－]\s*0*(?P<start>\d{1,4})\s*[-－]\s*(?P<count>\d{1,3})", joined_lines)
    if m:
        start = int(m.group("start"))
        count = int(m.group("count"))
        if start > 0 and 1 <= count <= 80:
            end = start + count - 1
            return f"{start}-{end}" if end != start else str(start)

    marker_pages: List[int] = []
    for idx, line in enumerate(raw_lines):
        if line.startswith("--- PDF_PAGE_"):
            for j in range(idx - 1, max(-1, idx - 8), -1):
                prev = raw_lines[j]
                mm = re.fullmatch(r"[—\-–－]*\s*(\d{1,4})\s*[—\-–－]*", prev)
                if mm:
                    val = int(mm.group(1))
                    if 1 <= val < 1900:
                        marker_pages.append(val)
                        break
    # Last selected page footer.
    for j in range(len(raw_lines) - 1, max(-1, len(raw_lines) - 12), -1):
        mm = re.fullmatch(r"[—\-–－]*\s*(\d{1,4})\s*[—\-–－]*", raw_lines[j])
        if mm:
            val = int(mm.group(1))
            if 1 <= val < 1900:
                marker_pages.append(val)
                break
    if len(set(marker_pages)) >= 2:
        return f"{min(marker_pages)}-{max(marker_pages)}"
    if len(set(marker_pages)) == 1:
        return str(marker_pages[0])

    # Fallback: use only dash-decorated footers, not arbitrary standalone digits.
    page_nums: List[int] = []
    for line_n in raw_lines:
        m3 = re.fullmatch(r"[—\-–－]+\s*(\d{1,4})\s*[—\-–－]*", line_n) or re.fullmatch(r"[—\-–－]*\s*(\d{1,4})\s*[—\-–－]+", line_n)
        if m3:
            val = int(m3.group(1))
            if 1 <= val < 1900:
                page_nums.append(val)
    if len(set(page_nums)) >= 2:
        return f"{min(page_nums)}-{max(page_nums)}"
    if len(set(page_nums)) == 1:
        return str(page_nums[0])
    return ""


def extract_reference_from_metadata(text: str, journal_names: List[str] | None = None) -> str:
    raw_lines = [_normalize_line(x) for x in (text or "").splitlines()]
    lines = [x for x in raw_lines if x and not x.startswith("--- PDF_PAGE_")]
    if not lines:
        return ""

    front = _front_text(text, max_pages=3)
    front_lines = [_normalize_line(x) for x in front.splitlines()]
    front_lines = [x for x in front_lines if x and not x.startswith("--- PDF_PAGE_")]

    joined_front = "\n".join(front_lines[:240])
    joined_all = "\n".join(lines)

    journal, year, volume, issue = _extract_journal_year_volume_issue(joined_front, journal_names=journal_names)
    if not journal or not year or not volume or not issue:
        j2, y2, v2, i2 = _extract_journal_year_volume_issue(joined_all[:12000], journal_names=journal_names)
        journal = journal or j2
        year = year or y2
        volume = volume or v2
        issue = issue or i2

    pages = _extract_pdf_page_range(raw_lines)
    if not pages:
        for pat in [r"起止页码\s*[:：]\s*(?P<pages>\d+\s*[-–—－]\s*\d+)", r"Pages\s*[:：]\s*(?P<pages>\d+\s*[-–—－]\s*\d+)"]:
            mm = re.search(pat, joined_all)
            if mm:
                pages = mm.group("pages").replace(" ", "").replace("–", "-").replace("—", "-").replace("－", "-")
                break

    title, authors = _extract_title_author_from_front(front_lines)
    if not (title and authors):
        title2, authors2 = _extract_title_author_from_front(lines[:220])
        title = title or title2
        authors = authors or authors2

    online_url = ""
    um = re.search(r"网络首发(?:时间|地址)?[^\n]{0,120}(https?://[A-Za-z0-9._~:/?#\[\]@!$&'()*+,;=%-]+)", joined_all)
    if not um:
        um = URL_ASCII_RE.search(joined_all)
    if um:
        online_url = um.group(1) if um.lastindex else um.group(0)

    if not (authors and title and journal):
        return ""

    if online_url and not year:
        return _clean_reference(f"{authors}. {title}[J/OL]. {journal}. {online_url}.")
    if year and volume and issue and pages:
        return _clean_reference(f"{authors}. {title}[J]. {journal}, {year}, {volume}({issue}): {pages}.")
    if year and pages:
        return _clean_reference(f"{authors}. {title}[J]. {journal}, {year}: {pages}.")
    if year:
        return _clean_reference(f"{authors}. {title}[J]. {journal}, {year}.")
    if pages:
        return _clean_reference(f"{authors}. {title}[J]. {journal}: {pages}.")
    return _clean_reference(f"{authors}. {title}[J]. {journal}.")


# v3.8.8.5.5 patch E: do not pull preceding prose into split titles

def _extract_title_block_before(win: List[str], author_idx: int) -> str:
    title_lines: List[str] = []
    for j in range(author_idx - 1, max(-1, author_idx - 10), -1):
        cand = win[j]
        compact = re.sub(r"\s+", "", _normalize_line(cand))
        if not compact or compact in {"*", "＊", "·", "·专", "题·", "专", "题"}:
            continue
        if _valid_title_line(cand):
            title_lines.insert(0, cand)
            continue
        if title_lines:
            # Only allow a short second title segment. Never cross a citation,
            # sentence boundary, or prose fragment.
            if (
                2 <= len(compact) <= 16
                and re.search(r"[\u4e00-\u9fff]", compact)
                and not re.search(r"[\[［【]\s*\d+\s*[\]］】|[。；;，,]", cand)
                and not _looks_like_author_candidate_line(cand)
                and not any(w in cand for w in _AFFILIATION_WORDS)
            ):
                title_lines.insert(0, cand)
                continue
            break
    while title_lines and not _valid_title_line(title_lines[0]):
        title_lines.pop(0)
    return _clean_chinese_title("".join(title_lines))


# v3.8.8.5.5 patch F: English-title lines must not contain CJK text

def _mostly_english(line: str) -> bool:
    line = _repair_english_spacing(line).strip()
    if not line:
        return False
    cjk = sum("\u4e00" <= ch <= "\u9fff" for ch in line)
    if cjk:
        return False
    letters = sum(ch.isalpha() and ord(ch) < 128 for ch in line)
    digits = sum(ch.isdigit() for ch in line)
    return letters >= 12 and letters > digits


# v3.8.8.5.5 patch G: journal header lines, short title tails, and online-first metadata

def _valid_title_line(line: str) -> bool:
    line = _normalize_line(line)
    compact = re.sub(r"\s+", "", line)
    if not re.search(r"[\u4e00-\u9fff]", line):
        return False
    if not (6 <= len(compact) <= 90):
        return False
    if re.search(r"[\u4e00-\u9fff]{2,20}\s*[,，]\s*(?:20\d{2}|XXXX|XX)\s*[,，]\s*(?:\d+|XX)\s*[\(（](?:\d+|XX)[\)）]", line):
        return False
    bad_fragments = [
        "ISSN", "CN ", "DOI", "http", "www.", "收稿日期", "修回日期", "基金项目", "作者简介", "通信作者",
        "关键词", "分类号", "中图分类号", "文献标识码", "文章编号", "摘 要", "摘要", "网络首发", "引用格式",
        "引用本文", "Vol.", "No.", "版权所有", "Reproduction", "Corresponding", "研究方向", "E-mail", "Email",
    ]
    if any(x in line for x in bad_fragments):
        return False
    if re.search(r"[\[［【]\s*\d+\s*[\]］】]", line):
        return False
    if line.rstrip().endswith(("。", "，", "；", "、", ";", ",")):
        return False
    if re.fullmatch(r"(第)?\d{1,4}", compact):
        return False
    if re.match(r"^(20\d{2}|XXXX|XX)\s*年", compact) or re.search(r"(?:20\d{2}|XXXX|XX)年(?:\d{1,2}|XX)月", compact):
        return False
    if re.search(r"^(第)?[一二三四五六七八九十百千万\d]+卷(第)?[一二三四五六七八九十百千万\d]+期$", compact):
        return False
    if re.search(r"^(总第.*卷|第.*期|Vol\.|No\.)", compact, flags=re.I):
        return False
    if compact in _NON_AUTHOR_WORDS:
        return False
    if len(compact) <= 8 and any(x in compact for x in ("情报", "学报", "期刊", "杂志", "图书馆", "探索", "法学")):
        return False
    if re.search(r"大学|学院|研究所|研究院|实验室|中心|北京市|上海市|武汉|长春|天津|哈尔滨|郑州|南京|苏州|\d{6}", line):
        return False
    if "■" in line or "▋" in line:
        return False
    return True


def _extract_title_block_before(win: List[str], author_idx: int) -> str:
    title_lines: List[str] = []
    for j in range(author_idx - 1, max(-1, author_idx - 10), -1):
        cand = win[j]
        compact = re.sub(r"\s+", "", _normalize_line(cand))
        if not compact or compact in {"*", "＊", "·", "·专", "题·", "专", "题"}:
            continue
        clean_short_tail = (
            2 <= len(compact) <= 16
            and re.search(r"[\u4e00-\u9fff]", compact)
            and not re.search(r"[\[［【]\s*\d+\s*[\]］】|[。；;，,]", cand)
            and not _looks_like_author_candidate_line(cand)
            and not any(w in cand for w in _AFFILIATION_WORDS)
        )
        if _valid_title_line(cand):
            title_lines.insert(0, cand)
            continue
        if clean_short_tail:
            title_lines.insert(0, cand)
            continue
        if title_lines:
            break
    while title_lines and not (_valid_title_line(title_lines[0]) or len(re.sub(r"\s+", "", title_lines[0])) <= 16):
        title_lines.pop(0)
    return _clean_chinese_title("".join(title_lines))


def _extract_title_author_from_front(lines: List[str]) -> Tuple[str, str]:
    lines = [_normalize_line(x) for x in lines if _normalize_line(x)]
    abstract_idx = next((i for i in range(min(240, len(lines))) if _is_abstract_start(lines, i)), -1)
    limit = abstract_idx if abstract_idx > 0 else min(120, len(lines))
    win = lines[:limit]

    candidates: List[Tuple[int, str, List[str], int]] = []
    for i, line in enumerate(win):
        compact = re.sub(r"\s+", "", line)
        line_names = _extract_cn_person_names_from_lines([line], max_lines=1)
        marker_start = compact in {"*", "＊"} or compact.startswith(("■", "▋")) or re.fullmatch(r"\d+(?:[,，]\d+)*", compact or "") is not None
        if not line_names and not marker_start:
            continue
        title = _extract_title_block_before(win, i)
        if not title or title in _NON_AUTHOR_WORDS or re.search(r"(?:20\d{2}|XXXX|XX)年", title):
            continue
        names = _extract_cn_person_names_from_lines(win[i:i+16], max_lines=16)
        if not names:
            continue
        score = len(names) * 100 + len(title) - i
        candidates.append((i, title, names, score))

    if candidates:
        i, title, names, score = max(candidates, key=lambda x: x[3])
        return _clean_chinese_title(title), ",".join(names[:12])

    valid = [(i, l) for i, l in enumerate(win) if _valid_title_line(l)]
    if valid:
        i, t = max(valid, key=lambda x: len(re.sub(r"\s+", "", x[1])))
        names = _extract_cn_person_names_from_lines(win[i+1:i+16], max_lines=15)
        return _clean_chinese_title(t), ",".join(names[:12])
    return "", ""


def _journal_names_hit_from_kb(text: str, journal_kb: List[Dict[str, Any]] | None = None) -> List[str]:
    hits: List[str] = []
    if not text:
        return hits
    front = _front_text(text, max_pages=3)
    lines = [_normalize_line(x) for x in front.splitlines() if _normalize_line(x)]
    head_lines = lines[:120]
    head_text = "\n".join(head_lines)
    head_norm = re.sub(r"\s+", " ", _normalize_text(head_text)).lower()
    compact_head = re.sub(r"\s+", "", head_norm)

    for en, cn in COMMON_JOURNAL_EN_CN.items():
        if en in head_norm or re.sub(r"\s+", "", en) in compact_head:
            if cn not in hits:
                hits.append(cn)

    for x in (journal_kb or []):
        cn = str(x.get("name_cn", "")).strip()
        en = str(x.get("name_en", "")).strip()
        aliases = x.get("alias_en") or []
        if isinstance(aliases, str):
            aliases = [aliases]
        if not cn:
            continue
        hit = False
        compact_cn = re.sub(r"\s+", "", cn)
        for idx, line in enumerate(head_lines[:80]):
            compact_line = re.sub(r"\s+", "", line)
            if compact_line == compact_cn:
                hit = True
                break
            if compact_line.startswith(compact_cn) and re.search(r"20\d{2}|XXXX|XX|第\d+卷|第\d+期", compact_line):
                hit = True
                break
            if idx <= 12 and len(compact_cn) >= 4 and compact_cn in compact_line and len(compact_line) <= len(compact_cn) + 18:
                hit = True
                break
        if not hit and en:
            en_low = re.sub(r"\s+", " ", en.lower()).strip()
            en_compact = re.sub(r"\s+", "", en_low)
            for line in head_lines[:100]:
                line_low = re.sub(r"\s+", " ", _normalize_text(line).lower()).strip()
                line_compact = re.sub(r"\s+", "", line_low)
                if line_low == en_low or line_compact == en_compact:
                    hit = True
                    break
                if len(en_low) >= 12 and en_low in line_low and len(line_low) <= len(en_low) + 40:
                    hit = True
                    break
        if not hit:
            for a in aliases:
                aa = str(a).strip().lower()
                if not aa:
                    continue
                aa_compact = re.sub(r"\s+", "", aa)
                for line in head_lines[:100]:
                    line_low = re.sub(r"\s+", " ", _normalize_text(line).lower()).strip()
                    if line_low == aa or re.sub(r"\s+", "", line_low) == aa_compact:
                        hit = True
                        break
                if hit:
                    break
        if hit and cn not in hits:
            hits.append(cn)
    return hits


def _extract_journal_year_volume_issue(joined: str, journal_names: List[str] | None = None) -> Tuple[str, str, str, str]:
    joined = _normalize_text(joined)
    lines = [_normalize_line(x) for x in joined.splitlines() if _normalize_line(x)]
    head_short = "\n".join(lines[:35])
    head = "\n".join(lines[:90])
    journal = year = volume = issue = ""

    if journal_names:
        journal = journal_names[0]

    low = re.sub(r"\s+", " ", head.lower())
    compact_low = re.sub(r"\s+", "", low)
    for en, cn in COMMON_JOURNAL_EN_CN.items():
        if en in low or re.sub(r"\s+", "", en) in compact_low:
            journal = journal or cn
            break

    if not journal:
        for i, line in enumerate(lines[:30]):
            compact = re.sub(r"\s+", "", line)
            if re.search(r"(?:20\d{2}|XXXX|XX)年", compact) and len(compact) <= 35:
                cand = re.sub(r"(?:20\d{2}|XXXX|XX)年.*$", "", compact)
                if 2 <= len(cand) <= 12:
                    journal = cand
                    break
            if re.match(r"^[\u4e00-\u9fff]{2,20}\s*[,，]\s*(?:20\d{2}|XXXX|XX)\s*[,，]", line):
                journal = re.split(r"[,，]", line, maxsplit=1)[0].strip()
                break
            if i + 1 < len(lines) and _mostly_english(lines[i+1]) and len(compact) <= 12:
                if any(x in compact for x in ("学报", "期刊", "情报", "图书", "杂志", "法学", "探索")):
                    journal = compact
                    break

    net_y = re.search(r"网络首发(?:时间|日期)?\s*[:：]?\s*(20\d{2})", head)
    if net_y:
        year = net_y.group(1)
    else:
        ym = re.search(r"(20\d{2})\s*年", head_short)
        if ym:
            year = ym.group(1)
        else:
            ym = re.search(r"[,，]\s*(20\d{2})\s*[,，]", head_short)
            if ym:
                year = ym.group(1)
            else:
                ym = re.search(r"\b(20\d{2})\b", head_short)
                if ym:
                    year = ym.group(1)

    vm = re.search(r"第\s*(?P<vol>\d+)\s*卷", head_short)
    if vm:
        volume = vm.group("vol")
    else:
        vm = re.search(r"Vol\.\s*(?P<vol>\d+)", head_short, flags=re.I)
        if vm:
            volume = vm.group("vol")
        else:
            vm = re.search(r"[,，]\s*(?P<vol>\d+|XX)\s*[\(（](?P<issue>\d+|XX)[\)）]\s*[:：]\s*\d+", head_short)
            if vm:
                volume = "" if vm.group("vol") == "XX" else vm.group("vol")
                issue = "" if vm.group("issue") == "XX" else vm.group("issue")

    im = re.search(r"第\s*(?P<issue>\d+)\s*期", head_short)
    if im:
        issue = im.group("issue")
    elif not issue:
        im = re.search(r"No\.\s*(?P<issue>\d+)", head_short, flags=re.I)
        if im:
            issue = im.group("issue")
    return journal, year, volume, issue


def extract_reference_from_metadata(text: str, journal_names: List[str] | None = None) -> str:
    raw_lines = [_normalize_line(x) for x in (text or "").splitlines()]
    lines = [x for x in raw_lines if x and not x.startswith("--- PDF_PAGE_")]
    if not lines:
        return ""

    front = _front_text(text, max_pages=3)
    front_lines = [_normalize_line(x) for x in front.splitlines()]
    front_lines = [x for x in front_lines if x and not x.startswith("--- PDF_PAGE_")]

    joined_front = "\n".join(front_lines[:240])
    joined_all = "\n".join(lines)

    journal, year, volume, issue = _extract_journal_year_volume_issue(joined_front, journal_names=journal_names)
    if not journal or not year or not volume or not issue:
        j2, y2, v2, i2 = _extract_journal_year_volume_issue(joined_all[:12000], journal_names=journal_names)
        journal = journal or j2
        year = year or y2
        volume = volume or v2
        issue = issue or i2

    pages = _extract_pdf_page_range(raw_lines)

    title, authors = _extract_title_author_from_front(front_lines)
    if not (title and authors):
        title2, authors2 = _extract_title_author_from_front(lines[:220])
        title = title or title2
        authors = authors or authors2

    online_url = ""
    um = re.search(r"网络首发(?:时间|日期|地址)?[^\n]{0,160}(https?://[A-Za-z0-9._~:/?#\[\]@!$&'()*+,;=%-]+)", joined_all)
    if not um:
        # Prefer CNKI URL over journal homepage URLs.
        for m in URL_ASCII_RE.finditer(joined_all):
            cand = m.group(0)
            if "link.cnki.net/urlid" in cand:
                um = m
                break
    if not um:
        um = URL_ASCII_RE.search(joined_all)
    if um:
        online_url = um.group(1) if hasattr(um, "lastindex") and um.lastindex else um.group(0)

    if not (authors and title and journal):
        return ""

    if online_url and (not (year and volume and issue and pages) or "link.cnki.net/urlid" in online_url):
        return _clean_reference(f"{authors}. {title}[J/OL]. {journal}. {online_url}.")
    if year and volume and issue and pages:
        return _clean_reference(f"{authors}. {title}[J]. {journal}, {year}, {volume}({issue}): {pages}.")
    if year and pages:
        return _clean_reference(f"{authors}. {title}[J]. {journal}, {year}: {pages}.")
    if year:
        return _clean_reference(f"{authors}. {title}[J]. {journal}, {year}.")
    if pages:
        return _clean_reference(f"{authors}. {title}[J]. {journal}: {pages}.")
    return _clean_reference(f"{authors}. {title}[J]. {journal}.")


# v3.8.8.5.5 patch H: exclude volume/issue tails from title and recover vol/issue broadly

def _extract_title_block_before(win: List[str], author_idx: int) -> str:
    title_lines: List[str] = []
    for j in range(author_idx - 1, max(-1, author_idx - 10), -1):
        cand = win[j]
        compact = re.sub(r"\s+", "", _normalize_line(cand))
        if not compact or compact in {"*", "＊", "·", "·专", "题·", "专", "题"}:
            continue
        header_like_short = bool(
            re.search(r"(?:20\d{2}|XXXX|XX)年", compact)
            or re.fullmatch(r"第?[一二三四五六七八九十百千万〇零\d]+[卷期]", compact)
            or re.search(r"^(情报资料工作|现代情报|中国科技期刊研究|情报学报|图书馆杂志)", compact)
        )
        clean_short_tail = (
            2 <= len(compact) <= 16
            and not header_like_short
            and re.search(r"[\u4e00-\u9fff]", compact)
            and not re.search(r"[\[［【]\s*\d+\s*[\]］】|[。；;，,]", cand)
            and not _looks_like_author_candidate_line(cand)
            and not any(w in cand for w in _AFFILIATION_WORDS)
        )
        if _valid_title_line(cand):
            title_lines.insert(0, cand)
            continue
        if clean_short_tail:
            title_lines.insert(0, cand)
            continue
        if title_lines:
            break
    while title_lines and not (_valid_title_line(title_lines[0]) or len(re.sub(r"\s+", "", title_lines[0])) <= 16):
        title_lines.pop(0)
    return _clean_chinese_title("".join(title_lines))


def _extract_journal_year_volume_issue(joined: str, journal_names: List[str] | None = None) -> Tuple[str, str, str, str]:
    joined = _normalize_text(joined)
    lines = [_normalize_line(x) for x in joined.splitlines() if _normalize_line(x)]
    head_short = "\n".join(lines[:40])
    head = "\n".join(lines[:140])
    journal = year = volume = issue = ""

    if journal_names:
        journal = journal_names[0]

    low = re.sub(r"\s+", " ", head.lower())
    compact_low = re.sub(r"\s+", "", low)
    for en, cn in COMMON_JOURNAL_EN_CN.items():
        if en in low or re.sub(r"\s+", "", en) in compact_low:
            journal = journal or cn
            break

    if not journal:
        for i, line in enumerate(lines[:40]):
            compact = re.sub(r"\s+", "", line)
            if re.search(r"(?:20\d{2}|XXXX|XX)年", compact) and len(compact) <= 35:
                cand = re.sub(r"(?:20\d{2}|XXXX|XX)年.*$", "", compact)
                if 2 <= len(cand) <= 12:
                    journal = cand
                    break
            if re.match(r"^[\u4e00-\u9fff]{2,20}\s*[,，]\s*(?:20\d{2}|XXXX|XX)\s*[,，]", line):
                journal = re.split(r"[,，]", line, maxsplit=1)[0].strip()
                break
            if i + 1 < len(lines) and _mostly_english(lines[i+1]) and len(compact) <= 12:
                if any(x in compact for x in ("学报", "期刊", "情报", "图书", "杂志", "法学", "探索")):
                    journal = compact
                    break

    net_y = re.search(r"网络首发(?:时间|日期)?\s*[:：]?\s*(20\d{2})", head)
    if net_y:
        year = net_y.group(1)
    else:
        for scope in (head_short, head):
            ym = re.search(r"(20\d{2})\s*年", scope)
            if ym:
                year = ym.group(1); break
            ym = re.search(r"[,，]\s*(20\d{2})\s*[,，]", scope)
            if ym:
                year = ym.group(1); break
            ym = re.search(r"\b(20\d{2})\s+\d{1,2}\s+(?:January|February|March|April|May|June|July|August|September|October|November|December)\b", scope, flags=re.I)
            if ym:
                year = ym.group(1); break

    # Numeric volume/issue
    for scope in (head_short, head):
        if not volume:
            vm = re.search(r"第\s*(?P<vol>\d+)\s*卷", scope)
            if vm:
                volume = vm.group("vol")
        if not issue:
            im = re.search(r"第\s*(?P<issue>\d+)\s*期", scope)
            if im:
                issue = im.group("issue")
        if not volume:
            vm = re.search(r"Vol\.\s*(?P<vol>\d+)", scope, flags=re.I)
            if vm:
                volume = vm.group("vol")
        if not issue:
            im = re.search(r"No\.\s*(?P<issue>\d+)", scope, flags=re.I)
            if im:
                issue = im.group("issue")
        if not (volume and issue):
            vm = re.search(r"[,，]\s*(?P<vol>\d+|XX)\s*[\(（](?P<issue>\d+|XX)[\)）]\s*[:：]\s*\d+", scope)
            if vm:
                volume = volume or ("" if vm.group("vol") == "XX" else vm.group("vol"))
                issue = issue or ("" if vm.group("issue") == "XX" else vm.group("issue"))
        if volume and issue:
            break

    # Preserved production heuristic.
    if not volume:
        vm = re.search(r"总?第(?P<vol>[一二三四五六七八九十百千万〇零\d]+)卷", head)
        if vm:
            volume = str(_chinese_numeral_to_int(vm.group("vol")) or "")
    if not issue:
        im = re.search(r"第(?P<issue>[一二三四五六七八九十百千万〇零\d]+)[期輯辑]", head)
        if im:
            issue = str(_chinese_numeral_to_int(im.group("issue")) or "")

    return journal, year, volume, issue


# v3.8.8.5.5 patch I: add common simplified surnames
_COMMON_CN_SURNAMES.update(set("闫肖"))
