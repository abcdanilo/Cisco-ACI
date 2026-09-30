"""Read-only PC/vPC overview with explicit evidence for each association."""
import csv
import io
import re
from collections import defaultdict
from flask import Response, jsonify, render_template, request
from aci_diagnostics import csv_cell

PHYS = re.compile(r'topology/pod-(\d+)/node-(\d+)/sys/phys-\[(eth\d+/\d+(?:/\d+)?)\]')
AGGR = re.compile(r'topology/pod-(\d+)/node-(\d+)/sys/aggr-\[(.+)\]')
PATH = re.compile(r'topology/pod-(\d+)/(?:protpaths-(\d+)-(\d+)|paths-(\d+))/pathep-\[(.+)\]')


def collect_overview(apic_get, collect_ports, warning):
    # Aggregate inventory is mandatory; optional enrichment failures remain visible.
    raw = apic_get('/api/class/pcAggrIf.json', params={
        'rsp-subtree':'children', 'rsp-subtree-class':'pcRsMbrIfs,ethpmAggrIf'})
    def optional(path, params=None):
        try:
            return apic_get(path, params=params)
        except Exception:
            warning(f'Coleta parcial: consulta indisponível em {path}.')
            return []
    paths = optional('/api/class/fabricPathEp.json', {'query-target-filter':'or(eq(fabricPathEp.lagT,"node"),eq(fabricPathEp.lagT,"link"))'})
    physical = {item['l1PhysIf']['attributes']['dn']:item['l1PhysIf']['attributes']
                for item in optional('/api/class/l1PhysIf.json') if 'l1PhysIf' in item and item['l1PhysIf'].get('attributes',{}).get('dn')}
    operations = {}
    for item in optional('/api/class/ethpmPhysIf.json'):
        attr = item.get('ethpmPhysIf',{}).get('attributes',{})
        dn = attr.get('dn','')
        if dn.endswith('/phys'):
            operations[dn[:-5]] = attr

    def member(dn):
        match = PHYS.fullmatch(dn)
        info, state = physical.get(dn,{}), operations.get(dn,{})
        return {'dn':dn, 'interface':match[3], 'admin_state':info.get('adminSt',''),
                'oper_state':state.get('operSt',''), 'speed':state.get('operSpeed') or info.get('speed',''),
                'description':info.get('descr','')}

    aggregates, indexed = {}, defaultdict(list)
    for item in raw:
        obj = item.get('pcAggrIf',{})
        a = obj.get('attributes',{})
        dn = a.get('dn','')
        match = AGGR.fullmatch(dn)
        if not match or dn in aggregates:
            continue
        pod,node,number = match.groups()
        members,oper = set(),{}
        for child in obj.get('children',[]):
            if 'ethpmAggrIf' in child:
                oper = child['ethpmAggrIf'].get('attributes',{})
            rel = child.get('pcRsMbrIfs',{}).get('attributes',{})
            target = rel.get('tDn','')
            if not target and re.fullmatch(r'eth\d+/\d+(?:/\d+)?',rel.get('tSKey','')):
                target = f'topology/pod-{pod}/node-{node}/sys/phys-[{rel["tSKey"]}]'
            physical_match = PHYS.fullmatch(target)
            if physical_match and physical_match.group(1,2) == (pod,node):
                members.add(target)
        record = {'dn':dn,'pod':pod,'node':node,'id':a.get('id') or number,'name':a.get('name',''),
                  'mode':a.get('pcMode',''),'admin_state':a.get('adminSt',''),
                  'oper_state':oper.get('operSt',''),'members':[member(x) for x in sorted(members)]}
        aggregates[dn] = record
        indexed[(pod,node)].append(record)

    # Each logical path defines pod, exact peer set and bundle policy group.
    logical, deploy = {}, {}
    for item in paths:
        a = item.get('fabricPathEp',{}).get('attributes',{})
        match = PATH.fullmatch(a.get('dn',''))
        if not match or a.get('lagT') not in ('node','link'):
            continue
        pod,first,second,single,name = match.groups()
        if (first and a['lagT'] != 'node') or (single and a['lagT'] != 'link'):
            continue
        nodes = sorted([first,second] if first else [single],key=int)
        pg = 'uni/infra/funcprof/accbundle-' + name
        logical[a['dn']] = {'id':a['dn'],'name':a.get('name') or name,'kind':'vpc' if first else 'pc',
                            'pod':pod,'policy_group_dn':pg,'expected_nodes':nodes,'nodes':[]}
        if pg not in deploy:
            ports = []
            try:
                collect_ports(pg,ports)
                deploy[pg] = {p['dn'] for p in ports if PHYS.fullmatch(p.get('dn',''))}
            except Exception:
                deploy[pg] = set()
                warning(f'Não foi possível resolver os membros do grupo {name}.')

    # Build proposals first: a physical aggregate can belong to at most one path.
    claims = defaultdict(set)
    proposals = {}
    for group in logical.values():
        for node in group['expected_nodes']:
            ports = {dn for dn in deploy[group['policy_group_dn']] if PHYS.fullmatch(dn).group(1,2) == (group['pod'],node)}
            candidates = [pc for pc in indexed[(group['pod'],node)]
                          if pc['members'] and {m['dn'] for m in pc['members']} <= ports]
            evidence = 'confirmed'
            # Some APIC versions return no deployment contexts. A unique exact
            # name within the logical path's pod/peer is useful correlation,
            # but must never be presented as physically confirmed deployment.
            if not ports:
                evidence = 'inferred'
                path_name = PATH.fullmatch(group['id'])[5]
                candidates = [pc for pc in indexed[(group['pod'],node)]
                              if pc['name']==path_name and pc['members']]
            proposals[(group['id'],node)] = (ports,candidates,evidence)
            for pc in candidates:
                claims[pc['dn']].add(group['id'])
    used = set()
    for group in logical.values():
        for node in group['expected_nodes']:
            ports,candidates,evidence = proposals[(group['id'],node)]
            verified = len(candidates)==1 and len(claims[candidates[0]['dn']])==1
            pc = candidates[0] if verified else None
            if pc:
                used.add(pc['dn'])
            group['nodes'].append({'node':node,'mapping':evidence if verified else 'ambiguous' if candidates else 'unresolved',
                'aggregate':pc,'members':pc['members'] if pc else [member(x) for x in sorted(ports)]})
        group['coverage'] = ('complete' if all(n['mapping']=='confirmed' for n in group['nodes'])
                             else 'correlated' if all(n['aggregate'] for n in group['nodes']) else 'partial')

    inferred = sum(any(n['mapping']=='inferred' for n in g['nodes']) for g in logical.values())
    partial = sum(g['coverage']=='partial' for g in logical.values())
    if inferred:
        warning(f'{inferred} grupo(s) correlacionado(s) por nome exato, pod e nodes do caminho lógico; deployment físico não confirmado. Consulte os detalhes por node.')
    if partial:
        warning(f'{partial} grupo(s) com associação incompleta ou ambígua; consulte os detalhes por node.')

    groups = list(logical.values())
    for dn,pc in aggregates.items():
        if dn in used:
            continue
        groups.append({'id':dn,'name':pc['name'] or pc['id'],'kind':'unassociated','pod':pc['pod'],
            'policy_group_dn':'','expected_nodes':[pc['node']],'coverage':'unassociated',
            'nodes':[{'node':pc['node'],'mapping':'standalone','aggregate':pc,'members':pc['members']}]})
    for group in groups:
        members = [m for node in group['nodes'] for m in node['members']]
        group['member_counts'] = {'total':len(members),'up':sum(m['oper_state']=='up' for m in members),
                                  'down':sum(m['oper_state']=='down' for m in members),
                                  'other':sum(m['oper_state'] not in ('up','down') for m in members)}
        search = [group['id'],group['name'],group['pod'],group['policy_group_dn']]
        for node in group['nodes']:
            pc = node['aggregate'] or {}
            search.extend([node['node'],pc.get('id',''),pc.get('name','')])
            for m in node['members']:search.extend([m['interface'],m['dn'],m['description']])
        group['search_text'] = ' '.join(search).lower()
    return sorted(groups,key=lambda g:(int(g['pod']),g['name'],g['id']))


def filter_overview(rows, args):
    q = args.get('q','').strip().lower()
    return [row for row in rows if (not q or q in row['search_text'])
        and (not args.get('kind') or row['kind']==args['kind'])
        and (not args.get('pod') or row['pod']==args['pod'])
        and (not args.get('path') or row['id']==args['path'])
        and any((not args.get('node') or node['node']==args['node'])
                and (not args.get('state') or (node['aggregate'] or {}).get('oper_state')==args['state'])
                for node in row['nodes'])]


def register_portchannels(app, apic_get, collect_ports, cached, json_route, warning):
    @cached()
    def portchannel_overview():
        return collect_overview(apic_get,collect_ports,warning)

    @app.get('/portchannel_overview')
    def portchannel_overview_page():
        return render_template('portchannel_overview.html')

    @app.get('/api/portchannel_overview')
    def portchannel_overview_api():
        return json_route(lambda:filter_overview(portchannel_overview(),request.args))

    @app.get('/export_csv/portchannel_overview')
    def portchannel_overview_csv():
        try:
            rows = filter_overview(portchannel_overview(),request.args)
        except Exception:
            app.logger.exception('Falha ao exportar consolidação PC/vPC')
            return jsonify(error='Falha ao consultar port-channels.'),500
        output=io.StringIO();writer=csv.writer(output)
        writer.writerow(['Grupo','Tipo','Pod','Caminho/DN','Cobertura','Node','Associacao','Port-channel','Estado PC','Interface','Admin','Operacional','Velocidade','Descricao'])
        for group in rows:
            for node in group['nodes']:
                pc=node['aggregate'] or {}
                for m in node['members'] or [{}]:
                    writer.writerow([csv_cell(value) for value in [group['name'],group['kind'],group['pod'],group['id'],group['coverage'],node['node'],node['mapping'],pc.get('id'),pc.get('oper_state'),m.get('interface'),m.get('admin_state'),m.get('oper_state'),m.get('speed'),m.get('description')]])
        return Response('\ufeff'+output.getvalue(),mimetype='text/csv; charset=utf-8',headers={
            'Content-Disposition':'attachment; filename=portchannel_overview.csv','Cache-Control':'no-store'})
