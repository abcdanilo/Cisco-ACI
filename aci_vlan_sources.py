"""Read-only VLAN associations, keeping configuration and deployment distinct."""
import re
from aci_access import configured_access_ports

EPG = r'uni/tn-([^/]+)/ap-([^/]+)/epg-([^/]+)'
PATH = re.compile(r'topology/pod-(\d+)/(?:protpaths-(\d+)-(\d+)|paths-(\d+))/(?:extpaths-(\d+)/)?pathep-\[(.+)\]')


def path_fields(path):
    match = PATH.fullmatch(path)
    if not match:
        return dict(path=path, pod='', nodes=[], port='', kind='Caminho não resolvido')
    pod, first, second, single, fex, port = match.groups()
    return dict(path=path, pod=pod, nodes=[first, second] if first else [single],
                port=port, kind='vPC' if first else 'FEX' if fex else 'Porta / PC')


def record(a, tenant, application='', epg='', source='', path='', **extra):
    return dict(dn=a.get('dn', ''), tenant=tenant, application=application, epg=epg,
                vlan=a.get('encap', ''), mode=a.get('mode', ''), deployment=a.get('instrImedcy', ''),
                state=a.get('state', ''), source=source, evidence='Configuração',
                aep='', domain='', l3out='', address='', interface_type='', note='',
                **path_fields(path), **extra)


def collect_vlan_sources(get, static_rows, warning):
    rows = [dict(r, source='Estático', evidence='Configuração', aep='', domain='',
                 l3out='', address='', interface_type='', note='') for r in static_rows]
    cache = {}

    def query(cls, params=None):
        if cls not in cache:
            try:
                cache[cls] = [item[cls] for item in get('/api/class/'+cls+'.json', params=params) if cls in item]
            except Exception:
                warning(f'Cobertura parcial de VLANs: consulta {cls} indisponível.')
                cache[cls] = []
        return cache[cls]

    def attrs(cls, params=None):
        return [obj.get('attributes', {}) for obj in query(cls, params)]

    # Routed interfaces are distinct from External EPG subnets.
    for a in attrs('l3extRsPathL3OutAtt'):
        match = re.fullmatch(r'uni/tn-([^/]+)/out-([^/]+)/lnodep-([^/]+)/lifp-([^/]+)/rspathL3OutAtt-\[(.+)\]', a.get('dn', ''))
        if not match:
            continue
        tenant, out, node_profile, interface_profile, target = match.groups()
        row = record(a, tenant, source='L3Out', path=a.get('tDn') or target)
        row.update(l3out=out, address=a.get('addr', ''), interface_type=a.get('ifInstT', ''),
                   note=f'Node Profile: {node_profile}; Interface Profile: {interface_profile}. Não identifica um External EPG específico.')
        if a.get('ifInstT') == 'l3-port' and a.get('encap') in ('', 'unknown', None):
            row['note'] += ' Porta roteada sem encapsulamento VLAN informado.'
        rows.append(row)

    # An EPG-domain relation does not identify a physical port or an allocated VLAN.
    for a in attrs('fvRsDomAtt'):
        domain = a.get('tDn', '')
        match = re.fullmatch(EPG+r'/rsdomAtt-\[(.+)\]', a.get('dn', ''))
        if not match or not domain.startswith('uni/vmmp-'):
            continue
        row = record(a, *match.groups()[:3], source='VMM')
        row.update(domain=domain, note='Associação ao domínio VMM; porta não identificada por esta relação. Consulte também Deployment dinâmico.')
        rows.append(row)

    # AEP -> EPG -> policy group -> explicit selectors -> existing physical ports.
    aep_bindings = attrs('infraRsFuncToEpg')
    if aep_bindings:
        links = attrs('infraRsAttEntP')
        profiles = [{'infraAccPortP': x} for x in query('infraAccPortP', {'rsp-subtree': 'full'})]
        switches = [{'infraNodeP': x} for x in query('infraNodeP', {'rsp-subtree': 'full'})]
        physical = [a.get('dn', '') for a in attrs('l1PhysIf')]
        resolved = {}
        for a in aep_bindings:
            match = re.fullmatch(EPG, a.get('tDn', ''))
            parent = re.fullmatch(r'(uni/infra/attentp-[^/]+)/(?:gen-[^/]+|provacc)/rsfuncToEpg-\[.+\]', a.get('dn', ''))
            if not match or not parent:
                continue
            aep = parent[1]
            ports = {}
            if a.get('state') == 'formed':
                for link in links:
                    group = re.fullmatch(r'(uni/infra/funcprof/(?:accportgrp|accbundle)-[^/]+)/rsattEntP', link.get('dn', ''))
                    if not group or link.get('tDn') != aep or link.get('state') != 'formed':
                        continue
                    if group[1] not in resolved:
                        resolved[group[1]] = configured_access_ports(group[1], profiles, switches, physical)
                    for port in resolved[group[1]]:
                        ports[port['dn']] = port
            for port in list(ports.values()) or [None]:
                path = f"topology/pod-{port['pod']}/paths-{port['node']}/pathep-[{port['iface']}]" if port else ''
                row = record(a, *match.groups(), source='AEP', path=path)
                row.update(aep=aep, note='Porta associada por seletores e inventário físico; não comprova deployment da VLAN.' if port else
                           'Portas não resolvidas pelos seletores e inventário disponíveis; vínculo AEP preservado.')
                rows.append(row)

    # fvDyPathAtt's DN includes the full path (dyatt-[topology/...]). Only
    # fvIfConn children of that exact DN can provide its dynamic encapsulation.
    dynamic = {a.get('dn', ''): a for a in attrs('fvDyPathAtt')}
    connections = {}
    for a in attrs('fvIfConn'):
        parent, sep, _ = a.get('dn', '').partition('/conndef/conn-[')
        if sep and '/dyatt-[' in parent:
            connections.setdefault(parent, []).append(a)
            dynamic.setdefault(parent, {'dn': parent})
    pattern = re.compile(r'uni/epp/fv-\[('+EPG+r')\]/node-(\d+)/dyatt-\[(topology/.+)\]')
    for dn, attachment in dynamic.items():
        match = pattern.fullmatch(dn)
        if not match:
            continue
        epg_dn, tenant, application, epg, node, path = match.groups()
        topology = path_fields(path)
        if node not in topology['nodes']:
            warning('Cobertura parcial de VLANs: caminho dinâmico incompatível com o node; associação ignorada.')
            continue
        for a in connections.get(dn) or [attachment]:
            row = record(a, tenant, application, epg, source='Deployment dinâmico', path=path)
            row.update(evidence='Deployment informado pela APIC', state=a.get('validState', ''),
                       note='Conexão dinâmica do EPG; não comprova tráfego nem identifica sozinha o domínio VMM.')
            if not connections.get(dn):
                row['note'] += ' Conexão de encapsulamento não retornada.'
            rows.append(row)
    unique = {(r['source'], r['dn'], r['path']): r for r in rows}
    return sorted(unique.values(), key=lambda r: (r['tenant'], r['epg'], r['l3out'], r['source'], r['path']))
