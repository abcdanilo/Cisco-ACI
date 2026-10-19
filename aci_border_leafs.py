"""Configured L3Out node attachments, not operational routing state."""
import re
from flask import render_template
from werkzeug.exceptions import HTTPException


def children(obj, cls):
    return [x[cls] for x in obj.get('children',[]) if cls in x]


def walk(obj, cls):
    for item in obj.get('children',[]):
        for kind, value in item.items():
            if kind == cls:
                yield value
            yield from walk(value, cls)


def attrs(obj):
    return obj.get('attributes',{})


def path_nodes(path):
    m = re.fullmatch(r'topology/pod-(\d+)/(?:paths-(\d+)|protpaths-(\d+)-(\d+))/(?:extpaths-\d+/)?pathep-\[.+\]',path)
    return {(m[1], n) for n in m.groups()[1:] if n} if m else set()


def collect_border_leafs(get):
    # Essential inventory must fail visibly, never become a successful empty report.
    outs = get('/api/class/l3extOut.json',params={'rsp-subtree':'full'})
    warnings, nodes = [], {}
    try:
        nodes = {attrs(x['fabricNode']).get('dn'):attrs(x['fabricNode'])
                 for x in get('/api/class/fabricNode.json') if 'fabricNode' in x}
    except HTTPException as error:
        if error.code == 401:
            raise
        warnings.append('Inventário de switches indisponível; nomes e estado do fabric não verificados.')
    except Exception:
        warnings.append('Inventário de switches indisponível; nomes e estado do fabric não verificados.')
    rows, unmapped = {}, []
    for item in outs:
        obj = item.get('l3extOut',{})
        oa = attrs(obj); out_dn = oa.get('dn','')
        m = re.fullmatch(r'uni/tn-([^/]+)/out-([^/]+)',out_dn)
        if not m:
            continue
        tenant, name = m.groups()
        vrfs = [dict(name=attrs(x).get('tnFvCtxName',''),dn=attrs(x).get('tDn',''),state=attrs(x).get('state','unknown')) for x in children(obj,'l3extRsEctx')]
        protocols = [label for cls,label in [('bgpExtP','BGP'),('ospfExtP','OSPF'),('eigrpExtP','EIGRP')] if children(obj,cls)]
        profiles = children(obj,'l3extLNodeP')
        if not profiles:
            unmapped.append(dict(tenant=tenant,l3out=name,dn=out_dn,reason='Nenhum node profile retornado.'))
        for profile in profiles:
            pa = attrs(profile); profile_dn = pa.get('dn') or out_dn+'/lnodep-'+pa.get('name','')
            attachments = children(profile,'l3extRsNodeL3OutAtt')
            if not attachments:
                unmapped.append(dict(tenant=tenant,l3out=name,dn=profile_dn,reason='Nenhuma associação de node retornada.'))
            mapped = set()
            for attachment in attachments:
                a = attrs(attachment); target = a.get('tDn','')
                node_match = re.fullmatch(r'topology/pod-(\d+)/node-(\d+)',target)
                if not node_match:
                    unmapped.append(dict(tenant=tenant,l3out=name,dn=a.get('dn',profile_dn),reason='Destino de node ausente ou não reconhecido.'))
                    continue
                pod,node = node_match.groups(); mapped.add((pod,node)); na = nodes.get(target,{})
                routes = {}
                for route in children(attachment,'ipRouteP'):
                    ra = attrs(route)
                    hops = [attrs(h) for h in children(route,'ipNexthopP')]
                    key = ra.get('dn') or ra.get('ip','')
                    routes[key] = dict(prefix=ra.get('ip',''),preference=ra.get('pref',''),dn=ra.get('dn',''),next_hops=hops)
                interfaces = []
                for interface_profile in children(profile,'l3extLIfP'):
                    for path in children(interface_profile,'l3extRsPathL3OutAtt'):
                        ia = attrs(path)
                        if (pod,node) not in path_nodes(ia.get('tDn','')):
                            continue
                        interfaces.append(dict(profile=attrs(interface_profile).get('name',''),path=ia.get('tDn',''),
                            address=ia.get('addr',''),encap=ia.get('encap',''),type=ia.get('ifInstT',''),state=ia.get('state','unknown'),
                            members=[attrs(x) for x in children(path,'l3extMember')],dn=ia.get('dn','')))
                rows[(out_dn,profile_dn,target)] = dict(tenant=tenant,l3out=name,out_dn=out_dn,profile=pa.get('name',''),profile_dn=profile_dn,
                    pod=pod,node=node,node_dn=target,node_name=na.get('name',''),node_state=na.get('fabricSt',''),node_role=na.get('role',''),
                    state=a.get('state','unknown'),router_id=a.get('rtrId',''),router_id_loopback=a.get('rtrIdLoopBack',''),
                    vrfs=vrfs,protocols=protocols,routes=list(routes.values()),interfaces=interfaces)
            for interface_profile in children(profile,'l3extLIfP'):
                for path in children(interface_profile,'l3extRsPathL3OutAtt'):
                    a = attrs(path); targets = path_nodes(a.get('tDn',''))
                    if not targets or not targets.issubset(mapped):
                        unmapped.append(dict(tenant=tenant,l3out=name,dn=a.get('dn') or a.get('tDn',profile_dn),reason='Caminho de interface sem associação completa aos nodes deste profile.'))
    return dict(rows=sorted(rows.values(),key=lambda r:(int(r['pod']),int(r['node']),r['tenant'],r['l3out'],r['profile_dn'])),
        unmapped=unmapped,warnings=warnings,
        scope='Configuração por associação de node e node profile. Protocolos são opções do L3Out; não indicam vizinhança ativa. Rotas estáticas não são rotas aprendidas nem comprovam instalação na tabela. Caminhos vPC mostram os membros A/B sem inferir o IP de cada node. Ausência de dados pode refletir permissões da conta APIC.')


def register_border_leafs(app,get,cached,json_route):
    @cached()
    def report():
        return collect_border_leafs(get)

    @app.get('/l3out_by_leaf')
    def l3out_by_leaf_page():
        return render_template('l3out_by_leaf.html')

    @app.get('/api/l3out_by_leaf')
    def l3out_by_leaf_api():
        return json_route(report)
