"""Tenant health and switch CPU: read-only, with explicit missing samples."""
from datetime import datetime
from urllib.parse import quote
from flask import render_template
from aci_resources import NODE, number


def timestamp(value):
    try:
        parsed=datetime.fromisoformat(value.replace('Z','+00:00'))
        return parsed.timestamp() if parsed.tzinfo else None
    except (ValueError,TypeError,AttributeError):
        return None


def tenant_health(get,warning):
    tenants={}
    for item in get('/api/class/fvTenant.json'):
        a=item.get('fvTenant',{}).get('attributes',{});dn=a.get('dn','')
        if not dn.startswith('uni/tn-') or '/' in dn[7:]:continue
        tenants[dn]=a.get('name') or dn[7:]
    rows=[]
    for dn,name in sorted(tenants.items()):
        row=dict(tenant=name,dn=dn,score=None,updated='',faults={k:None for k in ['critical','major','minor','warning']},notices=[])
        for suffix,classes in [('health',['healthInst']),('fltCnts',['faultCountsWithDetails','faultCounts'])]:
            try:
                objects=get('/api/mo/'+quote(dn,safe='/')+'/'+suffix+'.json')
                values=[obj[cls]['attributes'] for obj in objects for cls in classes
                        if obj.get(cls,{}).get('attributes',{}).get('dn')==dn+'/'+suffix]
                if len(values)!=1:
                    row['notices'].append('Saúde indisponível.' if suffix=='health' else 'Contagem de faults indisponível.')
                    continue
                a=values[0]
                if suffix=='health':
                    row.update(score=number(a.get('cur'),100),updated=a.get('updTs',''))
                else:
                    for label,key in [('critical','crit'),('major','maj'),('minor','minor'),('warning','warn')]:
                        value=number(a.get(key))
                        row['faults'][label]=int(value) if value is not None and value.is_integer() else None
            except Exception:
                warning(f'Tenant {name}: consulta {suffix} indisponível.')
                row['notices'].append('Consulta '+suffix+' indisponível.')
        rows.append(row)
    return rows


def switch_cpu(get,warning):
    nodes={}
    for item in get('/api/class/fabricNode.json'):
        a=item.get('fabricNode',{}).get('attributes',{});dn=a.get('dn','');match=NODE.fullmatch(dn)
        if not match or a.get('role') not in ('leaf','spine'):continue
        nodes[dn]=dict(dn=dn,name=a.get('name') or match[3],pod=match[2],node=match[3],role=a['role'],
                       cpu=None,user=None,kernel=None,start='',end='',sample_dn='',notice='Amostra indisponível.')
    if not nodes:return []
    try:objects=get('/api/class/procSysCPU5min.json')
    except Exception:
        warning('Consulta procSysCPU5min indisponível; inventário de switches preservado.');objects=[]
    candidates={dn:{} for dn in nodes}
    for item in objects:
        a=item.get('procSysCPU5min',{}).get('attributes',{});dn=a.get('dn','');match=NODE.match(dn)
        if match and match[1] in nodes:candidates[match[1]][dn]=a
    for dn,row in nodes.items():
        values=list(candidates[dn].values())
        if not values:continue
        dated=[a for a in values if timestamp(a.get('repIntvEnd')) is not None]
        if dated:
            latest=max(timestamp(a['repIntvEnd']) for a in dated)
            values=[a for a in dated if timestamp(a['repIntvEnd'])==latest]
        if len(values)!=1:
            row['notice']='Mais de uma amostra candidata; utilização não consolidada.';continue
        a=values[0];row.update(start=a.get('repIntvStart',''),end=a.get('repIntvEnd',''),sample_dn=a['dn'])
        if str(a.get('suspect','')).lower() in ('yes','true','1'):
            row['notice']='APIC marcou a amostra como suspeita.';continue
        idle=number(a.get('idleAvg'),100)
        row.update(cpu=round(100-idle,2) if idle is not None else None,
                   user=number(a.get('userAvg'),100),kernel=number(a.get('kernelAvg'),100),notice='')
        if idle is None:row['notice']='Utilização indisponível: idleAvg ausente ou inválido.'
        if timestamp(row['start']) is None or timestamp(row['end']) is None:
            row['notice']+=' Período da amostra não informado.'
    return sorted(nodes.values(),key=lambda r:(int(r['pod']),int(r['node'])))


def register_health(app,get,cached,json_route,warning):
    @cached()
    def tenants():return tenant_health(get,warning)

    @cached()
    def switches():return switch_cpu(get,warning)

    @app.get('/tenant_health')
    def tenant_health_page():return render_template('operational_health.html',kind='tenant')

    @app.get('/switch_cpu')
    def switch_cpu_page():return render_template('operational_health.html',kind='cpu')

    @app.get('/api/tenant_health')
    def tenant_health_api():return json_route(tenants)

    @app.get('/api/switch_cpu')
    def switch_cpu_api():return json_route(switches)
