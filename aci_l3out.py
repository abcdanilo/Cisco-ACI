"""Dynamic L3Out inventory and External EPG prefix selection."""
import csv
import io
import re
from flask import request, render_template, Response
from aci_diagnostics import csv_cell


def inventory(get, subnets):
    tenants = sorted({x['fvTenant']['attributes']['name'] for x in get('/api/class/fvTenant.json') if 'fvTenant' in x})
    outs = {}
    for item in get('/api/class/l3extOut.json'):
        a = item.get('l3extOut',{}).get('attributes',{})
        match = re.fullmatch(r'uni/tn-([^/]+)/out-([^/]+)',a.get('dn',''))
        if match:
            tenant,name=match.groups()
            outs[(tenant,name)]={'tenant':tenant,'name':name,'dn':a['dn']}
    rows=subnets()
    # Keep collected prefixes selectable even if inventory visibility differs.
    for row in rows:
        key=(row['tenant'],row['l3out'])
        outs.setdefault(key,{'tenant':key[0],'name':key[1],'dn':''})
    tenants=sorted(set(tenants)|{t for t,_ in outs})
    return {'tenants':tenants,'l3outs':[outs[k] for k in sorted(outs)],'rows':rows}


def select(rows,args):
    tenant=args.get('tenant','');out=args.get('l3out','');q=args.get('q','').strip().casefold()
    return [r for r in rows if (not tenant or r['tenant']==tenant)
            and (not out or r['l3out']==out)
            and (not q or q in ' '.join(str(v) for v in r.values()).casefold())]


def collect_static_routes(get):
    rows={}
    for item in get('/api/class/ipRouteP.json',params={'rsp-subtree':'children','rsp-subtree-class':'ipNexthopP'}):
        obj=item.get('ipRouteP',{});a=obj.get('attributes',{});dn=a.get('dn','')
        match=re.fullmatch(r'uni/tn-([^/]+)/out-([^/]+)/lnodep-([^/]+)/rsnodeL3OutAtt-\[topology/pod-(\d+)/node-(\d+)\]/rt-\[(.+)\]',dn)
        if not match:continue
        tenant,out,profile,pod,node,prefix=match.groups()
        hops=sorted({c['ipNexthopP']['attributes']['nhAddr'] for c in obj.get('children',[])
                     if c.get('ipNexthopP',{}).get('attributes',{}).get('nhAddr')})
        rows[dn]=dict(dn=dn,tenant=tenant,l3out=out,profile=profile,pod=pod,node=node,
            ip=a.get('ip') or prefix,next_hops=hops,preference=a.get('pref',''),description=a.get('descr',''))
    return sorted(rows.values(),key=lambda r:(r['tenant'],r['l3out'],r['pod'],r['node'],r['ip']))


def register_l3out(app,get,subnets,cached,json_route):
    @cached()
    def static_inventory():
        return inventory(get,lambda:collect_static_routes(get))

    @app.get('/api/l3out_static_routes')
    def l3out_static_api():
        return json_route(static_inventory)

    @app.get('/export_csv/l3out_static_routes')
    def l3out_static_csv():
        data=static_inventory();output=io.StringIO();writer=csv.writer(output)
        fields=['tenant','l3out','profile','pod','node','ip','next_hops','preference','description','dn']
        writer.writerow(['Tenant','L3Out','Node Profile','Pod','Node','Prefixo','Next hops','Preferência','Descrição','DN'])
        for row in select(data['rows'],request.args):
            writer.writerow([csv_cell('; '.join(row[k]) if isinstance(row[k],list) else row[k]) for k in fields])
        return Response('\ufeff'+output.getvalue(),mimetype='text/csv',headers={
            'Content-Disposition':'attachment; filename=l3out_static_routes.csv','Cache-Control':'no-store'})

    @cached()
    def l3out_inventory():
        return inventory(get,subnets)

    @app.get('/l3out_explorer')
    def l3out_explorer():
        return render_template('l3out_explorer.html')

    @app.get('/api/l3out_inventory')
    def l3out_inventory_api():
        return json_route(l3out_inventory)

    @app.get('/export_csv/l3out_selection')
    def l3out_selection_csv():
        data=l3out_inventory()
        output=io.StringIO();writer=csv.writer(output)
        fields=['tenant','l3out','instp','ip','scope']
        writer.writerow(['Tenant','L3Out','External EPG','Prefixo','Scope'])
        for row in select(data['rows'],request.args):
            writer.writerow([csv_cell(row.get(k,'')) for k in fields])
        return Response('\ufeff'+output.getvalue(),mimetype='text/csv',headers={
            'Content-Disposition':'attachment; filename=l3out_selection.csv','Cache-Control':'no-store'})
