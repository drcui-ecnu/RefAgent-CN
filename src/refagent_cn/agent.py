"""Portable entry point around the preserved single-response production hybrid."""
from __future__ import annotations
import argparse, json, os, re
from pathlib import Path
from typing import Any
from .source_aware_hybrid import SourceAwareHybridV390
from .style_renderer import StyleRenderer
from .parser import ReferenceParser, english_author_to_apa
from .llm_client import LLMClient

def read_records(path):
    if path is None: return []
    rows=json.loads(Path(path).read_text(encoding="utf-8-sig"))
    if not isinstance(rows,list):raise ValueError("Knowledge base must be a JSON array")
    return rows

class RefAgent:
    """One shared LLM response, deterministic correction, and explicit provenance.

    Cached responses are supplied by the caller, never inferred to be official.
    This wrapper is new packaging; parser and hybrid decision rules are preserved.
    """
    def __init__(self, journal_records=None, title_records=None, *, templates=None):
        self.hybrid=SourceAwareHybridV390(journal_records or [],title_records or [])
        self.renderer=StyleRenderer(templates or {})

    def process(self, reference: str, *, shared_response=None, record_id="demo", online=False, prompt_path=None):
        if not str(reference).strip():raise ValueError("Reference is empty")
        if online and shared_response is not None:raise ValueError("Choose cached or online generation, not both")
        transport={}
        if online:
            if not os.getenv("DEEPSEEK_API_KEY", "").strip():raise RuntimeError("Set DEEPSEEK_API_KEY before explicitly enabling online mode")
            if prompt_path is None:raise ValueError("Supply the frozen shared-generation prompt path")
            text=Path(prompt_path).read_text(encoding="utf-8")
            system=text.split("## System prompt",1)[1].split("## User prompt",1)[0].strip()
            user=text.split("## User prompt",1)[1].strip().replace("{{Chinese_Reference}}",reference)
            client=LLMClient({"provider":"deepseek","model":"deepseek-chat","temperature":.2,"max_tokens":512,"timeout":120,"enabled":True})
            content=client._request_chat([{"role":"system","content":system},{"role":"user","content":user}],temperature=.2,max_tokens=512)
            if content is None:raise RuntimeError(client.last_error or "Empty API response")
            cleaned=re.sub(r"^```(?:json)?\s*|\s*```$","",content.strip(),flags=re.I|re.S)
            try:shared_response=json.loads(cleaned)
            except json.JSONDecodeError:
                match=re.search(r"\{.*\}",cleaned,re.S)
                if not match:raise ValueError("API output is not a JSON object")
                shared_response=json.loads(match.group(0))
            transport=dict(client.last_response_meta)
            mode="online_shared_generation"
        elif shared_response is not None:mode="cached_shared_response"
        else:mode="no_generation_available"
        if shared_response is None:shared_response={}
        if not isinstance(shared_response,dict):raise ValueError("Shared response must be a JSON object")
        result=self.hybrid.derive(str(record_id),reference,shared_response)
        fields=result["Full_V390"]
        parsed=ReferenceParser().parse(reference,ref_id=str(record_id))
        ref=dict(parsed)
        ref.update({"authors_en":fields["authors"]["value"],"authors_apa":[english_author_to_apa(x) for x in fields["authors"]["value"]],
                    "title_en":fields["title"]["value"],"journal_en":fields["journal"]["value"],
                    **{k:str(fields[k]["value"] or "") for k in ("year","volume","issue","pages")}})
        result["Citations"]=self.renderer.render_all(ref)
        result["Generation_Mode"]=mode
        result["Generation_Available"]=bool(shared_response)
        result["Transport_Metadata"]=transport
        return result

def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--reference",required=True)
    p.add_argument("--journal-kb",type=Path)
    p.add_argument("--title-kb",type=Path)
    p.add_argument("--shared-response",type=Path)
    p.add_argument("--online",action="store_true",help="Explicitly permits one paid API request")
    p.add_argument("--prompt",type=Path)
    args=p.parse_args(argv)
    response=json.loads(args.shared_response.read_text(encoding="utf-8")) if args.shared_response else None
    agent=RefAgent(read_records(args.journal_kb),read_records(args.title_kb))
    print(json.dumps(agent.process(args.reference,shared_response=response,online=args.online,prompt_path=args.prompt),ensure_ascii=False,indent=2))
if __name__=="__main__":main()

