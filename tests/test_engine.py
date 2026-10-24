import unittest,sys,json,tempfile
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from wa_engine import load_profile,recognize,merge
from wa_experience import report

class EngineTests(unittest.TestCase):
    def setUp(self):
        self.profile=load_profile(Path(__file__).resolve().parents[1]/'tools/profiles/school.json')
    def test_no_identity_fails_closed(self):
        self.assertIsNone(recognize(self.profile,{'size':[600,1000],'lines':[]})[0])
    def test_unknown_schema_key_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'bad.json';data=dict(self.profile);data['exec']='anything'
            p.write_text(json.dumps(data),encoding='utf-8')
            with self.assertRaises(Exception):load_profile(p)
    def test_duplicate_id_keeps_all_sources(self):
        a={'id':'x','title':'A','body':'A','fields':{},'field_confidence':{},'sources':[{'shot':'one'}],'issues':[]}
        b={**a,'sources':[{'shot':'two'}]}
        merged=merge([a],[b]);self.assertEqual(len(merged),1);self.assertEqual(len(merged[0]['sources']),2)
    def test_evidence_html_escapes_content(self):
        with tempfile.TemporaryDirectory() as d:
            row={'title':'<script>alert(1)</script>','body':'<img onerror=boom>','fields':{},'sources':[],'issues':[]}
            report(d,[row],{'stop_reason':'test'})
            text=(Path(d)/'index.html').read_text(encoding='utf-8')
            self.assertNotIn('<script>alert(1)',text);self.assertIn('&lt;script&gt;',text)
if __name__=='__main__':unittest.main()
