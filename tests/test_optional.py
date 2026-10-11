"""Tests for optional interface and PDF dependencies; all are offline."""
import importlib.util, unittest
from pathlib import Path
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]

class OptionalTests(unittest.TestCase):
    @unittest.skipUnless(importlib.util.find_spec('streamlit'),'Install the web extra')
    def test_bilingual_interface(self):
        from streamlit.testing.v1 import AppTest
        with patch('urllib.request.urlopen',side_effect=AssertionError('Network forbidden')):
            app=AppTest.from_file(str(ROOT/'app.py')).run(timeout=20)
            self.assertFalse(app.exception)
            app.button(key='process').click().run(timeout=20)
            self.assertFalse(app.exception)
            self.assertEqual(len([a for a in app.text_area if a.key.startswith('citation_')]),5)
            self.assertTrue(app.warning)
            app.selectbox(key='language').select('中文').run(timeout=20)
            app.button(key='process').click().run(timeout=20)
            self.assertFalse(app.exception)
            self.assertIn('需要人工复核',app.warning[0].value)
            self.assertEqual(len([a for a in app.text_area if a.key.startswith('citation_')]),5)

    @unittest.skipUnless(importlib.util.find_spec('fitz'),'Install the pdf extra')
    def test_pdf_selected_pages(self):
        import fitz
        from refagent_cn.pdf_reader import extract_pdf_text
        doc=fitz.open()
        for i in range(12):
            page=doc.new_page()
            page.insert_text((72,72),'文本提取测试示例中文字符用于选页功能验证编号'+str(i+1),fontname='china-s')
        raw=doc.tobytes();doc.close()
        text,warning=extract_pdf_text(raw)
        self.assertFalse(warning)
        self.assertIn('--- PDF_PAGE_1 ---',text)
        self.assertIn('--- PDF_PAGE_12 ---',text)
        self.assertNotIn('--- PDF_PAGE_6 ---',text)
        self.assertNotIn('--- PDF_PAGE_7 ---',text)
        self.assertEqual(text.count('--- PDF_PAGE_'),10)

if __name__=='__main__':unittest.main()
