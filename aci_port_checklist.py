"""Read-only evidence checks for conventional Ethernet access selectors."""
import re
from urllib.parse import quote

from flask import jsonify, request
from werkzeug.exceptions import HTTPException
from aci_access import children, usage_tree
from aci_diagnostics import PHYSICAL_DN


def inside(value, low, high):
    try:
        return int(low) <= int(value) <= int(high)
    except (ValueError, TypeError):
        return False


def collect_checklist(dn, get):
    checks, memo = [], {}

    def add(title, status, message, evidence=()):
        checks.append(dict(title=title, status=status, message=message,
                           evidence=sorted(set(x for x in evidence if x))))

    def query(path, params=None):
        key = (path, tuple(sorted((params or {}).items())))
        if key not in memo:
            try:
                memo[key] = get(path, params=params)
            except HTTPException as error:
                if error.code == 401:
                    raise
                memo[key] = None
            except Exception:
                memo[key] = None
        return memo[key]

    def obj(target, cls):
        if not target.startswith(('uni/', 'topology/')) or any(c in target for c in ('?', '#', '\\')):
            return None
        data = query('/api/node/mo/'+quote(target, safe='/')+'.json', {'rsp-subtree':'full'})
        return next((x[cls] for x in data or [] if cls in x), None)

    def attrs(objects):
        return [x.get('attributes', {}) for x in objects]

    def relation(title, records, source):
        targets = [r.get('tDn', '') for r in records]
        if not records:
            add(title, 'unknown', 'Nenhuma relação retornada; dependência não confirmada.', [source])
            return False
        if any(r.get('state') in ('unformed', 'unresolved') for r in records):
            add(title, 'issue', 'A APIC informa relação não formada.', [source]+targets)
            return False
        if any(r.get('state') != 'formed' or not r.get('tDn') for r in records):
            add(title, 'unknown', 'Estado ou destino da relação não confirmado.', [source]+targets)
            return False
        add(title, 'ok', 'Relações formadas conforme a APIC.', [source]+targets)
        return True

    def finish():
        counts = {s:sum(c['status'] == s for c in checks) for s in ('ok','issue','unknown')}
        return dict(dn=dn, checks=checks, counts=counts,
                    status='issue' if counts['issue'] else 'unknown' if counts['unknown'] else 'ok',
                    scope='Configuração de acesso e bindings estáticos diretos. Não comprova tráfego, contratos ou encaminhamento. VMM, bindings via AEP, L3Out, FEX e breakout não são validados integralmente.')

    def pending(message):
        for title in ('Policy Group → AEP', 'AEP → domínios', 'EPGs / VLAN Pool'):
            add(title, 'unknown', message)
        return finish()

    match = PHYSICAL_DN.fullmatch(dn)
    if not match:
        raise ValueError('DN inválido.')
    pod, node, port = re.fullmatch(r'topology/pod-(\d+)/node-(\d+)/sys/phys-\[(.+)\]', dn).groups()
    physical = obj(dn, 'l1PhysIf')
    if physical is None:
        add('Interface física', 'unknown', 'Interface ausente ou consulta indisponível.', [dn])
        return pending('A interface não foi confirmada.')
    a = physical.get('attributes', {})
    add('Interface física', 'ok', 'Interface encontrada. Administrativo: '+a.get('adminSt', 'indisponível')+'. O estado não é um veredicto de configuração.', [dn])
    port_match = re.fullmatch(r'eth(\d+)/(\d+)', port)
    if not port_match:
        add('Seletores de acesso', 'unknown', 'Breakout/FEX fora da cobertura deste checklist.', [dn])
        return pending('Caminho não suportado nesta verificação.')
    profiles = query('/api/class/infraAccPortP.json', {'rsp-subtree':'full'})
    switches = query('/api/class/infraNodeP.json', {'rsp-subtree':'full'})
    nodes = query('/api/class/fabricNode.json')
    if profiles is None or switches is None or nodes is None:
        add('Seletores de acesso', 'unknown', 'Consulta de perfis ou inventário indisponível.')
        return pending('Não foi possível confirmar o Policy Group.')
    node_dns = {x.get('fabricNode', {}).get('attributes', {}).get('dn') for x in nodes
                if x.get('fabricNode', {}).get('attributes', {}).get('id') == node}
    if node_dns != {f'topology/pod-{pod}/node-{node}'}:
        add('Seletores de acesso', 'unknown', 'Pod/node ausente ou ambíguo no inventário.')
        return pending('Não foi possível confirmar o escopo do node.')
    groups = {r.get('attributes', {}).get('tDn', '') for p in profiles
              for s in children(p.get('infraAccPortP', {}), 'infraHPortS')
              for r in children(s, 'infraRsAccBaseGrp')}
    candidates = []
    for group in sorted(groups):
        for use in usage_tree(group, profiles, switches):
            if not any(inside(port_match[1], b['fromCard'], b['toCard']) and
                       inside(port_match[2], b['fromPort'], b['toPort']) for b in use['ports']):
                continue
            for switch in use['switch_profiles']:
                if any(inside(node, r['from'], r['to']) for leaf in switch['leaves'] for r in leaf['ranges']):
                    candidates.append((group, use, switch))
    unique = {(g, u['selector_dn'], s['dn']): (g,u,s) for g,u,s in candidates}
    if len(unique) != 1:
        add('Seletores de acesso', 'unknown', 'Nenhum seletor aplicável encontrado.' if not unique else
            'Mais de uma cadeia de seletores encontrada; não foi escolhido um grupo automaticamente.',
            [g for g,_,_ in candidates])
        return pending('Associação de Policy Group não confirmada.')
    group_dn, use, switch = next(iter(unique.values()))
    states = use['relation_states']+switch['states']
    status = 'ok' if all(s == 'formed' for s in states) else 'issue' if any(s in ('unformed','unresolved') for s in states) else 'unknown'
    add('Seletor → Policy Group', status, 'Faixas de node e porta correspondem. Estados: '+', '.join(states),
        [use['profile_dn'], use['selector_dn'], switch['dn'], group_dn])
    if status != 'ok':
        return pending('As relações dos seletores não estão confirmadas.')
    bundle = '/accbundle-' in group_dn
    group = obj(group_dn, 'infraAccBndlGrp' if bundle else 'infraAccPortGrp')
    if group is None:
        return pending('Objeto Policy Group ausente ou indisponível.')
    aep_rels = attrs(children(group, 'infraRsAttEntP'))
    if not relation('Policy Group → AEP', aep_rels, group_dn):
        add('AEP → domínios', 'unknown', 'Depende da confirmação do AEP.')
        add('EPGs / VLAN Pool', 'unknown', 'Depende da confirmação do AEP.')
        return finish()
    domains = set()
    domain_complete = True
    for r in aep_rels:
        aep = obj(r['tDn'], 'infraAttEntityP')
        if aep is None:
            add('AEP → domínios', 'unknown', 'Objeto AEP ausente ou indisponível.', [r['tDn']])
            domain_complete = False
            continue
        links = attrs(children(aep, 'infraRsDomP'))
        if not relation('AEP → domínios', links, r['tDn']):
            domain_complete = False
        domains.update(x['tDn'] for x in links if x.get('state') == 'formed' and x.get('tDn'))
    if bundle:
        add('EPGs / VLAN Pool', 'unknown', 'PC/vPC: a cadeia até o AEP foi consultada; bindings do caminho lógico não são inferidos pelo nome do grupo.', [group_dn])
        return finish()
    path = f'topology/pod-{pod}/paths-{node}/pathep-[{port}]'
    bindings = query('/api/class/fvRsPathAtt.json', {'query-target-filter':f'eq(fvRsPathAtt.tDn,"{path}")'})
    if bindings is None:
        add('Bindings estáticos', 'unknown', 'Consulta de bindings indisponível.', [path])
        return finish()
    records = [x['fvRsPathAtt']['attributes'] for x in bindings if 'fvRsPathAtt' in x
               and x['fvRsPathAtt'].get('attributes', {}).get('tDn') == path]
    if not records:
        add('EPGs / VLAN Pool', 'unknown', 'Nenhum binding estático direto retornado. Isso não prova ausência de EPGs via AEP, VMM ou outros caminhos.', [path])
    for binding in records:
        epg_dn = binding.get('dn', '').split('/rspathAtt-[')[0]
        title = epg_dn+' · '+binding.get('encap', 'encap indisponível')
        if not relation('Binding '+title, [binding], epg_dn):
            continue
        epg = obj(epg_dn, 'fvAEPg')
        if epg is None or not domain_complete:
            add('Domínio / VLAN '+title, 'unknown', 'EPG ou domínios do AEP não confirmados.', [epg_dn])
            continue
        links = attrs(children(epg, 'fvRsDomAtt'))
        common = [r for r in links if r.get('tDn') in domains and r.get('state') == 'formed']
        if not common:
            status = 'unknown' if any(r.get('state') not in ('formed','unformed','unresolved') for r in links) else 'issue'
            add('Domínio / VLAN '+title, status, 'Nenhum domínio com relação formada comum ao EPG e ao AEP.', [epg_dn]+list(domains))
            continue
        vlan_match = re.fullmatch(r'vlan-(\d+)', binding.get('encap', ''))
        if not vlan_match:
            add('Domínio / VLAN '+title, 'unknown', 'Encapsulamento VLAN não identificado.', [epg_dn])
            continue
        outcomes, evidence = [], [epg_dn]
        for link in common:
            domain_dn = link['tDn']
            evidence.append(domain_dn)
            if not domain_dn.startswith('uni/phys-'):
                outcomes.append('unknown')
                continue
            domain = obj(domain_dn, 'physDomP')
            pools = attrs(children(domain or {}, 'infraRsVlanNs'))
            if not pools:
                outcomes.append('unknown')
            for pool_link in pools:
                pool_dn = pool_link.get('tDn', '')
                evidence.append(pool_dn)
                pool = obj(pool_dn, 'fvnsVlanInstP') if pool_link.get('state') == 'formed' else None
                if pool is None:
                    outcomes.append('unknown')
                    continue
                blocks = attrs(children(pool, 'fvnsEncapBlk'))
                matching = [b for b in blocks if inside(vlan_match[1], b.get('from','').removeprefix('vlan-'), b.get('to','').removeprefix('vlan-'))]
                modes = [b.get('allocMode') if b.get('allocMode') not in (None,'','inherit') else pool.get('attributes',{}).get('allocMode') for b in matching]
                outcomes.append('ok' if 'static' in modes else 'unknown' if not blocks or any(m not in ('static','dynamic') for m in modes) else 'issue')
        status = 'ok' if 'ok' in outcomes else 'unknown' if not outcomes or 'unknown' in outcomes else 'issue'
        message = {'ok':'VLAN coberta por bloco estático de um domínio físico comum ao EPG e ao AEP.',
                   'issue':'VLAN não coberta por bloco estático nos pools físicos comuns consultados.',
                   'unknown':'Não foi possível verificar integralmente domínio, pool ou modo de alocação.'}[status]
        add('Domínio / VLAN '+title, status, message, evidence)
    return finish()


def register_checklist(app, get, cached, json_route):
    @cached(key_fn=lambda:'port_checklist:'+request.args['dn'])
    def report():
        return collect_checklist(request.args['dn'], get)

    @app.get('/api/port_checklist')
    def port_checklist_api():
        if not PHYSICAL_DN.fullmatch(request.args.get('dn','')):
            return jsonify(error='Informe um DN de interface física válido.'), 400
        return json_route(report)
