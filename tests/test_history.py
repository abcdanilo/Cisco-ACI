import sys
import unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from aci_history import query, collect

class HistoryTests(unittest.TestCase):
    def args(self,**kw):
        return dict(start='2026-09-28T10:00:00-03:00',end='2026-09-28T11:00:00-03:00',**kw)

    def test_utc_exact_filter_and_pagination(self):
        cls,p,_,_=query(self.args(dn='uni/tn-a',page='2'))
        self.assertEqual(cls,'aaaModLR')
        self.assertIn('13:00:00+00:00',p['query-target-filter'])
        self.assertIn('eq(aaaModLR.affected,"uni/tn-a")',p['query-target-filter'])
        self.assertEqual((p['page'],p['page-size']),(2,50))

    def test_invalid_inputs(self):
        for args in [self.args(kind='bad'),self.args(page='-1'),dict(start='2026-01-01',end='2026-09-28'),
                     dict(start='2026-01-01T00:00:00Z',end='2026-09-28T00:00:00Z'),
                     dict(start='2026-09-29T00:00:00Z',end='2026-09-28T00:00:00Z')]:
            with self.assertRaises(ValueError):query(args)

    def test_literal_partial_search(self):
        import json
        _,params,_,_=query(self.args(q='ACC.[1]'))
        self.assertIn('[aA][cC][cC]',params['query-target-filter'])
        self.assertIn('wcard(aaaModLR.affected,',params['query-target-filter'])
        self.assertIn(json.dumps('[aA][cC][cC]\\.\\[1\\]'),params['query-target-filter'])
        with self.assertRaises(ValueError):query(self.args(q='a'*121))

    def test_bounded_and_safe_projection(self):
        calls=[]
        def get(path,params):
            calls.append((path,params))
            return [{'eventRecord':{'attributes':{'descr':'sample','changeSet':'internal data'}}}]*50
        result=collect(self.args(kind='events'),get)
        self.assertEqual(len(calls),1)
        self.assertTrue(result['has_more'])
        self.assertNotIn('changeSet',result['rows'][0])
        self.assertFalse(collect(self.args(),lambda *a:[])['has_more'])
