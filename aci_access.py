"""Read-only access policy details and explicit configuration relationships."""
import re
from urllib.parse import quote
from flask import request, jsonify, render_template
from werkzeug.exceptions import NotFound

GROUP = re.compile(r'uni/infra/funcprof/accportgrp-[^/\s?#]+')
LABELS = {'infraRsAttEntP':'AEP', 'infraRsCdpIfPol':'CDP',
          'infraRsLldpIfPol':'LLDP', 'infraRsHIfPol':'Velocidade / Link Level',
          'infraRsStpIfPol':'Spanning Tree', 'infraRsMcpIfPol':'MCP',
          'infraRsL2IfPol':'Camada 2', 'infraRsL2PortSecurityPol':'Port Security',
          'infraRsQosPfcIfPol':'Priority Flow Control',
          'infraRsQosLlfcIfPol':'Link-Level Flow Control',
          'infraRsStormctrlIfPol':'Storm Control', 'infraRsMonIfInfraPol':'Monitoramento'}
META = {'annotation','childAction','creator','dn','rn','extMngdBy','lcOwn',
        'modTs','monPolDn','name','nameAlias','ownerKey','ownerTag','status','uid','userdom'}


def children(obj, kind):
    return [c[kind] for c in obj.get('children', []) if kind in c]


def usage_tree(group_dn, profiles, switches):
    usages = []
    for item in profiles:
        profile = item.get('infraAccPortP', {})
        pa = profile.get('attributes', {})
        for selector in children(profile, 'infraHPortS'):
            relations = [r.get('attributes', {}) for r in children(selector, 'infraRsAccBaseGrp')
                         if r.get('attributes', {}).get('tDn') == group_dn]
            if not relations:
                continue
            sa = selector.get('attributes', {})
            blocks = [b.get('attributes', {}) for b in children(selector, 'infraPortBlk')]
            switch_profiles = []
            for node in switches:
                obj = node.get('infraNodeP', {})
                links = [r.get('attributes', {}) for r in children(obj, 'infraRsAccPortP')
                         if pa.get('dn') and r.get('attributes', {}).get('tDn') == pa['dn']]
                if not links:
                    continue
                na = obj.get('attributes', {})
                leaves = []
                for leaf in children(obj, 'infraLeafS'):
                    leaves.append({'name':leaf.get('attributes', {}).get('name',''),
                                   'ranges':[{'from':b.get('attributes',{}).get('from_',''),
                                              'to':b.get('attributes',{}).get('to_','')}
                                             for b in children(leaf,'infraNodeBlk')]})
                switch_profiles.append({'name':na.get('name',''), 'dn':na.get('dn',''),
                                        'states':[r.get('state','unknown') for r in links], 'leaves':leaves})
            usages.append({'profile':pa.get('name',''), 'profile_dn':pa.get('dn',''),
                           'selector':sa.get('name',''),
                           'selector_dn':sa.get('dn') or (pa.get('dn','')+'/'+sa.get('rn','')),
                           'relation_states':[r.get('state','unknown') for r in relations],
                           'ports':[{k:b.get(k,'') for k in ('fromCard','toCard','fromPort','toPort')} for b in blocks],
                           'switch_profiles':switch_profiles})
    return usages


def collect_access(dn, get, warning):
    data = get('/api/node/mo/'+quote(dn,safe='/')+'.json', params={'rsp-subtree':'children'})
    group = next((x['infraAccPortGrp'] for x in data if 'infraAccPortGrp' in x), None)
    if group is None:
        raise NotFound('Leaf Access Port Policy Group não encontrado.')
    policies, targets = [], {}
    for child in group.get('children', []):
        for kind, obj in child.items():
            if not kind.startswith('infraRs'):
                continue
            attr = obj.get('attributes', {})
            target = attr.get('tDn','')
            record = {'label':LABELS.get(kind,kind), 'relation':kind,'dn':target,
                      'state':attr.get('state','unknown'), 'default':attr.get('stateQual') == 'default-target',
                      'available':False,'name':'','values':{},'children':[]}
            # Only APIC-provided infrastructure objects, never arbitrary URLs.
            if target.startswith('uni/infra/') and '?' not in target and '#' not in target:
                if target not in targets:
                    try:
                        targets[target] = get('/api/node/mo/'+quote(target,safe='/')+'.json',params={'rsp-subtree':'children'})
                    except Exception:
                        targets[target] = []
                        warning(f'Política indisponível: {target}')
                found = targets[target]
                if found:
                    policy = next(iter(found[0].values()))
                    values = policy.get('attributes',{})
                    record.update(available=True,name=values.get('name',''),
                                  values={k:v for k,v in values.items() if k not in META and v != ''})
                    for c in policy.get('children',[]):
                        for ck, co in c.items():
                            ca = co.get('attributes',{})
                            record['children'].append({'class':ck,'values':{k:v for k,v in ca.items() if k not in META and v != ''}})
            policies.append(record)
    def optional(cls):
        try:
            return get('/api/class/'+cls+'.json',params={'rsp-subtree':'full'})
        except Exception:
            warning(f'Utilização incompleta: consulta {cls} indisponível.')
            return []
    profiles, switches = optional('infraAccPortP'), optional('infraNodeP')
    a = group.get('attributes',{})
    return {'dn':dn,'name':a.get('name',''),'description':a.get('descr',''),
            'policies':sorted(policies,key=lambda p:p['label']),
            'usage':usage_tree(dn,profiles,switches)}


def register_access(app, get, cached, json_route, warning):
    @app.get('/access_group')
    def access_group_page():
        return render_template('access_group.html')

    @cached(key_fn=lambda:'access_group:'+request.args['dn'])
    def details():
        return collect_access(request.args['dn'],get,warning)

    @app.get('/api/access_group')
    def access_group_api():
        if not GROUP.fullmatch(request.args.get('dn','')):
            return jsonify(error='Informe um DN de Leaf Access Port Policy Group válido.'),400
        return json_route(details)
