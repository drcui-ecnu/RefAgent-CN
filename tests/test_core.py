"""Offline behavior tests; network generation must never be invoked."""
import json, unittest
from pathlib import Path
from unittest.mock import patch
from refagent_cn import RefAgent
from refagent_cn.journal_kb import JournalKB
from refagent_cn.parser import ReferenceParser
from refagent_cn.scoring_helpers import identity_match

FIXTURE=json.loads((Path(__file__).resolve().parents[1]/'examples/synthetic_demo.json').read_text(encoding='utf-8'))

class CoreTests(unittest.TestCase):
    def test_offline_pipeline(self):
        with patch('urllib.request.urlopen',side_effect=AssertionError('Network forbidden in offline test')):
            result=RefAgent(FIXTURE['journal_kb'],FIXTURE['title_kb']).process(FIXTURE['reference'],shared_response=FIXTURE['shared_response'])
        self.assertEqual(result['Generation_Mode'],'cached_shared_response')
        self.assertTrue(result['Exact_Title_KB_Hit'])
        self.assertEqual(result['Full_V390']['title']['source'],'title_kb_verified_exact')
        self.assertEqual(result['Full_V390']['journal']['source'],'journal_kb_verified')
        self.assertTrue(result['Full_V390']['authors']['need_review'])
        self.assertTrue(result['Review_Required'])
        self.assertEqual(len(result['Citations']),5)
        self.assertIn('Zhang, S.',result['Citations']['apa_en'])
        self.assertIn('12(2)',result['Citations']['apa_en'])
        self.assertIn('示例',result['Citations']['gbt7714_bilingual'])

    def test_title_miss_and_unverified(self):
        title=dict(FIXTURE['title_kb'][0],verification_status='unresolved')
        result=RefAgent(FIXTURE['journal_kb'],[title]).process(FIXTURE['reference'],shared_response=FIXTURE['shared_response'])
        self.assertFalse(result['Exact_Title_KB_Hit'])
        self.assertTrue(result['Full_V390']['title']['need_review'])
        self.assertFalse(result['Full_V390']['title']['is_official'])

    def test_journal_no_alias_branch(self):
        kb=JournalKB([{'name_cn':'甲乙丙丁','name_en':'Example','alias_cn':['不同别名']}])
        self.assertEqual(kb.resolve('不同别名').match_type,'none')
        self.assertEqual(kb.resolve(' 甲乙丙丁 ').match_type,'exact')

    def test_fuzzy_candidate_not_adopted(self):
        name='示例图书馆学刊名称扩展示例名称ABC'
        ref='张三.学术引用示例研究[J].'+name+'X,2024,12(2):10-20.'
        records=[{'name_cn':name,'name_en':'Not to be adopted'}]
        self.assertEqual(JournalKB(records).resolve(name+'X').match_type,'fuzzy')
        result=RefAgent(records,[]).process(ref,shared_response=FIXTURE['shared_response'])
        self.assertEqual(result['Full_V390']['journal']['value'],'Example Generated Journal')
        self.assertTrue(result['Full_V390']['journal']['need_review'])

    def test_missing_generation_is_explicit(self):
        result=RefAgent().process(FIXTURE['reference'])
        self.assertFalse(result['Generation_Available'])
        self.assertEqual(result['Full_V390']['title']['value'],'')
        self.assertTrue(result['Review_Required'])

    def test_incomplete_reference_and_identity(self):
        result=ReferenceParser().parse('invalid reference',ref_id='bad')
        self.assertFalse(result.get('title_cn'))
        self.assertTrue(identity_match('Ke P.','Ke Ping'))
        self.assertFalse(identity_match('Lyu P.','Lv Ping'))
        self.assertFalse(identity_match('Ke P.','Ke Bing'))

    def test_online_is_opt_in(self):
        with patch.dict('os.environ',{'DEEPSEEK_API_KEY':''}):
            with self.assertRaises(RuntimeError):RefAgent().process(FIXTURE['reference'],online=True)

if __name__=='__main__':unittest.main()

