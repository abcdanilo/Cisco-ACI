"""Bounded, server-filtered event and configuration audit history."""
import json
import re
from datetime import datetime, timezone, timedelta
from flask import request, jsonify, render_template

CLASSES = {'events':'eventRecord', 'audit':'aaaModLR'}


def query(args):
    kind = args.get('kind','audit')
    if kind not in CLASSES:
        raise ValueError('Tipo de histórico inválido.')
    def date(key, default):
        value = args.get(key)
        if not value:
            return default
        try:
            result = datetime.fromisoformat(value.replace('Z','+00:00'))
            if result.tzinfo is None:
                raise ValueError()
            return result.astimezone(timezone.utc)
        except ValueError:
            raise ValueError('Informe datas válidas com fuso horário.')
    end = date('end',datetime.now(timezone.utc))
    start = date('start',end-timedelta(days=1))
    if not timedelta(0) < end-start <= timedelta(days=31):
        raise ValueError('O período deve ser positivo e de até 31 dias.')
    try:
        page = int(args.get('page','0'))
        if not 0 <= page <= 1999:
            raise ValueError()
    except ValueError:
        raise ValueError('Página inválida; refine o período para consultar mais registros.')
    cls = CLASSES[kind]
    filters = [f'ge({cls}.created,{json.dumps(start.isoformat())})',
               f'le({cls}.created,{json.dumps(end.isoformat())})']
    dn = args.get('dn','').strip()
    if len(dn)>1024 or any(ord(c)<32 for c in dn):
        raise ValueError('DN inválido.')
    if dn:
        filters.append(f'eq({cls}.affected,{json.dumps(dn)})')
    text = args.get('q','').strip()
    if len(text)>120 or any(ord(c)<32 for c in text):
        raise ValueError('Use até 120 caracteres na busca por texto.')
    if text:
        # Literal substring, ASCII case insensitive; no user-supplied regex.
        pattern = ''.join('['+c.lower()+c.upper()+']' if c.isascii() and c.isalpha() else re.escape(c) for c in text)
        filters.append('or('+','.join(f'wcard({cls}.{field},{json.dumps(pattern)})' for field in ('descr','affected','user','code'))+')')
    return cls, {'query-target-filter' :'and('+','.join(filters)+')',
                 'order-by':cls+'.created|desc','page':page,'page-size':50}, start,end


def collect(args, get_page):
    cls, params, start, end = query(args)
    objects = get_page('/api/class/'+cls+'.json', params)
    rows=[]
    for item in objects:
        if cls not in item:
            continue
        a=item[cls].get('attributes',{})
        rows.append({k:a.get(k,'') for k in ('dn','created','affected','descr','user','ind','code','severity','cause')})
    return {'rows':rows,'page':params['page'],'has_more':len(objects)==50 and params['page']<1999,
            'start':start.isoformat(),'end':end.isoformat(),'kind':'audit' if cls=='aaaModLR' else 'events'}


def register_history(app,get_page,json_route):
    @app.get('/history')
    def history_page():
        return render_template('history.html')

    @app.get('/api/history')
    def history_api():
        try:
            query(request.args)
        except ValueError as error:
            return jsonify(error=str(error)),400
        return json_route(lambda:collect(request.args,get_page))
