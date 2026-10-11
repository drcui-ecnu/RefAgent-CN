"""Synthetic evaluator test; no formal metrics are embedded in this test."""
import unittest
from refagent_cn.evaluate import evaluate

class EvaluationTests(unittest.TestCase):
    def test_exact_and_form_difference(self):
        gold=[{'Record_ID':'1','Chinese_Reference':'张三.示例研究[J].示例学刊,2024,12(2):10-20.',
               'Chinese_Title':'示例研究','English_Author_Gold_Full':'Zhang S.','English_Title_Gold':'Example Study',
               'English_Journal_Gold':'Example Journal','Year_Gold':'2024','Volume_Issue_Pages_Gold':'12(2): 10-20'}]
        pred=[{'Record_ID':'1','Pred_English_Authors':'["Zhang San"]','Pred_English_Title':'Example Study',
               'Pred_English_Journal':'Example Journal','Pred_Year':'2024','Pred_Volume':'12','Pred_Issue':'2','Pred_Pages':'10-20'}]
        metrics,_=evaluate(gold,pred)
        self.assertEqual(metrics['Canonical visible-author exact accuracy'],1)
        self.assertEqual(metrics['Strict bibliographic-form exact'],0)
        self.assertEqual(metrics['Title NEM'],1)
        self.assertEqual(metrics['Mean chrF++'],100)
        self.assertIsNone(metrics['Mean COMET'])
        pred[0]['Pred_English_Title']='Different output'
        changed,_=evaluate(gold,pred)
        self.assertEqual(changed['Title NEM'],0)
        self.assertLess(changed['Mean chrF++'],100)

    def test_duplicate_record_id_fails(self):
        with self.assertRaises(ValueError):evaluate([{'Record_ID':'1'},{'Record_ID':'1'}],[{'Record_ID':'1'},{'Record_ID':'2'}])

if __name__=='__main__':unittest.main()
