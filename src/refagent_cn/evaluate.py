"""Offline computation using extracted final normalization and identity helpers."""
from __future__ import annotations
import argparse, csv, json, statistics
from pathlib import Path
from sacrebleu.metrics import CHRF
from .scoring_helpers import s,basic,tnorm,num,vip,parse_prediction,identity_match
from .author_scoring_v1 import construct_visible_gold,strict_author_form_normalize

def read_csv(path):
    with Path(path).open(encoding="utf-8-sig",newline="") as f:return list(csv.DictReader(f))

def evaluate(gold,predictions,*,comet_checkpoint=None):
    if not gold or len(gold)!=len(predictions):raise ValueError("Gold and predictions must have equal nonzero record counts")
    gd={str(int(x["Record_ID"])):x for x in gold};pd={str(int(x["Record_ID"])):x for x in predictions}
    if len(gd)!=len(gold) or len(pd)!=len(predictions) or gd.keys()!=pd.keys():raise ValueError("Duplicate or mismatched Record_ID values")
    ch=CHRF(word_order=2);rows=[];mts=[];refs=[];comet_data=[]
    for rid,g in gd.items():
        x=pd[rid];_,ga,_,_=construct_visible_gold(g["English_Author_Gold_Full"],g["Chinese_Reference"])
        pa=parse_prediction(x["Pred_English_Authors"]);match=[identity_match(a,b) for a,b in zip(ga,pa)]
        tp=sum(match);vol,issue,pages=vip(g["Volume_Issue_Pages_Gold"])
        mt=s(x["Pred_English_Title"]);ref=s(g["English_Title_Gold"]);mts.append(mt);refs.append(ref)
        rows.append({"Record_ID":rid,"Canonical visible-author exact accuracy":len(ga)==len(pa) and all(match),
                     "Strict bibliographic-form exact":[strict_author_form_normalize(a) for a in ga]==[strict_author_form_normalize(a) for a in pa],
                     "TP":tp,"FP":len(pa)-tp,"FN":len(ga)-tp,
                     "English journal mapping accuracy":basic(x["Pred_English_Journal"])==basic(g["English_Journal_Gold"]),
                     "Year accuracy":num(x["Pred_Year"])==g["Year_Gold"],"Volume accuracy":num(x["Pred_Volume"])==vol,
                     "Issue accuracy":num(x["Pred_Issue"])==issue,"Pages accuracy":basic(x["Pred_Pages"])==pages,
                     "Title resolution rate":bool(mt),"Title NEM":tnorm(mt)==tnorm(ref),"Mean chrF++":ch.sentence_score(mt,[ref]).score})
        comet_data.append({"src":g["Chinese_Title"],"mt":mt,"ref":ref})
    n=len(rows);metrics={"N":n}
    for k in rows[0]:
        if k not in {"Record_ID","TP","FP","FN"}:metrics[k]=sum(x[k] for x in rows)/n
    tp=sum(x["TP"] for x in rows);fp=sum(x["FP"] for x in rows);fn=sum(x["FN"] for x in rows)
    precision=tp/(tp+fp) if tp+fp else 0;recall=tp/(tp+fn) if tp+fn else 0
    metrics.update({"Micro precision":precision,"Micro recall":recall,"Micro F1":2*precision*recall/(precision+recall) if precision+recall else 0,
                    "TP":tp,"FP":fp,"FN":fn,"Corpus chrF++":ch.corpus_score(mts,[refs]).score,"Mean COMET":None})
    if comet_checkpoint:
        if not Path(comet_checkpoint).is_file():raise FileNotFoundError(comet_checkpoint)
        from comet import load_from_checkpoint
        model=load_from_checkpoint(str(comet_checkpoint))
        result=model.predict(comet_data,batch_size=8,gpus=0)
        metrics["Mean COMET"]=statistics.mean(float(x) for x in result.scores)
        for row,value in zip(rows,result.scores):row["COMET"]=float(value)
    return metrics,rows

def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--gold",required=True,type=Path);p.add_argument("--predictions",required=True,type=Path)
    p.add_argument("--output",type=Path);p.add_argument("--comet-checkpoint",type=Path)
    args=p.parse_args(argv);metrics,rows=evaluate(read_csv(args.gold),read_csv(args.predictions),comet_checkpoint=args.comet_checkpoint)
    payload={"metrics":metrics,"records":rows}
    if args.output:args.output.write_text(json.dumps(payload,ensure_ascii=False,indent=2),encoding="utf-8")
    print(json.dumps(metrics,ensure_ascii=False,indent=2))
if __name__=="__main__":main()

