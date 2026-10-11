"""Small bilingual interface for the preserved hybrid, not the legacy UI."""
import json
from pathlib import Path
import streamlit as st
from refagent_cn import RefAgent
from refagent_cn.agent import read_records
from refagent_cn.pdf_reader import pdf_bytes_to_refs_and_title_entries

ROOT=Path(__file__).resolve().parent
FIXTURE=json.loads((ROOT/'examples/synthetic_demo.json').read_text(encoding='utf-8'))
TEXT={
 'English':{'heading':'RefAgent-CN','notice':FIXTURE['notice'],'reference':'Chinese reference','journal':'Journal KB JSON path (optional)','title':'Title KB JSON path (optional)','cached':'Shared response JSON','online':'Enable one online API request (requires DEEPSEEK_API_KEY)','run':'Process reference','review':'Human review required','mode':'Generation mode','pdf':'PDF text-layer input (optional)','empty':'No reliable reference extracted; paste a reference manually.'},
 '中文':{'heading':'RefAgent-CN','notice':'示例为虚构测试数据，不是正式知识库或模型响应。示例中的官方标志仅用于演示接口契约。','reference':'中文参考文献','journal':'期刊知识库JSON路径（可选）','title':'题名知识库JSON路径（可选）','cached':'共享响应JSON','online':'启用一次在线API请求（需DEEPSEEK_API_KEY）','run':'处理参考文献','review':'需要人工复核','mode':'生成方式','pdf':'PDF文本层输入（可选）','empty':'未可靠提取引用，请手工粘贴。'}
}
st.set_page_config(page_title='RefAgent-CN',layout='wide')
language=st.selectbox('Language / 语言',['English','中文'],key='language');t=TEXT[language]
st.title(t['heading']);st.caption(t['notice'])
journal_path=st.text_input(t['journal'],key='journal_path');title_path=st.text_input(t['title'],key='title_path')
uploaded=st.file_uploader(t['pdf'],type=['pdf'])
default=FIXTURE['reference']
if uploaded is not None:
    extracted=pdf_bytes_to_refs_and_title_entries(uploaded.getvalue(),journal_kb=read_records(journal_path) if journal_path else [])
    if extracted['warning']:st.warning(extracted['warning'])
    if extracted['references']:default=extracted['references'][0]
    else:st.warning(t['empty'])
reference=st.text_area(t['reference'],value=default,key='reference')
cached=st.text_area(t['cached'],value=json.dumps(FIXTURE['shared_response'],ensure_ascii=False),key='cached')
online=st.checkbox(t['online'],value=False,key='online')
if st.button(t['run'],key='process'):
    try:
        journals=read_records(journal_path) if journal_path else FIXTURE['journal_kb']
        titles=read_records(title_path) if title_path else FIXTURE['title_kb']
        result=RefAgent(journals,titles).process(reference,shared_response=None if online else json.loads(cached),online=online,prompt_path=ROOT/'prompts/shared_generation_v390.md')
        st.write(t['mode']+': '+result['Generation_Mode'])
        if result['Review_Required']:st.warning(t['review'])
        st.subheader('Field provenance / 字段来源');st.json(result['Full_V390'])
        for name,citation in result['Citations'].items():st.text_area(name,value=citation,key='citation_'+name)
    except Exception as exc:st.error(str(exc))

