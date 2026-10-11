from __future__ import annotations

from typing import Dict, List, Tuple

try:
    from pypinyin import lazy_pinyin
except Exception:  # pragma: no cover
    lazy_pinyin = None

_FALLBACK_CHAR_PINYIN = {
    "张": "Zhang", "王": "Wang", "李": "Li", "赵": "Zhao", "刘": "Liu", "陈": "Chen", "任": "Ren",
    "杨": "Yang", "黄": "Huang", "周": "Zhou", "吴": "Wu", "徐": "Xu", "孙": "Sun",
    "马": "Ma", "费": "Fei", "成": "Cheng", "逸": "Yi", "姝": "Shu", "卢": "Lu", "慧": "Hui", "质": "Zhi",
    "熊": "Xiong", "思": "Si", "玥": "Yue", "玉": "Yu", "姣": "Jiao", "邓": "Deng",
    "萌": "Meng", "牟": "Mu", "冬": "Dong", "宁": "Ning", "胜": "Sheng", "霞": "Xia",
    "樊": "Fan", "振": "Zhen", "佳": "Jia", "姬": "Ji", "祥": "Xiang", "飞": "Fei", "需": "Xu", "要": "Yao",
    "崔": "Cui", "文": "Wen", "波": "Bo", "梅": "Mei", "妍": "Yan", "霜": "Shuang", "鑫": "Xin",
    "薛": "Xue", "增": "Zeng", "灿": "Can", "晓": "Xiao", "冉": "Ran", "锐": "Rui",
    "段": "Duan", "宇": "Yu", "锋": "Feng", "范": "Fan", "并": "Bing", "泽": "Ze", "泉": "Quan",
    "何": "He", "琳": "Lin", "常": "Chang", "颖": "Ying", "聪": "Cong",
    "三": "San", "四": "Si", "五": "Wu", "明": "Ming", "小": "Xiao", "华": "Hua",
}

_MULTI_CHAR_SURNAMES = {
    "欧阳", "司马", "诸葛", "上官", "夏侯", "东方", "尉迟", "公孙", "慕容", "令狐", "皇甫", "长孙", "宇文", "司徒", "司空", "端木", "申屠", "南宫", "太史", "闻人", "百里", "东郭", "西门",
}

ET_AL = "et al."


class AuthorMapper:
    def _pinyin_parts(self, name_cn: str) -> List[str]:
        name_cn = (name_cn or "").strip()
        if not name_cn:
            return []
        if lazy_pinyin:
            return [p.capitalize() for p in lazy_pinyin(name_cn) if p]
        return [_FALLBACK_CHAR_PINYIN.get(ch, ch) for ch in name_cn]

    def _name_parts_cn(self, name_cn: str) -> Tuple[str, List[str]]:
        name_cn = (name_cn or "").strip()
        if not name_cn:
            return "", []
        if name_cn.lower() in {"et al", "et al."} or name_cn == "等":
            return ET_AL, []
        parts = self._pinyin_parts(name_cn)
        if not parts:
            return "", []
        surname_len = 2 if name_cn[:2] in _MULTI_CHAR_SURNAMES and len(parts) >= 2 else 1
        surname = "".join(parts[:surname_len]) if surname_len > 1 else parts[0]
        return surname, parts[surname_len:]

    def to_pinyin_full(self, name_cn: str) -> str:
        surname, given_parts = self._name_parts_cn(name_cn)
        if not surname:
            return ""
        if surname == ET_AL:
            return ET_AL
        given = given_parts[0] + "".join(x[:1].lower() + x[1:] for x in given_parts[1:]) if given_parts else ""
        return f"{surname} {given}".strip()

    def to_apa_name(self, full_pinyin: str) -> str:
        full_pinyin = (full_pinyin or "").strip()
        if full_pinyin.lower() in {"et al", "et al."}:
            return ET_AL
        parts = [p for p in full_pinyin.replace("-", " ").split() if p]
        if not parts:
            return ""
        surname = parts[0]
        initials = " ".join(f"{p[0].upper()}." for p in parts[1:] if p)
        return f"{surname}, {initials}" if initials else surname

    def to_upper_initials(self, name_cn: str) -> str:
        """to_upper_initials; preserved production heuristic. See reproducibility documentation."""
        surname, given_parts = self._name_parts_cn(name_cn)
        if not surname:
            return ""
        if surname == ET_AL:
            return ET_AL
        initials = " ".join(p[0].upper() for p in given_parts if p)
        return f"{surname.upper()} {initials}".strip()

    def to_title_initials(self, name_cn: str) -> str:
        """to_title_initials; preserved production heuristic. See reproducibility documentation."""
        surname, given_parts = self._name_parts_cn(name_cn)
        if not surname:
            return ""
        if surname == ET_AL:
            return ET_AL
        initials = " ".join(p[0].upper() for p in given_parts if p)
        surname = surname[:1].upper() + surname[1:].lower()
        return f"{surname} {initials}".strip()

    def to_upper_surname_full_given(self, name_cn: str) -> str:
        """to_upper_surname_full_given; preserved production heuristic. See reproducibility documentation."""
        surname, given_parts = self._name_parts_cn(name_cn)
        if not surname:
            return ""
        if surname == ET_AL:
            return ET_AL
        given = given_parts[0] + "".join(x[:1].lower() + x[1:] for x in given_parts[1:]) if given_parts else ""
        return f"{surname.upper()} {given}".strip()

    def map_authors(self, authors_cn: List[str], et_al: bool = False) -> Dict[str, List[str]]:
        base_authors = [str(a).strip() for a in authors_cn if str(a).strip()]
        authors_en = [self.to_pinyin_full(a) for a in base_authors]
        authors_upper_initials = [self.to_upper_initials(a) for a in base_authors]
        authors_title_initials = [self.to_title_initials(a) for a in base_authors]
        authors_upper_surname_full_given = [self.to_upper_surname_full_given(a) for a in base_authors]
        if et_al:
            for seq in (authors_en, authors_upper_initials, authors_title_initials, authors_upper_surname_full_given):
                if not seq or seq[-1].lower() != ET_AL:
                    seq.append(ET_AL)
        authors_apa = [self.to_apa_name(a) for a in authors_en]
        return {
            "authors_en": authors_en,
            "authors_apa": authors_apa,
            "authors_upper_initials": authors_upper_initials,
            "authors_title_initials": authors_title_initials,
            "authors_upper_surname_full_given": authors_upper_surname_full_given,
        }
