import unittest
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from aci_access import collect_access, usage_tree

DN='uni/infra/funcprof/accportgrp-PG'
def mo(cls,children=None,**attr):
    return {cls:{'attributes':attr,'children':children or []}}

class AccessTests(unittest.TestCase):
    def test_exact_links_and_ranges(self):
        profiles=[mo('infraAccPortP',dn='uni/infra/accportprof-P',name='P',children=[
            mo('infraHPortS',name='S',rn='hports-S-typ-range',children=[
                mo('infraRsAccBaseGrp',tDn=DN,state='formed'),
                mo('infraPortBlk',fromCard='1',toCard='1',fromPort='2',toPort='4')])])]
        nodes=[mo('infraNodeP',name='Leaf',dn='uni/infra/nprof-L',children=[
            mo('infraRsAccPortP',tDn='uni/infra/accportprof-P',state='formed'),
            mo('infraLeafS',name='range',children=[mo('infraNodeBlk',from_='101',to_='102')])])]
        result=usage_tree(DN,profiles,nodes)
        self.assertEqual(result[0]['ports'][0]['toPort'],'4')
        self.assertEqual(result[0]['switch_profiles'][0]['leaves'][0]['ranges'][0]['from'],'101')
        self.assertEqual(usage_tree(DN+'other',profiles,nodes),[])
        nodes[0]['infraNodeP']['children'][0]['infraRsAccPortP']['attributes']['tDn']+='other'
        self.assertEqual(usage_tree(DN,profiles,nodes)[0]['switch_profiles'],[])

    def test_values_defaults_and_partial_failure(self):
        def get(path,params=None):
            if 'accportgrp' in path:
                return [mo('infraAccPortGrp',name='PG',children=[
                    mo('infraRsCdpIfPol',tDn='uni/infra/cdpIfP-default',state='formed',stateQual='default-target'),
                    mo('infraRsLldpIfPol',tDn='uni/infra/lldpIfP-missing')])]
            if 'cdpIfP' in path:return [mo('cdpIfPol',name='default',adminSt='disabled')]
            if 'lldpIfP' in path:raise RuntimeError('unavailable')
            return []
        warnings=[]
        data=collect_access(DN,get,warnings.append)
        cdp=next(p for p in data['policies'] if p['label']=='CDP')
        self.assertTrue(cdp['default'])
        self.assertEqual(cdp['values']['adminSt'],'disabled')
        self.assertFalse(next(p for p in data['policies'] if p['label']=='LLDP')['available'])
        self.assertEqual(len(warnings),1)
