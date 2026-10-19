"""Observed fabric topology; no assumed full-mesh or link health."""
import re
from flask import render_template
from werkzeug.exceptions import HTTPException


def collect_fabric_map(get):
    nodes={}
    for item in get('/api/class/fabricNode.json'):
        a=item.get('fabricNode',{}).get('attributes',{})
        dn=a.get('dn','');m=re.fullmatch(r'topology/pod-(\d+)/node-(\d+)',dn)
        if m and a.get('role') in ('leaf','spine'):
            nodes[dn]=dict(dn=dn,pod=m[1],node=m[2],name=a.get('name',''),role=a['role'],
                           state=a.get('fabricSt',''),model=a.get('model',''),serial=a.get('serial',''))
    warnings,unresolved,links,coverage=[],[],{},{}
    def query(cls):
        try:
            data=get('/api/class/'+cls+'.json');coverage[cls]=True;return data
        except HTTPException as e:
            if e.code==401:raise
        except Exception:pass
        coverage[cls]=False;warnings.append('Consulta '+cls+' indisponível; topologia parcial.');return []
    def add(left,lp,right,rp,source,a):
        if left==right:return
        ends=sorted([(left,lp),(right,rp)])
        key=tuple(ends)
        row=links.setdefault(key,dict(a=ends[0][0],a_port=ends[0][1],b=ends[1][0],b_port=ends[1][1],sources=[],evidence=[]))
        if source not in row['sources']:row['sources'].append(source)
        if a not in row['evidence']:row['evidence'].append(a)
    def port(value):
        m=re.fullmatch(r'(?:eth|ethernet)(\d+/\d+(?:/\d+)?)',value or '',re.I)
        return 'eth'+m[1] if m else ''
    for item in query('fabricLink'):
        a=item.get('fabricLink',{}).get('attributes',{})
        pod=re.search(r'(?:^|/)pod-(\d+)(?:/|$)',a.get('dn',''))
        ends=[]
        for suffix in ('1','2'):
            candidates=[n['dn'] for n in nodes.values() if n['node']==a.get('n'+suffix)
                        and (not pod or n['pod']==pod[1])]
            slot,p=a.get('s'+suffix,''),a.get('p'+suffix,'')
            ends.append((candidates[0],f'eth{slot}/{p}') if len(candidates)==1 and slot.isdigit() and p.isdigit() else None)
        if all(ends):add(*ends[0],*ends[1],'fabricLink',a)
        else:unresolved.append(dict(source='fabricLink',dn=a.get('dn',''),reason='Nodes/portas ausentes, fora do inventário leaf/spine ou ambíguos.'))
    for item in query('lldpAdjEp'):
        a=item.get('lldpAdjEp',{}).get('attributes',{})
        m=re.fullmatch(r'(topology/pod-\d+/node-\d+)/sys/lldp/inst/if-\[(.+)\]/adj-[^/]+',a.get('dn',''))
        if not m or m[1] not in nodes:continue
        candidates=[n['dn'] for n in nodes.values() if n['name'] and n['name']==a.get('sysName')]
        lp,rp=port(m[2]),port(a.get('portIdV',''))
        if len(candidates)==1 and lp and rp:
            add(m[1],lp,candidates[0],rp,'LLDP por nome exato e único',a)
        else:
            unresolved.append(dict(source='LLDP',dn=a.get('dn',''),reason='Vizinho externo, nome ambíguo ou porta não identificada; não desenhado.'))
    return dict(nodes=sorted(nodes.values(),key=lambda n:(int(n['pod']),n['role'],int(n['node']))),
                links=list(links.values()),warnings=warnings,unresolved=unresolved,coverage=coverage,
                scope='Enlaces retornados por fabricLink e adjacências LLDP correlacionadas por nome exato e único. Linhas não comprovam tráfego nem saúde operacional. Ausência de enlace não comprova falha. Nós sem enlaces retornados permanecem visíveis; APICs e equipamentos externos não fazem parte do mapa.')


def register_fabric_map(app,get,cached,json_route):
    @cached()
    def report():return collect_fabric_map(get)
    @app.get('/fabric_map')
    def fabric_map_page():return render_template('fabric_map.html')
    @app.get('/api/fabric_map')
    def fabric_map_api():return json_route(report)
