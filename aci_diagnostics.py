"""Read-only endpoint lookup and physical-interface diagnostics."""
import csv
import io
import ipaddress
import math
import re
import copy
from urllib.parse import quote

from flask import Response, jsonify, render_template, request
from werkzeug.exceptions import NotFound


PHYSICAL_DN = re.compile(r"topology/pod-[1-9]\d*/node-[1-9]\d*/sys/phys-\[eth\d+/\d+(?:/\d+)?\]")


def normalize_lookup(value):
    value = value.strip()
    if not value or len(value) > 80:
        raise ValueError("Informe um endereço IPv4, IPv6 ou MAC completo.")
    try:
        return "ip", str(ipaddress.ip_address(value))
    except ValueError:
        pass
    if re.fullmatch(r"[0-9a-fA-F]{12}|(?:[0-9a-fA-F]{2}:){5}[0-9a-fA-F]{2}|(?:[0-9a-fA-F]{2}-){5}[0-9a-fA-F]{2}|(?:[0-9a-fA-F]{4}\.){2}[0-9a-fA-F]{4}", value):
        return "mac", re.sub(r"[:.\-]", "", value).upper()
    raise ValueError("Endereço inválido. Use IPv4, IPv6 ou MAC completo (ex.: AA:BB:CC:DD:EE:FF).")


def canonical_ip(value):
    try:
        address = ipaddress.ip_address(value)
        return "" if address.is_unspecified else str(address)
    except ValueError:
        return ""


def path_information(dn):
    """Only physical paths with an unambiguous node receive a diagnostics link."""
    direct = re.fullmatch(r"topology/pod-(\d+)/paths-(\d+)/pathep-\[(eth\d+/\d+(?:/\d+)?)\]", dn)
    if direct:
        pod, node, interface = direct.groups()
        return {"dn": dn, "label": f"Pod {pod} / Node {node} / {interface}",
                "interface_dn": f"topology/pod-{pod}/node-{node}/sys/phys-[{interface}]", "kind": "physical"}
    fex = re.fullmatch(r"topology/pod-(\d+)/paths-(\d+)/extpaths-(\d+)/pathep-\[(.+)\]", dn)
    if fex:
        return {"dn": dn, "label": f"Pod {fex[1]} / Node {fex[2]} / FEX {fex[3]} / {fex[4]}", "interface_dn": "", "kind": "fex"}
    bundle = re.fullmatch(r"topology/pod-(\d+)/(protpaths-\d+-\d+|paths-\d+)/pathep-\[(.+)\]", dn)
    if bundle:
        return {"dn": dn, "label": f"Pod {bundle[1]} / {bundle[2]} / {bundle[3]}",
                "interface_dn": "", "kind": "vpc" if bundle[2].startswith('protpaths') else "port-channel"}
    return {"dn": dn, "label": dn, "interface_dn": "", "kind": "other"}


def collect_endpoint_inventory(apic_get):
    objects = apic_get("/api/class/fvCEp.json", params={
        "rsp-subtree": "children", "rsp-subtree-class": "fvIp,fvRsCEpToPathEp",
    })
    rows = []
    seen = set()
    for item in objects:
        endpoint = item.get("fvCEp")
        if not endpoint:
            continue
        attr = endpoint.get("attributes", {})
        dn = attr.get("dn", "")
        if dn and dn in seen:
            continue
        if dn:
            seen.add(dn)
        context = re.match(r"^uni/tn-([^/]+)/ap-([^/]+)/epg-([^/]+)/cep-", dn)
        ips = {canonical_ip(attr.get("ip", ""))} - {""}
        paths = {attr.get("fabricPathDn", "")} - {""}
        for child in endpoint.get("children", []):
            if "fvIp" in child:
                ip_attr = child["fvIp"].get("attributes", {})
                address = canonical_ip(ip_attr.get("addr", ""))
                if address:
                    ips.add(address)
                if ip_attr.get("fabricPathDn"):
                    paths.add(ip_attr["fabricPathDn"])
            if "fvRsCEpToPathEp" in child:
                target = child["fvRsCEpToPathEp"].get("attributes", {}).get("tDn", "")
                if target:
                    paths.add(target)
        rows.append({
            "dn": dn, "mac": attr.get("mac", ""), "ips": sorted(ips),
            "tenant": context[1] if context else "", "application": context[2] if context else "",
            "epg": context[3] if context else "", "epg_dn": dn.rsplit('/cep-', 1)[0] if context else "",
            "encap": attr.get("encap", ""), "bd_dn": attr.get("bdDn", ""),
            "description": attr.get("contName") or attr.get("nameAlias") or attr.get("name", ""),
            "names": sorted({attr.get(k, '') for k in ('contName','nameAlias','name','descr')} - {''}),
            "paths": [path_information(path) for path in sorted(paths)],
        })
    return sorted(rows, key=lambda row: (row['tenant'], row['application'], row['epg'], row['mac'], row['dn']))


def filter_endpoints(rows, kind, value):
    if kind == 'name':
        return [row for row in rows if any(value.casefold() in name.casefold() for name in row.get('names', [row.get('description','')]))]
    if kind == 'mac':
        return [row for row in rows if re.sub(r"[:.\-]", "", row['mac']).upper() == value]
    return [row for row in rows if value in row['ips']]


def finite_rate(value):
    try:
        result = float(value)
        return result if math.isfinite(result) and result >= 0 else None
    except (ValueError, TypeError):
        return None


def exact_counter(value):
    # Preserve large APIC counters beyond JavaScript's safe-integer range.
    return str(value) if re.fullmatch(r"\d+", str(value)) else None


def normalize_sample(attributes):
    return {
        "available": bool(attributes), "interval_seconds": 300,
        "start": attributes.get("repIntvStart", ""), "end": attributes.get("repIntvEnd", ""),
        "bytes_per_second": finite_rate(attributes.get("bytesRateAvg")),
        "packets_per_second": finite_rate(attributes.get("pktsRateAvg")),
        "bytes_in_interval": exact_counter(attributes.get("bytesPer")),
        "packets_in_interval": exact_counter(attributes.get("pktsPer")),
        "bytes_cumulative": exact_counter(attributes.get("bytesCum")),
        "packets_cumulative": exact_counter(attributes.get("pktsCum")),
    }


def collect_interface_details(apic_get, warning, dn):
    if not PHYSICAL_DN.fullmatch(dn):
        raise ValueError("DN de interface física inválido.")
    url = '/api/node/mo/' + quote(dn, safe='/')
    objects = apic_get(url + '.json', params={"rsp-subtree": "children", "rsp-subtree-class": "ethpmPhysIf"})
    physical = next((item['l1PhysIf'] for item in objects if 'l1PhysIf' in item), None)
    if physical is None:
        raise NotFound("Interface não encontrada no APIC.")
    attr = physical.get('attributes', {})
    operational = next((child['ethpmPhysIf'].get('attributes', {}) for child in physical.get('children', []) if 'ethpmPhysIf' in child), {})
    if not operational:
        warning('Estado operacional indisponível para esta interface.')
    samples = {}
    for direction, family in (('ingress', 'Ingr'), ('egress', 'Egr')):
        kind = f'eqpt{family}Total5min'
        values = {}
        try:
            data = apic_get(url + f'/HDeqpt{family}Total5min-0.json')
            values = next((item[kind].get('attributes', {}) for item in data if kind in item), {})
        except Exception:
            warning(f'Falha ao consultar estatísticas de {"entrada" if direction == "ingress" else "saída"}.')
        else:
            if not values:
                warning(f'Amostra de cinco minutos de {"entrada" if direction == "ingress" else "saída"} indisponível; confira a coleta de estatísticas no APIC.')
        samples[direction] = normalize_sample(values)
    parts = re.fullmatch(r'topology/pod-(\d+)/node-(\d+)/sys/phys-\[(.+)\]', dn)
    return {"dn": dn, "pod": parts[1], "node": parts[2], "interface": parts[3],
            "description": attr.get('descr', ''), "admin_state": attr.get('adminSt', ''),
            "oper_state": operational.get('operSt', ''), "oper_reason": operational.get('operStQual', ''),
            "configured_speed": attr.get('speed', ''), "oper_speed": operational.get('operSpeed', ''),
            "mtu": attr.get('mtu', ''), "duplex": operational.get('operDuplex', ''),
            "last_link_change": operational.get('lastLinkStChg', ''), "statistics": samples}


def csv_cell(value):
    value = str(value or '')
    return "'" + value if value.lstrip().startswith(('=', '+', '-', '@')) else value


def register_diagnostics(app, apic_get, cached, json_route, warning, collect_ports=None):
    @cached()
    def endpoint_inventory():
        return collect_endpoint_inventory(apic_get)

    def lookup_query():
        if request.args.get('mode') == 'name':
            value = request.args.get('q','').strip()
            if not 2 <= len(value) <= 80 or any(ord(c)<32 for c in value):
                raise ValueError('Informe pelo menos 2 caracteres do nome disponível no APIC.')
            return 'name',value
        return normalize_lookup(request.args.get('q', ''))

    @cached()
    def server_ports():
        physical={x['l1PhysIf']['attributes']['dn']:x['l1PhysIf']['attributes'] for x in apic_get('/api/class/l1PhysIf.json') if 'l1PhysIf' in x}
        operational={x['ethpmPhysIf']['attributes']['dn'].removesuffix('/phys'):x['ethpmPhysIf']['attributes'] for x in apic_get('/api/class/ethpmPhysIf.json') if 'ethpmPhysIf' in x}
        return physical,operational

    @cached()
    def server_bundles():
        from aci_portchannels import collect_overview
        return collect_overview(apic_get,collect_ports,warning)

    def locate(kind,value):
        rows=copy.deepcopy(filter_endpoints(endpoint_inventory(),kind,value))
        if not rows:return rows
        try:
            physical,operational=server_ports()
        except Exception:
            physical,operational={},{}
            warning('Estado e velocidade das portas indisponíveis.')
        bundles={}
        if collect_ports and any(p['kind'] in ('vpc','port-channel') for r in rows for p in r['paths']):
            try:bundles={g['id']:g for g in server_bundles()}
            except Exception:warning('Associação dos membros PC/vPC indisponível.')
        for row in rows:
            row['match_type']=kind
            for path in row['paths']:
                members=[]
                if path['interface_dn']:members=[path['interface_dn']]
                else:
                    group=bundles.get(path['dn'])
                    path['mapping']='Não confirmada'
                    if group:
                        path['mapping']='Completa' if group['coverage']=='complete' else 'Parcial'
                        members=[m['dn'] for n in group['nodes'] if n['mapping']=='confirmed' for m in n['members']]
                path['ports']=[]
                for dn in sorted(set(members)):
                    a=physical.get(dn,{});op=operational.get(dn,{})
                    path['ports'].append({'dn':dn,'description':a.get('descr',''),
                        'admin_state':a.get('adminSt',''),'oper_state':op.get('operSt',''),
                        'configured_speed':a.get('speed',''),'oper_speed':op.get('operSpeed','')})
        return rows

    @app.get('/endpoint_lookup')
    def endpoint_lookup_page():
        return render_template('endpoint_lookup.html')

    @app.get('/api/endpoint_lookup')
    def endpoint_lookup_api():
        try:
            kind, value = lookup_query()
        except ValueError as error:
            return jsonify(error=str(error)), 400
        return json_route(lambda: locate(kind, value))

    @app.get('/export_csv/endpoint_lookup')
    def endpoint_lookup_csv():
        try:
            kind, value = lookup_query()
        except ValueError as error:
            return jsonify(error=str(error)), 400
        try:
            rows = filter_endpoints(endpoint_inventory(), kind, value)
        except Exception:
            app.logger.exception('Falha ao exportar localizador de endpoints')
            return jsonify(error='Falha ao consultar endpoints.'), 500
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(['MAC','IPs','Tenant','Application Profile','EPG','VLAN/Encap','Interfaces','Endpoint DN'])
        for row in rows:
            writer.writerow([csv_cell(value) for value in (row['mac'], '; '.join(row['ips']), row['tenant'],
                row['application'], row['epg'], row['encap'], '; '.join(path['dn'] for path in row['paths']), row['dn'])])
        return Response('\ufeff' + output.getvalue(), mimetype='text/csv; charset=utf-8', headers={
            'Content-Disposition': 'attachment; filename=endpoint_lookup.csv', 'Cache-Control': 'no-store'})

    @app.get('/interface_details')
    def interface_details_page():
        return render_template('interface_details.html')

    @cached(key_fn=lambda: 'interface_details:' + request.args['dn'])
    def interface_details():
        return collect_interface_details(apic_get, warning, request.args['dn'])

    @app.get('/api/interface_details')
    def interface_details_api():
        if not PHYSICAL_DN.fullmatch(request.args.get('dn', '')):
            return jsonify(error='Informe uma interface física válida: pod, node e eth1/1, por exemplo.'), 400
        return json_route(interface_details)
