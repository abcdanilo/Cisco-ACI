import sys
import unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from aci_l3out import inventory,select

class L3OutTests(unittest.TestCase):
    def test_inventory_includes_empty_l3out_and_tenant(self):
        def get(path):
            if 'fvTenant' in path:return [{'fvTenant':{'attributes':{'name':'Empty'}}}]
            return [{'l3extOut':{'attributes':{'dn':'uni/tn-A/out-SAME'}}},
                    {'l3extOut':{'attributes':{'dn':'uni/tn-B/out-SAME'}}}]
        result=inventory(get,lambda:[{'tenant':'B','l3out':'SAME','instp':'EPG','ip':'10.0.0.0/24','scope':''}])
        self.assertEqual(result['tenants'],['A','B','Empty'])
        self.assertEqual(len(result['l3outs']),2)
        self.assertEqual(select(result['rows'],{'tenant':'A','l3out':'SAME'}),[])
        self.assertEqual(len(select(result['rows'],{'tenant':'B','q':'epg'})),1)
