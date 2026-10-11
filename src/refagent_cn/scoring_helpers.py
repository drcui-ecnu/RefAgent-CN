"""Extracted unchanged from final scoring scripts; see core_source_map."""
import ast,json,re,unicodedata

def s(x): return "" if x is None else str(x).strip()

def basic(x): return re.sub(r"[^\w\u3400-\u9fff]+","",unicodedata.normalize("NFKC",s(x)).casefold())

def tnorm(x):
    x=unicodedata.normalize("NFKC",s(x)).replace("“",'"').replace("”",'"').replace("–","-").replace("—","-")
    x=" ".join(x.split()).casefold(); return x[:-1].rstrip() if x.endswith(".") else x

def num(x):
    x=s(x); return x[:-2] if re.fullmatch(r"\d+\.0",x) else x

def vip(x):
    x=s(x).replace("：",":").replace("（","(").replace("）",")").replace("–","-").replace("—","-")
    m=re.match(r"^\s*(?:(\d+)\s*)?\(([^)]+)\)\s*:\s*(.+?)\s*$",x)
    if m:return num(m.group(1)),num(m.group(2)),basic(m.group(3))
    m=re.match(r"^\s*(\d+)\s*:\s*(.+?)\s*$",x)
    return (num(m.group(1)),"",basic(m.group(2))) if m else ("","",basic(x))

def parse_prediction(value):
    if isinstance(value, (list, tuple)):
        return [str(x).strip() for x in value if str(x).strip()]
    x = str(value or "").strip()
    if not x:
        return []
    if x.startswith("[") and x.endswith("]"):
        for parser in (json.loads, ast.literal_eval):
            try:
                parsed = parser(x)
                if isinstance(parsed, (list, tuple)):
                    return [str(z).strip() for z in parsed if str(z).strip()]
            except Exception:
                pass
    return [z.strip() for z in re.split(r"\s*(?:;|；|&|\band\b)\s*", x, flags=re.I) if z.strip()]

def normalize_name(value):
    x = unicodedata.normalize("NFKC", str(value or "")).casefold().strip()
    x = x.translate(str.maketrans({c: "-" for c in "‐-‒–—−"}))
    x = x.translate(str.maketrans({c: "'" for c in "’‘`´"}))
    x = x.replace(".", "")
    return re.sub(r"\s+", " ", x).strip()

def identity_key(value):
    """Surname is exact; given names are reduced only to observable initials."""
    x = normalize_name(value)
    tokens = re.findall(r"[a-z]+(?:[-'][a-z]+)*", x)
    if not tokens:
        return ""
    surname = tokens[0]
    initials = ""
    for token in tokens[1:]:
        for part in re.split(r"[-']+", token):
            if part:
                initials += part[0]
    return f"{surname}|{initials}"

def identity_parts(value):
    x = normalize_name(value)
    tokens = re.findall(r"[a-z]+(?:[-'][a-z]+)*", x)
    if not tokens:
        return "", ""
    surname = tokens[0]
    given = "".join(re.sub(r"[-']+", "", token) for token in tokens[1:])
    return surname, given

def identity_match(gold_value, pred_value):
    """Match every observable Gold initial without guessing surname aliases.

    Published Chinese given names are often concatenated (e.g. Hongjie) while
    APA Gold exposes syllable initials (H. J.).  The observable initials must
    occur in order in the predicted given-name string, with the first initial
    at its start.  This uses only literal letters and introduces no dictionary.
    """
    gold_surname, gold_given = identity_parts(gold_value)
    pred_surname, pred_given = identity_parts(pred_value)
    if not gold_surname or gold_surname != pred_surname:
        return False
    gold_initials = identity_key(gold_value).split("|", 1)[1]
    if not gold_initials:
        return not pred_given
    if not pred_given or pred_given[0] != gold_initials[0]:
        return False
    pos = 0
    for initial in gold_initials:
        pos = pred_given.find(initial, pos)
        if pos < 0:
            return False
        pos += 1
    return True
