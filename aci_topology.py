"""Hierarchy of configured L3Out objects, preserving APIC source attributes."""
import re
from flask import render_template
from aci_border_leafs import attrs, children


def collect_topology(get):
    data = get('/api/class/l3extOut.json', params={'rsp-subtree':'full'})
    result = []
    for item in data:
        obj = item.get('l3extOut', {})
        a = attrs(obj); dn = a.get('dn','')
        match = re.fullmatch(r'uni/tn-([^/]+)/out-([^/]+)',dn)
        if not match:
            continue
        profiles = []
        for profile in children(obj,'l3extLNodeP'):
            nodes, interfaces = [], []
            for node in children(profile,'l3extRsNodeL3OutAtt'):
                nodes.append(dict(attributes=attrs(node), routes=[dict(attributes=attrs(r),
                    next_hops=[attrs(h) for h in children(r,'ipNexthopP')]) for r in children(node,'ipRouteP')]))
            for interface in children(profile,'l3extLIfP'):
                paths = []
                for path in children(interface,'l3extRsPathL3OutAtt'):
                    paths.append(dict(attributes=attrs(path),secondary=[attrs(s) for s in children(path,'l3extIp')],
                        members=[dict(attributes=attrs(m),secondary=[attrs(s) for s in children(m,'l3extIp')]) for m in children(path,'l3extMember')]))
                interfaces.append(dict(attributes=attrs(interface), paths=paths))
            profiles.append(dict(attributes=attrs(profile),nodes=nodes,interfaces=interfaces))
        epgs=[]
        for epg in children(obj,'l3extInstP'):
            epgs.append(dict(attributes=attrs(epg),prefixes=[attrs(s) for s in children(epg,'l3extSubnet')],
                providers=[attrs(s) for s in children(epg,'fvRsProv')],consumers=[attrs(s) for s in children(epg,'fvRsCons')]))
        result.append(dict(dn=dn,tenant=match[1],name=match[2],description=a.get('descr',''),
            vrfs=[attrs(r) for r in children(obj,'l3extRsEctx')],profiles=profiles,epgs=epgs,
            protocols=[label for cls,label in [('bgpExtP','BGP'),('ospfExtP','OSPF'),('eigrpExtP','EIGRP')] if children(obj,cls)]))
    return dict(l3outs=sorted(result,key=lambda r:(r['tenant'],r['name'])),
        scope='Mapa da configuração retornada pela APIC. Next hops não identificam automaticamente firewalls ou VIPs. Ausência de relação não comprova ausência de conectividade. Endereços A/B de vPC são mostrados sem inferir qual membro corresponde a cada node.')


def register_topology(app,get,cached,json_route):
    @cached()
    def report():
        return collect_topology(get)

    @app.get('/l3out_map')
    def l3out_map_page():
        return render_template('l3out_map.html')

    @app.get('/api/l3out_map')
    def l3out_map_api():
        return json_route(report)
