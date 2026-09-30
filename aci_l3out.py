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


def register_l3out(app,get,subnets,cached,json_route):
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
