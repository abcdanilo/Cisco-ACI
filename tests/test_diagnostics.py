import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.update(APIC_USER='test', APIC_PASS='test', PYTHON_DOTENV_DISABLED='1')
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import app as reports
from aci_diagnostics import normalize_lookup, normalize_sample, path_information


DN = 'topology/pod-1/node-101/sys/phys-[eth1/1]'
PATH = 'topology/pod-1/paths-101/pathep-[eth1/1]'


def obj(kind, **attr):
    return {kind: {'attributes': attr}}


def endpoints():
    rows = []
    for tenant in ('A','B'):
        item = obj('fvCEp', dn=f'uni/tn-{tenant}/ap-ERP/epg-WEB/cep-AA:BB:CC:DD:EE:FF',
                   mac='AA:BB:CC:DD:EE:FF', ip='0.0.0.0', encap='vlan-200', bdDn=f'uni/tn-{tenant}/BD-WEB')
        item['fvCEp']['children'] = [obj('fvIp',addr='10.0.0.10'),obj('fvIp',addr='2001:db8::1'),
            obj('fvIp',addr='0.0.0.0'), obj('fvRsCEpToPathEp',tDn=PATH), obj('fvRsCEpToPathEp',tDn=PATH)]
        rows.append(item)
    return rows


def physical():
    item = obj('l1PhysIf',dn=DN,adminSt='up',descr='Servidor ERP',speed='inherit',mtu='9000')
    item['l1PhysIf']['children'] = [obj('ethpmPhysIf',operSt='up',operSpeed='10G',operDuplex='full')]
    return [item]


class DiagnosticsTests(unittest.TestCase):
    def setUp(self):
        reports._data_cache.clear()
        self.client = reports.app.test_client()
        mock = patch.object(reports.session, 'request', side_effect=AssertionError('Network forbidden'))
        mock.start(); self.addCleanup(mock.stop)

    def test_mac_and_ipv6_normalization(self):
        for value in ('aabbccddeeff','aa:bb:cc:dd:ee:ff','AA-BB-CC-DD-EE-FF','aabb.ccdd.eeff'):
            self.assertEqual(normalize_lookup(value),('mac','AABBCCDDEEFF'))
        self.assertEqual(normalize_lookup('2001:0db8:0:0:0:0:0:1'),('ip','2001:db8::1'))

    def test_invalid_queries_do_not_contact_apic(self):
        with patch.object(reports,'apic_get') as get:
            for query in ('', '10.0.0', '10.0.0.999','<script>', 'AA-BB:CCDD.EEFF'):
                self.assertEqual(self.client.get('/api/endpoint_lookup',query_string={'q':query}).status_code,400)
            for dn in ('', 'http://example.com', DN+'/../', 'topology/pod-1/node-101/sys/aggr-[po1]'):
                self.assertEqual(self.client.get('/api/interface_details',query_string={'dn':dn}).status_code,400)
            get.assert_not_called()

    def test_ip_lookup_keeps_tenants_and_child_paths(self):
        with patch.object(reports,'apic_get',return_value=endpoints()) as get:
            response = self.client.get('/api/endpoint_lookup?q=10.0.0.10')
        self.assertEqual(response.status_code,200)
        self.assertEqual(len(response.json),2)
        self.assertEqual({row['tenant'] for row in response.json},{'A','B'})
        row=response.json[0]
        self.assertEqual((row['application'],row['epg'],row['encap']),('ERP','WEB','vlan-200'))
        self.assertEqual(row['ips'],['10.0.0.10','2001:db8::1'])
        self.assertEqual(len(row['paths']),1)
        self.assertEqual(row['paths'][0]['interface_dn'],DN)
        self.assertIn('fvRsCEpToPathEp',get.call_args_list[0].kwargs['params']['rsp-subtree-class'])

    def test_lookup_cache_shared_between_searches_and_refresh(self):
        with patch.object(reports,'apic_get',return_value=endpoints()) as get:
            a=self.client.get('/api/endpoint_lookup?q=10.0.0.10')
            b=self.client.get('/api/endpoint_lookup?q=aabb.ccdd.eeff')
            c=self.client.get('/api/endpoint_lookup?q=2001:0db8:0:0:0:0:0:1')
            self.assertEqual(sum('fvCEp' in c.args[0] for c in get.call_args_list),1)
            self.assertEqual(b.headers['X-Data-Cache'],'hit')
            self.assertEqual(c.json,a.json)
            self.client.get('/api/endpoint_lookup?q=10.0.0.10&refresh=1')
            self.assertEqual(sum('fvCEp' in c.args[0] for c in get.call_args_list),2)

    def test_server_name_and_physical_speeds(self):
        def get(path,params=None):
            if 'fvCEp' in path:
                data=endpoints()
                data[0]['fvCEp']['attributes']['nameAlias']='SRV-Financeiro'
                return data
            if 'l1PhysIf' in path:return [obj('l1PhysIf',dn=DN,speed='inherit',descr='Server port',adminSt='up')]
            if 'ethpmPhysIf' in path:return [obj('ethpmPhysIf',dn=DN+'/phys',operSpeed='10G',operSt='up')]
            return []
        with patch.object(reports,'apic_get',side_effect=get):
            response=self.client.get('/api/endpoint_lookup?mode=name&q=financeiro')
            self.assertEqual(response.status_code,200)
            self.assertEqual(len(response.json),1)
            port=response.json[0]['paths'][0]['ports'][0]
            self.assertEqual((port['configured_speed'],port['oper_speed']),('inherit','10G'))
            self.assertEqual(self.client.get('/api/endpoint_lookup?mode=name&q=missing').json,[])
            self.assertIn('AA',self.client.get('/export_csv/endpoint_lookup?mode=name&q=financeiro').text)

    def test_endpoint_without_ip_can_be_found_by_mac(self):
        row=obj('fvCEp',dn='uni/tn-A/ap-X/epg-Y/cep-AA:BB:CC:DD:EE:FF',mac='AA:BB:CC:DD:EE:FF')
        with patch.object(reports,'apic_get',return_value=[row]):
            result=self.client.get('/api/endpoint_lookup?q=aabbccddeeff').json
            empty=self.client.get('/api/endpoint_lookup?q=10.0.0.10').json
        self.assertEqual(result[0]['ips'],[])
        self.assertEqual(result[0]['paths'],[])
        self.assertEqual(empty,[])

    def test_vpc_and_fex_paths_are_not_mislabeled_as_physical_ports(self):
        vpc=path_information('topology/pod-1/protpaths-101-102/pathep-[PG-vPC]')
        fex=path_information('topology/pod-1/paths-101/extpaths-112/pathep-[eth1/1]')
        self.assertEqual(vpc['kind'],'vpc')
        self.assertEqual(fex['kind'],'fex')
        self.assertEqual(vpc['interface_dn'],'')
        self.assertEqual(fex['interface_dn'],'')

    def test_stats_window_units_zero_and_exact_counters(self):
        def get(path,params=None):
            if path.endswith('/HDeqptIngrTotal5min-0.json'):
                return [obj('eqptIngrTotal5min',bytesRateAvg='1250000',pktsRateAvg='0',bytesPer='375000000',
                    bytesCum='9007199254740993',repIntvStart='2026-09-21T10:00:00+00:00',repIntvEnd='2026-09-21T10:05:00+00:00')]
            if path.endswith('/HDeqptEgrTotal5min-0.json'):
                return [obj('eqptEgrTotal5min',bytesRateAvg='0',pktsRateAvg='0')]
            return physical()
        with patch.object(reports,'apic_get',side_effect=get) as mock:
            response=self.client.get('/api/interface_details',query_string={'dn':DN})
            self.client.get('/api/interface_details',query_string={'dn':DN})
            self.assertEqual(mock.call_count,3)
            self.client.get('/api/interface_details',query_string={'dn':DN,'refresh':'1'})
            self.assertEqual(mock.call_count,6)
        row=response.json
        self.assertEqual(row['oper_speed'],'10G')
        self.assertEqual(row['admin_state'],'up')
        sample=row['statistics']['ingress']
        self.assertEqual(sample['interval_seconds'],300)
        self.assertEqual(sample['bytes_per_second'],1250000)
        self.assertEqual(sample['packets_per_second'],0)
        self.assertEqual(sample['bytes_cumulative'],'9007199254740993')
        self.assertIsNone(sample['packets_in_interval'])
        self.assertEqual(row['statistics']['egress']['bytes_per_second'],0)

    def test_partial_stats_failure_retains_interface_and_warning_in_cache(self):
        def get(path,params=None):
            if 'HDeqptIngr' in path: raise RuntimeError('simulated')
            if 'HDeqptEgr' in path: return []
            return physical()
        with patch.object(reports,'apic_get',side_effect=get):
            response=self.client.get('/api/interface_details',query_string={'dn':DN})
            cached=self.client.get('/api/interface_details',query_string={'dn':DN})
        self.assertEqual(response.status_code,200)
        self.assertEqual(response.json['oper_state'],'up')
        self.assertFalse(response.json['statistics']['ingress']['available'])
        self.assertIsNone(response.json['statistics']['ingress']['bytes_per_second'])
        self.assertEqual(response.headers['X-Collection-Warnings'],cached.headers['X-Collection-Warnings'])

    def test_not_found_and_query_failure_are_distinct(self):
        with patch.object(reports,'apic_get',return_value=[]):
            self.assertEqual(self.client.get('/api/interface_details',query_string={'dn':DN}).status_code,404)
        with patch.object(reports,'apic_get',side_effect=RuntimeError('simulated')):
            self.assertEqual(self.client.get('/api/interface_details',query_string={'dn':DN}).status_code,500)
            self.assertEqual(self.client.get('/api/endpoint_lookup?q=10.0.0.10').status_code,500)

    def test_invalid_stats_values_are_not_zero(self):
        for value in ('NaN','Infinity','-1','unspecified',''):
            sample=normalize_sample({'bytesRateAvg':value})
            self.assertIsNone(sample['bytes_per_second'])

    def test_csv_exports_only_query_results(self):
        rows=endpoints()+[obj('fvCEp',dn='uni/tn-C/ap-X/epg-Y/cep-other',mac='00:11:22:33:44:55',ip='10.0.0.20')]
        rows[0]['fvCEp']['attributes']['encap']='=formula'
        with patch.object(reports,'apic_get',return_value=rows):
            response=self.client.get('/export_csv/endpoint_lookup?q=10.0.0.10')
        self.assertEqual(response.status_code,200)
        self.assertIn('Application Profile',response.text)
        self.assertIn("'=formula",response.text)
        self.assertNotIn('10.0.0.20',response.text)


if __name__=='__main__':
    unittest.main()
