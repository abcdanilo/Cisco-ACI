"""Configured EPG static bindings; no claim of forwarding or live traffic."""
import csv
import io
import re
from flask import Response, render_template, request
from aci_diagnostics import csv_cell
from aci_vlan_sources import collect_vlan_sources


def collect_bindings(get):
    rows = {}
    for item in get('/api/class/fvRsPathAtt.json'):
        a = item.get('fvRsPathAtt', {}).get('attributes', {})
        dn = a.get('dn', '')
        match = re.fullmatch(r'uni/tn-([^/]+)/ap-([^/]+)/epg-([^/]+)/rspathAtt-\[(.+)\]', dn)
        if not match:
            continue
        tenant, application, epg, target = match.groups()
        path = a.get('tDn') or target
        topology = re.fullmatch(r'topology/pod-(\d+)/(?:protpaths-(\d+)-(\d+)|paths-(\d+))/(?:extpaths-(\d+)/)?pathep-\[(.+)\]', path)
        pod, nodes, port, kind = '', [], '', 'Outro caminho'
        if topology:
            pod, first, second, single, fex, port = topology.groups()
            nodes = [first, second] if first else [single]
            kind = 'vPC' if first else 'FEX' if fex else 'Porta / PC'
        rows[dn] = dict(dn=dn,tenant=tenant,application=application,epg=epg,
            vlan=a.get('encap',''),mode=a.get('mode',''),deployment=a.get('instrImedcy',''),
            state=a.get('state',''),path=path,pod=pod,nodes=nodes,port=port,kind=kind)
    return sorted(rows.values(),key=lambda r:(r['tenant'],r['application'],r['epg'],r['path']))


def select_bindings(rows,args):
    q=args.get('q','').strip().casefold()
    return [r for r in rows if (not args.get('tenant') or r['tenant']==args['tenant'])
        and (not args.get('node') or args['node'] in r['nodes'])
        and (not args.get('path') or r['path']==args['path'])
        and (not args.get('source') or r.get('source')==args['source'])
        and (not q or q in ' '.join(str(v) for v in r.values()).casefold())]


def register_bindings(app,get,cached,json_route,warning=lambda message: None):
    @cached()
    def binding_tenants():
        return sorted({a['name'] for item in get('/api/class/fvTenant.json')
                       if (a := item.get('fvTenant', {}).get('attributes', {})).get('name')})

    @cached()
    def bindings():
        return collect_bindings(get)

    @cached()
    def port_vlans():
        try:
            static_rows = collect_bindings(get)
        except Exception:
            warning('Cobertura parcial de VLANs: consulta fvRsPathAtt indisponível.')
            static_rows = []
        return collect_vlan_sources(get, static_rows, warning)

    @app.get('/api/port_vlans')
    def port_vlans_api():
        return json_route(lambda: select_bindings(port_vlans(), request.args))

    @app.get('/export_csv/port_vlans')
    def port_vlans_csv():
        output=io.StringIO();writer=csv.writer(output)
        fields=['tenant','source','evidence','application','epg','l3out','vlan','mode','deployment',
                'state','pod','nodes','port','path','aep','domain','address','interface_type','note','dn']
        writer.writerow(['Tenant','Origem','Evidência','Application Profile','EPG','L3Out','Encap','Modo',
                         'Deployment','Estado da relação','Pod','Nodes','Porta / Grupo','Caminho',
                         'AEP','Domínio','Endereço','Tipo de interface','Observação','DN'])
        for row in select_bindings(port_vlans(), request.args):
            writer.writerow([csv_cell('; '.join(row[k]) if isinstance(row[k],list) else row[k]) for k in fields])
        return Response('\ufeff'+output.getvalue(),mimetype='text/csv',headers={
            'Content-Disposition':'attachment; filename=port_vlans.csv','Cache-Control':'no-store'})

    @app.get('/epg_bindings')
    def epg_bindings_page():
        return render_template('epg_bindings.html')

    @app.get('/api/epg_bindings')
    def epg_bindings_api():
        return json_route(lambda:select_bindings(bindings(),request.args))

    @app.get('/api/epg_binding_tenants')
    def epg_binding_tenants_api():
        return json_route(binding_tenants)

    @app.get('/export_csv/epg_bindings')
    def epg_bindings_csv():
        output=io.StringIO();writer=csv.writer(output)
        fields=['tenant','application','epg','vlan','mode','deployment','state','pod','nodes','port','path']
        writer.writerow(['Tenant','Application Profile','EPG','VLAN','Modo','Deployment','Estado da relação','Pod','Nodes','Porta / Grupo','Caminho'])
        for row in select_bindings(bindings(),request.args):
            writer.writerow([csv_cell('; '.join(row[k]) if isinstance(row[k],list) else row[k]) for k in fields])
        return Response('\ufeff'+output.getvalue(),mimetype='text/csv',headers={
            'Content-Disposition':'attachment; filename=epg_bindings.csv','Cache-Control':'no-store'})
