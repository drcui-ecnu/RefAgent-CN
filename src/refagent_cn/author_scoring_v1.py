from __future__ import annotations
import re,unicodedata
from collections import Counter
from typing import Any,Iterable

DASHES=str.maketrans({c:"-" for c in "‐-‒–—−"})
APOS=str.maketrans({c:"'" for c in "’‘`´"})
ETAL={"et al","et al.","and others","等"}
def canonical_author_normalize(text:Any)->str:
 x=unicodedata.normalize("NFKC",str(text or "")).strip().casefold().translate(DASHES).translate(APOS)
 x=re.sub(r"(?<=\w)\.(?=\s|$)","",x);x=re.sub(r"[,;&]+"," ",x);return re.sub(r"\s+"," ",x).strip()
def strict_author_form_normalize(text:Any)->str:
 x=unicodedata.normalize("NFKC",str(text or "")).strip().casefold().translate(DASHES).translate(APOS);return re.sub(r"\s+"," ",x).strip()
def canonical_name_key(author:Any)->str:
 x=canonical_author_normalize(author);tok=re.findall(r"[a-z]+(?:[-'][a-z]+)*",x)
 if not tok:return ""
 return tok[0]+"|"+re.sub(r"[\s\-']+","","".join(tok[1:]))
def is_etal_marker(v:Any)->bool:return strict_author_form_normalize(v).rstrip(".") in {"et al","and others","等"}
def parse_predicted_authors(value:Any)->tuple[list[str],bool]:
 if isinstance(value,(list,tuple)):raw=[str(x).strip() for x in value if str(x).strip()]
 else:
  x=str(value or "").strip();raw=[z.strip() for z in re.split(r"\s*(?:;|；|&|\band\b)\s*",x,flags=re.I) if z.strip()]
 marker=any(is_etal_marker(x) for x in raw);return [x for x in raw if not is_etal_marker(x)],marker
def visible_author_count_from_chinese_reference(ref:Any)->tuple[int,bool]:
 x=str(ref or "").strip();prefix=re.split(r"[.。]",x,maxsplit=1)[0];parts=[p.strip() for p in re.split(r"[,，、;；]",prefix) if p.strip()];has=any(p=="等" or p.endswith("等") for p in parts) or bool(re.search(r"(?:[,，、;；])\s*等\s*$",prefix));names=[]
 for p in parts:
  p=re.sub(r"\s*等\s*$","",p).strip()
  if p:names.append(p)
 return len(names),has
def construct_visible_gold(gold_full:Any,chinese_reference:Any)->tuple[list[str],list[str],int,bool]:
 all_auth=[x.strip() for x in str(gold_full or "").split(";") if x.strip()];count,has=visible_author_count_from_chinese_reference(chinese_reference);visible=all_auth[:count] if has else all_auth;return all_auth,visible,count,has
def score_authors(gold_visible:Iterable[Any],prediction:Any)->dict[str,Any]:
 gold=[str(x).strip() for x in gold_visible if str(x).strip()];pred,marker=parse_predicted_authors(prediction);gk=[canonical_name_key(x) for x in gold];pk=[canonical_name_key(x) for x in pred];gs=[strict_author_form_normalize(x) for x in gold];ps=[strict_author_form_normalize(x) for x in pred]
 exact=len(gk)==len(pk) and gk==pk;strict=len(gs)==len(ps) and gs==ps
 ug=[True]*len(gk);up=[True]*len(pk);tp=0
 for i in range(min(len(gk),len(pk))):
  if gk[i] and gk[i]==pk[i]:ug[i]=up[i]=False;tp+=1
 gc=Counter(gk[i] for i in range(len(gk)) if ug[i] and gk[i]);pc=Counter(pk[i] for i in range(len(pk)) if up[i] and pk[i]);tp+=sum((gc&pc).values());fp=len(pk)-tp;fn=len(gk)-tp
 order=Counter(gk)==Counter(pk) and gk!=pk
 # Named-author count errors are distinct from equal-length romanization substitutions.
 extra=len(pk)>len(gk) and fp>0;missing=len(pk)<len(gk) and fn>0
 kinds=[]
 if exact and not strict:kinds=["FORMAT_ONLY"]
 elif not exact:
  if not pred:kinds.append("PARSING_ERROR")
  if extra:kinds.append("EXTRA_NAMED_AUTHOR")
  if missing:kinds.append("MISSING_VISIBLE_AUTHOR")
  if len(gk)!=len(pk):kinds.append("AUTHOR_COUNT")
  if order:kinds.append("AUTHOR_ORDER")
  if len(gk)==len(pk) and any(a!=b for a,b in zip(gk,pk)) and not order:kinds.append("PRONUNCIATION_OR_ROMANIZATION")
  if not kinds:kinds=["OTHER"]
 return {"Gold_Canonical_Authors":gk,"Gold_Strict_Authors":gs,"Pred_Parsed_Authors":pred,"Pred_Canonical_Authors":pk,"Pred_Strict_Authors":ps,"Canonical_Exact":exact,"Strict_Form_Exact":strict,"TP":tp,"FP":fp,"FN":fn,"Author_Order_Error":order,"Extra_Named_Author_Error":extra,"Missing_Visible_Author_Error":missing,"EtAl_Marker_Present":marker,"Mismatch_Type":";".join(kinds) if kinds else "MATCH","Mismatch_Details":f"gold={gk}; pred={pk}; strict_gold={gs}; strict_pred={ps}"}
