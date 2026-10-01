"""Read-only controller resources from procEntity and eqptStorage."""
import math
import re
from flask import render_template

NODE = re.compile(r'^(topology/pod-(\d+)/node-(\d+))(?:/|$)')


def number(value, maximum=None):
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(result) or result < 0 or (maximum is not None and result > maximum):
        return None
    return result


def collect_resources(get, warning):
    controllers = {}
    for item in get('/api/class/fabricNode.json'):
        a = item.get('fabricNode', {}).get('attributes', {})
        dn = a.get('dn', '')
        match = NODE.fullmatch(dn)
        if a.get('role') != 'controller' or not match:
            continue
        controllers[dn] = dict(dn=dn, pod=match[2], node=match[3],
            name=a.get('name') or match[3], model=a.get('model', ''),
            version=a.get('version', ''), state=a.get('fabricSt', ''),
            cpu_percent=None, memory_percent=None, process_dn='', process_modified='',
            disks=[], notices=[], health=None)
    if not controllers:
        return []

    # Each availability view can contain several peers. Match the child ID,
    # not the source node in the parent DN, to avoid attributing peer health.
    for dn, row in controllers.items():
        try:
            records = get('/api/node/mo/' + dn + '/av.json', params={
                'query-target': 'children', 'target-subtree-class': 'infraWiNode'})
            matches = {}
            for item in records:
                a = item.get('infraWiNode', {}).get('attributes', {})
                if (a.get('dn') == dn + '/av/node-' + row['node']
                        and str(a.get('id')) == row['node']
                        and str(a.get('podId', row['pod'])) == row['pod']):
                    matches[a['dn']] = a
            if len(matches) == 1:
                a = next(iter(matches.values()))
                row['health'] = {key: a.get(key, '') for key in (
                    'dn', 'health', 'adminSt', 'operSt', 'apicMode', 'failoverStatus', 'modTs')}
            else:
                row['notices'].append('Saúde indisponível: o controlador não foi identificado em sua visão infraWiNode.')
        except Exception:
            warning(f'Pod {row["pod"]} / Node {row["node"]}: consulta de saúde infraWiNode indisponível.')
            row['notices'].append('Saúde indisponível; os recursos são consultados separadamente.')

    def optional(cls):
        try:
            return get('/api/class/' + cls + '.json')
        except Exception:
            warning(f'Consulta {cls} indisponível; as demais métricas foram preservadas.')
            return []

    processes = {dn: {} for dn in controllers}
    for item in optional('procEntity'):
        a = item.get('procEntity', {}).get('attributes', {})
        match = NODE.match(a.get('dn', ''))
        if match and match[1] in controllers:
            processes[match[1]][a['dn']] = a
    for dn, row in controllers.items():
        candidates = list(processes[dn].values())
        if len(candidates) != 1:
            row['notices'].append('CPU e memória indisponíveis: procEntity ausente ou ambíguo para este controlador.')
            continue
        a = candidates[0]
        row['process_dn'] = a['dn']
        row['process_modified'] = a.get('modTs', '')
        row['cpu_percent'] = number(a.get('cpuPct'), 100)
        allocated, free = number(a.get('maxMemAlloc')), number(a.get('memFree'))
        if allocated is not None and allocated > 0 and free is not None and free <= allocated:
            row['memory_percent'] = round((allocated - free) / allocated * 100, 2)
        if row['cpu_percent'] is None or row['memory_percent'] is None:
            row['notices'].append('CPU ou memória sem valores válidos retornados pelo APIC.')

    seen = set()
    for item in optional('eqptStorage'):
        a = item.get('eqptStorage', {}).get('attributes', {})
        dn = a.get('dn', '')
        match = NODE.match(dn)
        if not match or match[1] not in controllers or dn in seen:
            continue
        seen.add(dn)
        controllers[match[1]]['disks'].append(dict(dn=dn,
            mount=a.get('mount') or a.get('name') or 'Não informado',
            filesystem=a.get('fileSystem', ''), state=a.get('operSt', ''),
            percent=number(a.get('capUtilized'), 100), modified=a.get('modTs', ''),
            reason=a.get('failReason', '')))
    for row in controllers.values():
        row['disks'].sort(key=lambda disk: (disk['mount'], disk['dn']))
        if not row['disks']:
            row['notices'].append('Nenhum registro de armazenamento disponível para este controlador.')
    return sorted(controllers.values(), key=lambda row: (int(row['pod']), int(row['node'])))


def register_resources(app, get, cached, json_route, warning):
    @cached()
    def resources():
        return collect_resources(get, warning)

    @app.get('/apic_resources')
    def apic_resources_page():
        return render_template('apic_resources.html')

    @app.get('/api/apic_resources')
    def apic_resources_api():
        return json_route(resources)
