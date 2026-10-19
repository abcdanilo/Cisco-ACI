"""Contract relationships and configured filter rules, not forwarding verdicts."""
import json
import re
from flask import render_template
from werkzeug.exceptions import HTTPException


def tenant(dn):
    match = re.match(r'uni/tn-([^/]+)', dn)
    return match[1] if match else ''


def walk(objects):
    for item in objects:
        for kind, obj in item.items():
            yield kind, obj
            yield from walk(obj.get('children', []))


def resolve(a, name_field, prefix, objects, owner):
    target = a.get('tDn', '')
    if target:
        return target, 'DN informado pela APIC' if target in objects else 'Destino não retornado'
    name = a.get(name_field, '')
    choices = [dn for dn in objects if dn in
               (f'uni/tn-{tenant(owner)}/{prefix}-{name}', f'uni/tn-common/{prefix}-{name}')]
    if name and len(choices) == 1:
        return choices[0], 'Correlação por nome e tenant; destino não confirmado'
    return '', 'Destino ausente ou ambíguo'


def collect_contract_relations(get):
    warnings, coverage = [], {}

    def query(cls, subtree=False):
        try:
            data = get('/api/class/'+cls+'.json', params={'rsp-subtree':'full'} if subtree else {})
            coverage[cls] = True
            return data
        except HTTPException as error:
            if error.code == 401:
                raise
        except Exception:
            pass
        coverage[cls] = False
        warnings.append('Consulta '+cls+' indisponível; os resultados estão incompletos.')
        return []

    contracts = {o.get('attributes', {}).get('dn'): o for k,o in walk(query('vzBrCP', True)) if k == 'vzBrCP' and o.get('attributes', {}).get('dn')}
    filters = {o.get('attributes', {}).get('dn'): o for k,o in walk(query('vzFilter', True)) if k == 'vzFilter' and o.get('attributes', {}).get('dn')}
    rows = {}
    for dn, obj in contracts.items():
        a = obj.get('attributes', {})
        subjects = []
        for kind, subject in walk(obj.get('children', [])):
            if kind != 'vzSubj':
                continue
            sa = subject.get('attributes', {})
            rules, extras = [], []
            for ck, co in walk(subject.get('children', [])):
                ca = co.get('attributes', {})
                if ck not in ('vzRsSubjFiltAtt', 'vzRsFiltAtt'):
                    if ck in ('vzRsSubjGraphAtt', 'vzRsInTermGraphAtt', 'vzRsOutTermGraphAtt', 'vzRsSubjGraphAtt'):
                        extras.append(dict(type=ck, attributes=ca))
                    continue
                target, association = resolve(ca, 'tnVzFilterName', 'flt', filters, dn)
                relation_dn = ca.get('dn', '')
                direction = 'Consumidor → provedor' if '/intmnl/' in relation_dn else 'Provedor → consumidor' if '/outtmnl/' in relation_dn else 'Subject (ver opções de direção)'
                rules.append(dict(dn=relation_dn, name=ca.get('tnVzFilterName',''), target=target,
                    state=ca.get('state','unknown'), association=association, direction=direction,
                    action=ca.get('action',''), directives=ca.get('directives',''),
                    attributes=ca, available=target in filters,
                    entries=[eo.get('attributes',{}) for ek,eo in walk(filters.get(target,{}).get('children',[])) if ek == 'vzEntry']))
            subjects.append(dict(name=sa.get('name',''), dn=sa.get('dn',''), attributes=sa, filters=rules, services=extras))
        rows[dn] = dict(dn=dn, name=a.get('name',''), tenant=tenant(dn), scope=a.get('scope',''),
                        description=a.get('descr',''), available=True, providers=[], consumers=[], subjects=subjects)
    for cls, role in [('fvRsProv','providers'),('fvRsCons','consumers'),
                      ('vzRsAnyToProv','providers'),('vzRsAnyToCons','consumers')]:
        for kind, obj in walk(query(cls)):
            if kind != cls:
                continue
            a = obj.get('attributes', {})
            rel_dn = a.get('dn','')
            owner = rel_dn.rsplit('/',1)[0]
            target, association = resolve(a, 'tnVzBrCPName', 'brc', contracts, owner)
            key = target or 'unresolved:'+rel_dn
            if key not in rows:
                rows[key] = dict(dn=target, name=a.get('tnVzBrCPName',''), tenant=tenant(target) or tenant(owner),
                    scope='', description='', available=False, providers=[], consumers=[], subjects=[])
            kind_name = 'vzAny' if cls.startswith('vz') else 'External EPG' if '/out-' in owner and '/instP-' in owner else 'EPG' if '/ap-' in owner and '/epg-' in owner else 'Outro objeto'
            rows[key][role].append(dict(dn=owner, tenant=tenant(owner), type=kind_name,
                relation_dn=rel_dn, state=a.get('state','unknown'), association=association,
                confirmed=bool(a.get('tDn') in contracts and a.get('state') == 'formed')))
    for row in rows.values():
        for role in ('providers','consumers'):
            row[role] = sorted({r['relation_dn']:r for r in row[role]}.values(), key=lambda r:r['dn'])
        row['tenants'] = sorted({row['tenant']} | {r['tenant'] for role in ('providers','consumers') for r in row[role]})
        row['search'] = json.dumps(row,ensure_ascii=False).casefold()
    return dict(rows=sorted(rows.values(),key=lambda r:(r['tenant'],r['name'],r['dn'])), warnings=warnings,
                coverage=coverage, scope='Relações diretas e vzAny configuradas. Não calcula permissão efetiva de tráfego. Herança, contratos importados, taboo, preferred groups, exceções, escopo de VRF e regras programadas no hardware não são avaliados integralmente. Ausência de consumidores/provedores não comprova contrato sem uso.')


def register_contract_relations(app, get, cached, json_route):
    @cached()
    def report():
        return collect_contract_relations(get)

    @app.get('/contract_relations')
    def contract_relations_page():
        return render_template('contract_relations.html')

    @app.get('/api/contract_relations')
    def contract_relations_api():
        return json_route(report)
