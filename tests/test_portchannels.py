import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.update(APIC_USER='test', APIC_PASS='test', PYTHON_DOTENV_DISABLED='1')
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import app as reports


def obj(kind, **attr):return {kind:{'attributes':attr}}
def port(node,pod='1',iface='eth1/1'):return f'topology/pod-{pod}/node-{node}/sys/phys-[{iface}]'
def pc(node,number='po10',pod='1',name='PG',member=True):
    value=obj('pcAggrIf',dn=f'topology/pod-{pod}/node-{node}/sys/aggr-[{number}]',id=number,name=name,adminSt='up',pcMode='active')
    value['pcAggrIf']['children']=[obj('ethpmAggrIf',operSt='up')]
    if member:value['pcAggrIf']['children'] += [obj('pcRsMbrIfs',tDn=port(node,pod))]*2
    return value
def logical(pair='101-102',pod='1',name='PG',kind='node'):
    path=f'topology/pod-{pod}/{"protpaths" if kind=="node" else "paths"}-{pair}/pathep-[{name}]'
    return obj('fabricPathEp',dn=path,name=name,lagT=kind)


class PortchannelTests(unittest.TestCase):
    def setUp(self):
        reports._data_cache.clear();self.client=reports.app.test_client()
        self.pcs=[pc('101'),pc('102',number='po27')]
        self.paths=[logical()]
        self.ports={'PG':[port('101'),port('102')]}
        self.fail_path=False;self.fail_deploy=False
        block=patch.object(reports.session,'request',side_effect=AssertionError('Network forbidden'))
        block.start();self.addCleanup(block.stop)
        mock=patch.object(reports,'apic_get',side_effect=self.get)
        self.get_mock=mock.start();self.addCleanup(mock.stop)
        collect=patch.object(reports,'_collect_acc_ports',side_effect=self.collect)
        self.collect_mock=collect.start();self.addCleanup(collect.stop)

    def get(self,path,params=None):
        if 'pcAggrIf' in path:return self.pcs
        if 'fabricPathEp' in path:
            if self.fail_path:raise RuntimeError('simulated')
            return self.paths
        if 'l1PhysIf' in path:return [obj('l1PhysIf',dn=dn,adminSt='up',descr='Server',speed='inherit') for ports in self.ports.values() for dn in ports]
        if 'ethpmPhysIf' in path:return [obj('ethpmPhysIf',dn=dn+'/phys',operSt='down' if '/node-102/' in dn else 'up',operSpeed='10G') for ports in self.ports.values() for dn in ports]
        self.fail(path)

    def collect(self,pg,ports):
        if self.fail_deploy:raise RuntimeError('simulated')
        for dn in self.ports.get(pg.split('accbundle-',1)[1],[]):ports.append({'dn':dn})

    def result(self,**params):
        response=self.client.get('/api/portchannel_overview',query_string=params)
        self.assertEqual(response.status_code,200,response.text)
        return response.json

    def test_vpc_groups_exact_peers_with_different_local_po_numbers(self):
        rows=self.result();self.assertEqual(len(rows),1)
        group=rows[0];self.assertEqual(group['kind'],'vpc');self.assertEqual(group['coverage'],'complete')
        self.assertEqual([n['aggregate']['id'] for n in group['nodes']],['po10','po27'])
        self.assertEqual(group['member_counts'],{'total':2,'up':1,'down':1,'other':0})
        self.assertEqual(group['nodes'][0]['members'][0]['speed'],'10G')

    def test_same_name_different_peer_pairs_and_pods_stay_separate(self):
        self.paths += [logical('103-104'),logical(pod='2')]
        self.pcs += [pc('103'),pc('104'),pc('101',pod='2'),pc('102',pod='2')]
        self.ports['PG'] += [port('103'),port('104'),port('101','2'),port('102','2')]
        groups=self.result();self.assertEqual(len(groups),3)
        self.assertTrue(all(g['coverage']=='complete' for g in groups))
        self.assertEqual(self.collect_mock.call_count,1)

    def test_same_po_number_uses_logical_pair_and_legacy_page_is_consolidated(self):
        self.pcs=[pc('101','po14'),pc('102','po14')]
        rows=self.result()
        self.assertEqual(len(rows),1)
        self.assertEqual([n['aggregate']['id'] for n in rows[0]['nodes']],['po14','po14'])
        page=self.client.get('/portchannels')
        self.assertIn('Uma linha por grupo',page.text)
        self.assertIn('/static/portchannels.js',page.text)

    def test_node_state_filters_keep_both_peers_and_export_matches(self):
        self.pcs[1]['pcAggrIf']['children'][0]=obj('ethpmAggrIf',operSt='down')
        rows=self.result(node='102',state='down')
        self.assertEqual(len(rows),1)
        self.assertEqual(len(rows[0]['nodes']),2)
        self.assertEqual(self.result(node='101',state='down'),[])
        csv=self.client.get('/export_csv/portchannel_overview?node=102&state=down')
        self.assertIn('po10',csv.text)
        self.assertIn('po27',csv.text)

    def test_single_switch_pc_is_not_a_vpc(self):
        self.paths=[logical('101',kind='link')];self.pcs=[pc('101')]
        row=self.result()[0];self.assertEqual(row['kind'],'pc');self.assertEqual(len(row['nodes']),1)

    def test_same_name_without_member_evidence_is_not_merged(self):
        self.ports['PG']=[]
        self.pcs=[pc('101',member=False),pc('102',member=False)]
        rows=self.result();self.assertEqual(len(rows),3)
        vpc=next(g for g in rows if g['kind']=='vpc')
        self.assertEqual(vpc['coverage'],'partial')
        self.assertTrue(all(n['aggregate'] is None for n in vpc['nodes']))

    def test_missing_peer_is_shown_not_hidden(self):
        self.pcs=[pc('101')]
        row=self.result()[0];self.assertEqual(row['coverage'],'partial')
        self.assertEqual(row['nodes'][1]['mapping'],'unresolved')
        self.assertIsNone(row['nodes'][1]['aggregate'])
        self.assertEqual(len(row['nodes'][1]['members']),1)

    def test_multiple_candidates_are_ambiguous(self):
        self.pcs.append(pc('101','po20'))
        row=next(g for g in self.result() if g['kind']=='vpc')
        self.assertEqual(row['nodes'][0]['mapping'],'ambiguous')
        self.assertIsNone(row['nodes'][0]['aggregate'])

    def test_same_aggregate_claimed_by_two_paths_is_never_double_assigned(self):
        self.paths.append(logical(name='OTHER'));self.ports['OTHER']=self.ports['PG'][:]
        rows=self.result()
        self.assertEqual(sum(g['kind']=='unassociated' for g in rows),2)
        for group in rows:
            if group['kind']=='vpc':self.assertTrue(all(n['mapping']=='ambiguous' for n in group['nodes']))

    def test_tskey_member_and_unknown_operational_state(self):
        self.pcs[0]['pcAggrIf']['children']=[obj('pcRsMbrIfs',tSKey='eth1/1')]
        row=self.result()[0]
        self.assertEqual(row['nodes'][0]['aggregate']['oper_state'],'')
        self.assertEqual(row['nodes'][0]['members'][0]['dn'],port('101'))

    def test_path_failure_retains_separate_aggregates_and_cached_warning(self):
        self.fail_path=True
        rows=self.result();self.assertEqual(len(rows),2);self.assertTrue(all(g['kind']=='unassociated' for g in rows))
        cached=self.client.get('/api/portchannel_overview')
        self.assertIn('Coleta parcial',cached.headers['X-Collection-Warnings'])
        self.assertEqual(cached.headers['X-Data-Cache'],'hit')

    def test_deployment_failure_is_visible(self):
        self.fail_deploy=True
        response=self.client.get('/api/portchannel_overview')
        self.assertEqual(response.status_code,200)
        self.assertIn('resolver',response.headers['X-Collection-Warnings'])

    def test_empty_deployment_correlates_exact_name_and_topology(self):
        self.ports = {}
        response = self.client.get('/api/portchannel_overview')
        self.assertEqual(response.status_code, 200)
        logical_groups = [g for g in response.json if g['kind'] == 'vpc']
        self.assertEqual(len(response.json),1)
        self.assertEqual(logical_groups[0]['coverage'], 'correlated')
        self.assertTrue(all(n['mapping']=='inferred' for n in logical_groups[0]['nodes']))
        self.assertEqual([n['aggregate']['id'] for n in logical_groups[0]['nodes']],['po10','po27'])
        self.assertTrue(all(n['members'] for n in logical_groups[0]['nodes']))
        self.assertIn('deployment', response.headers['X-Collection-Warnings'])
        self.assertEqual(self.collect_mock.call_args.args[0], 'uni/infra/funcprof/accbundle-PG')

    def test_fallback_does_not_merge_other_pairs_pods_or_duplicate_candidates(self):
        self.ports={}
        self.paths += [logical('103-104'),logical(pod='2')]
        self.pcs += [pc('103'),pc('104'),pc('101',pod='2'),pc('102',pod='2')]
        rows=self.result()
        self.assertEqual(len(rows),3)
        self.assertTrue(all(g['coverage']=='correlated' for g in rows))
        self.pcs.append(pc('101','po99'))
        rows=self.result(refresh='1')
        group=next(g for g in rows if g['id']==self.paths[0]['fabricPathEp']['attributes']['dn'])
        self.assertEqual(group['nodes'][0]['mapping'],'ambiguous')
        self.assertEqual(sum(g['kind']=='unassociated' for g in rows),2)

    def test_fallback_never_overrides_conflicting_deployment(self):
        self.ports={'PG':[port('101',iface='eth1/99'),port('102',iface='eth1/99')]}
        group=next(g for g in self.result() if g['kind']=='vpc')
        self.assertTrue(all(n['aggregate'] is None for n in group['nodes']))

    def test_filters_csv_and_refresh(self):
        self.assertEqual(self.result(q='PO27')[0]['kind'],'vpc')
        self.assertEqual(self.result(pod='2'),[])
        self.assertEqual(self.result(kind='pc'),[])
        self.assertEqual(len(self.result(path=self.paths[0]['fabricPathEp']['attributes']['dn'])),1)
        self.assertEqual(self.collect_mock.call_count,1)
        self.result(refresh='1');self.assertEqual(self.collect_mock.call_count,2)
        csv=self.client.get('/export_csv/portchannel_overview?q=po27')
        self.assertEqual(csv.status_code,200);self.assertIn('po27',csv.text);self.assertIn('po10',csv.text)
        empty=self.client.get('/export_csv/portchannel_overview?pod=2')
        self.assertNotIn('po27',empty.text)

    def test_mandatory_inventory_failure_is_500(self):
        self.get_mock.side_effect=RuntimeError('simulated')
        self.assertEqual(self.client.get('/api/portchannel_overview').status_code,500)


if __name__=='__main__':unittest.main()
