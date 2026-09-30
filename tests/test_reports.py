"""Offline regression tests: no APIC credentials or network required."""
import os
import csv
import io
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.update(APIC_USER='test', APIC_PASS='test', PYTHON_DOTENV_DISABLED='1')
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import app as reports


def obj(kind, **attributes):
    return {kind: {'attributes': attributes}}


DN = 'topology/pod-1/node-101/sys/phys-[eth1/1]'


class ReportTests(unittest.TestCase):
    def test_generic_csv_escapes_formulas_after_serializing_lists(self):
        values=['=1+1','+SUM(A1:A2)','-1+2','@SUM(A1:A2)','  =1+1',
                ['=1+1','plain'],['10.0.0.1/24','2001:db8::1/64'],'normal',None]
        config={'fn':lambda:[{'value':value} for value in values],
                'fields':[('Value','value')],'filename':'safe.csv'}
        with patch.dict(reports.CSV_REGISTRY,{'csv_safety_test':config}):
            response=self.client.get('/export_csv/csv_safety_test')
        self.assertEqual(response.status_code,200)
        self.assertEqual(response.headers['Content-Disposition'],'attachment; filename=safe.csv')
        self.assertEqual(response.mimetype,'text/csv')
        parsed=list(csv.reader(io.StringIO(response.text)))
        self.assertEqual(parsed,[['Value'],["'=1+1"],["'+SUM(A1:A2)"],["'-1+2"],
            ["'@SUM(A1:A2)"],["'  =1+1"],["'=1+1; plain"],
            ['10.0.0.1/24; 2001:db8::1/64'],['normal'],['']])

    def setUp(self):
        reports._data_cache.clear()
        self.no_network = patch.object(reports.session, 'request', side_effect=AssertionError('Network forbidden'))
        self.no_network.start()
        self.addCleanup(self.no_network.stop)
        self.client = reports.app.test_client()

    def test_tls_boolean_and_ca_path(self):
        for value in ('true', 'True', ' 1 ', 'yes'):
            self.assertIs(reports.parse_verify(value), True)
        for value in ('false', 'False', '0', ''):
            self.assertIs(reports.parse_verify(value), False)
        self.assertEqual(reports.parse_verify('/etc/ssl/aci.pem'), '/etc/ssl/aci.pem')

    def test_bd_subnets_are_direct_children_and_preserve_empty_bds(self):
        bd=obj('fvBD',dn='uni/tn-T/BD-A',name='A')
        bd['fvBD']['children']=[obj('fvSubnet',ip='10.0.0.1/24'),
            obj('fvSubnet',ip='2001:db8::1/64'),obj('fvSubnet',ip='10.0.0.1/24'),
            obj('fvSubnet'),obj('fvRsCtx',tnFvCtxName='VRF')]
        with patch.object(reports,'apic_get',return_value=[bd,obj('fvBD',dn='uni/tn-T/BD-B',name='B')]) as get:
            rows=self.client.get('/api/bds').json
            self.assertEqual(rows[0]['subnets'],['10.0.0.1/24','2001:db8::1/64'])
            self.assertEqual(rows[1]['subnets'],[])
            self.assertEqual(get.call_args.kwargs['params'],{'rsp-subtree':'children','rsp-subtree-class':'fvSubnet'})
            csv=self.client.get('/export_csv/bds')
            self.assertIn('Subnets',csv.text)
            self.assertIn('10.0.0.1/24; 2001:db8::1/64',csv.text)

    def test_physical_dn_preserves_interface(self):
        self.assertEqual(reports.physical_dn(DN + '/phys'), DN)
        self.assertEqual(reports.physical_dn(DN), DN)

    def test_access_status_and_speed_join(self):
        def get(path, params=None):
            if 'infraAccPortGrp' in path: return [obj('infraAccPortGrp', name='PG')]
            if 'l1PhysIf' in path: return [obj('l1PhysIf', dn=DN, speed='inherit')]
            if 'ethpmPhysIf' in path: return [obj('ethpmPhysIf', dn=DN+'/phys', operSt='up', operSpeed='10G')]
            self.fail(path)
        def collect(acc, ports):
            ports.append(dict(acc=acc, pod='1', node='101', iface='eth1/1', dn=DN))
        with patch.object(reports, 'apic_get', side_effect=get), patch.object(reports, '_collect_acc_ports', side_effect=collect):
            row = self.client.get('/api/acc_ports').json[0]
        self.assertEqual((row['status'], row['speed']), ('up', '10G'))

    def test_access_group_visible_without_deployment(self):
        group = {'infraAccPortGrp': {'attributes': {'name':'PG','dn':'uni/infra/funcprof/accportgrp-PG'},
                 'children':[obj('infraRsAttEntP',tDn='uni/infra/attentp-AEP'),
                             obj('infraRsCdpIfPol',tDn='uni/infra/cdpIfP-default',state='formed')]}}
        def get(path, params=None):
            return [group] if 'infraAccPortGrp' in path else []
        with patch.object(reports,'apic_get',side_effect=get), patch.object(reports,'_collect_acc_ports'):
            response=self.client.get('/api/acc_ports')
        self.assertEqual(response.status_code,200)
        row=response.json[0]
        self.assertEqual(row['acc'],'PG')
        self.assertEqual(row['status'],'-')
        self.assertIn('não informada',row['path'])
        self.assertIn('attentp-AEP',row['aep'])
        self.assertIn('cdpIfP-default',row['policies'])

    def test_fault_scope_uses_dn_boundary(self):
        self.assertTrue(reports.fault_matches({'dn':DN+'/phys/fault-F1'},DN))
        self.assertTrue(reports.fault_matches({'affected':DN},DN))
        self.assertFalse(reports.fault_matches({'dn':DN+'0/fault-F1'},DN))
        self.assertFalse(reports.fault_matches({'affected':DN+'suffix'},DN))
        self.assertEqual(self.client.get('/api/object_faults?dn=invalid').status_code,400)
        with patch.object(reports,'get_faults',return_value=[{'dn':DN+'/fault-F1'},{'dn':DN+'suffix/fault-F2'}]):
            response=self.client.get('/api/object_faults',query_string={'dn':DN})
        self.assertEqual(response.status_code,200)
        self.assertEqual(len(response.json),1)

    def test_l3out_dn_segments_and_storage_filter(self):
        dn='uni/tn-out-EXAMPLE/out-REAL/instP-EXT/extsubnet-[10.0.0.0/24]'
        self.assertEqual(reports.extract_tenant_l3out_instp_from_dn(dn),('out-EXAMPLE','REAL','EXT'))
        rows=[obj('l3extSubnet',dn='uni/tn-TN_STORAGE-OFFLOAD/out-OTHER/instP-EXT/extsubnet-[10.0.0.0/24]',ip='10.0.0.0/24',scope='import-security')]
        with patch.object(reports,'apic_get',return_value=rows):
            self.assertEqual(len(self.client.get('/api/l3out_subnets').json),1)
            self.assertEqual(self.client.get('/api/l3out_storage_offload').status_code,404)
            self.assertEqual(self.client.get('/l3out_storage_offload').location,'/l3out_explorer')

    def test_up_requires_operational_state_and_full_includes_admin_down(self):
        physical = [obj('l1PhysIf', dn=DN+str(i), adminSt=admin, switchingSt='enabled')
                    for i, admin in enumerate(('up', 'up', 'down'))]
        def get(path, params=None):
            if 'ethpmPhysIf' in path:
                return [obj('ethpmPhysIf', dn=DN+str(i)+'/phys', operSt=state)
                        for i, state in enumerate(('down', 'up', 'down'))]
            if params: return physical[:2]
            return physical
        with patch.object(reports, 'apic_get', side_effect=get):
            up = self.client.get('/api/interfaces/up').json
            full = self.client.get('/api/interfaces/up_full').json
        self.assertEqual(len(up), 1)
        self.assertEqual(up[0]['dn'], DN+'1')
        self.assertEqual(len(full), 3)
        self.assertEqual((full[2]['adminSt'], full[2]['status']), ('down', 'down'))

    def test_same_portchannel_on_different_nodes_not_merged(self):
        rows = [obj('pcAggrIf', dn=f'topology/pod-1/node-{node}/sys/aggr-[po1]', name='PG', id='po1') for node in (101,102)]
        with patch.object(reports, 'apic_get', return_value=rows):
            data = self.client.get('/api/portchannels').json
        self.assertEqual(len(data), 2)
        self.assertEqual({r['node'] for r in data}, {'101', '102'})

    def test_same_mac_ip_in_different_tenants_retained(self):
        rows = []
        for tenant in ('A', 'B'):
            row = obj('fvCEp', dn=f'uni/tn-{tenant}/ap-app/epg-e/cep-mac', mac='00:11', bdDn='bd')
            row['fvCEp']['children'] = [obj('fvIp', addr='10.0.0.1')]*2
            rows.append(row)
        with patch.object(reports, 'apic_get', return_value=rows):
            data = self.client.get('/api/ip_endpoints').json
        self.assertEqual(len(data), 2)
        self.assertEqual({r['tenant'] for r in data}, {'A', 'B'})

    def test_bundle_and_access_deployment(self):
        for kind, prefix in (('infraAccPortGrp', 'accportgrp'), ('infraAccBndlGrp', 'accbundle')):
            group = f'uni/infra/funcprof/{prefix}-PG'
            deployment = [{kind: {'attributes': {'dn':group}, 'children': [
                {'pconsNodeDeployCtx': {'children':[obj('pconsResourceCtx', ctxDn=DN),obj('pconsResourceCtx', ctxDn=DN)]}}
            ]}}]
            with patch.object(reports, 'apic_get', return_value=deployment) as get:
                ports = []
                reports._collect_acc_ports(group, ports)
            self.assertIn(group, get.call_args.args[0])
            self.assertEqual(len(ports), 1)
            self.assertEqual(ports[0]['dn'], DN)

    def test_aep_preserves_group_type_and_oper_state(self):
        groups = ['uni/infra/funcprof/accportgrp-PG', 'uni/infra/funcprof/accbundle-PG']
        def get(path, params=None):
            if 'infraAttEntityP' in path: return [obj('infraAttEntityP', name='AEP')]
            if 'infraRsAttEntP' in path:
                return [obj('infraRsAttEntP', tDn='uni/infra/attentp-AEP', dn=g+'/rsattEntP') for g in groups]
            if 'l1PhysIf' in path: return [obj('l1PhysIf', dn=DN)]
            if 'ethpmPhysIf' in path: return [obj('ethpmPhysIf', dn=DN+'/phys', operSt='up', operSpeed='10G')]
            self.fail(path)
        def collect(group, ports): ports.append(dict(dn=DN, pod='1', node='101', iface='eth1/1'))
        with patch.object(reports, 'apic_get', side_effect=get), patch.object(reports, '_collect_acc_ports', side_effect=collect) as collector:
            response = self.client.get('/api/aep_interfaces')
        self.assertEqual(response.status_code, 200)
        self.assertEqual({c.args[0] for c in collector.call_args_list}, set(groups))
        self.assertEqual(len(response.json), 2)
        self.assertEqual({r['policy_group_dn'] for r in response.json}, set(groups))
        self.assertTrue(all(r['status']=='up' and r['speed']=='10G' for r in response.json))

    def test_partial_warning_survives_cache_and_refresh(self):
        def get(path, params=None):
            if 'infraAccPortGrp' in path: return [obj('infraAccPortGrp', name='PG')]
            return []
        with patch.object(reports, 'apic_get', side_effect=get), patch.object(reports, '_collect_acc_ports', side_effect=RuntimeError('simulated')) as collect:
            first = self.client.get('/api/acc_ports')
            cached = self.client.get('/api/acc_ports')
            refreshed = self.client.get('/api/acc_ports?refresh=1')
        self.assertEqual(collect.call_count, 2)
        self.assertEqual(first.headers['X-Data-Cache'], 'miss')
        self.assertEqual(cached.headers['X-Data-Cache'], 'hit')
        self.assertEqual(refreshed.headers['X-Data-Cache'], 'miss')
        self.assertIn('Coleta incompleta', first.headers['X-Collection-Warnings'])
        self.assertEqual(first.headers['X-Collection-Warnings'], cached.headers['X-Collection-Warnings'])

    def test_l3out_shared_snapshot(self):
        with patch.object(reports, 'apic_get', return_value=[]) as get:
            self.client.get('/api/l3out_subnets')
            self.client.get('/api/l3out_subnets')
            self.assertEqual(get.call_count, 1)
            self.client.get('/api/l3out_subnets?refresh=1')
            self.assertEqual(get.call_count, 2)

    def test_all_html_routes_render_and_assets_exist(self):
        for rule in reports.app.url_map.iter_rules():
            if rule.arguments or rule.rule.startswith(('/api/', '/export_csv/')):
                continue
            with self.subTest(route=rule.rule):
                self.assertEqual(self.client.get(rule.rule, follow_redirects=True).status_code, 200)
        with self.client.get('/static/report-tools.js') as response:
            self.assertEqual(response.status_code, 200)

    def test_csv_preserves_switch_and_endpoint_context(self):
        with patch.object(reports, 'apic_get', return_value=[]):
            pc = self.client.get('/export_csv/portchannels')
            ip = self.client.get('/export_csv/ip_endpoints')
            aep = self.client.get('/export_csv/aep_interfaces')
        self.assertEqual(pc.status_code, 200)
        self.assertIn('Pod,Node,DN', pc.text)
        self.assertIn('Tenant,Endpoint DN', ip.text)
        self.assertEqual(aep.status_code, 200)

    def test_apic_error_object_is_not_a_successful_empty_report(self):
        from unittest.mock import Mock
        response = Mock(status_code=200)
        response.json.return_value = {'imdata':[obj('error', code='400', text='Invalid query')]}
        with patch.object(reports, 'apic_login', return_value='mock'), patch.object(reports.session, 'get', return_value=response):
            with self.assertRaisesRegex(RuntimeError, 'Invalid query'):
                reports._apic_get_page('/api/class/test.json', {})

    def test_api_failure_is_not_empty_success(self):
        with patch.object(reports, 'apic_get', side_effect=RuntimeError('simulated')):
            self.assertEqual(self.client.get('/api/vrfs').status_code, 500)


if __name__ == '__main__':
    unittest.main()
