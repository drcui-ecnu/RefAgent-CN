"""Offline, synthetic demonstration: no API key and no formal Gold required."""
import json
from pathlib import Path
from refagent_cn import RefAgent

def run_demo():
    fixture=json.loads((Path(__file__).with_name("synthetic_demo.json")).read_text(encoding="utf-8"))
    result=RefAgent(fixture["journal_kb"],fixture["title_kb"]).process(fixture["reference"],shared_response=fixture["shared_response"])
    result["Demo_Notice"]=fixture["notice"]
    return result

if __name__=="__main__":print(json.dumps(run_demo(),ensure_ascii=False,indent=2))

