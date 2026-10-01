# app.py - pacote completo de relatórios ACI
import os
import re
import time
import io
import csv
import logging
import json
from datetime import datetime, timezone
from urllib.parse import quote
import threading
import urllib3
from functools import wraps

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

from flask import redirect, Flask, render_template, jsonify, Response, request, g, has_request_context
import requests
from requests.exceptions import RequestException
from dotenv import load_dotenv
from werkzeug.exceptions import HTTPException
from aci_diagnostics import register_diagnostics, csv_cell
from aci_portchannels import register_portchannels
from aci_access import register_access
from aci_history import register_history
from aci_resources import register_resources
from aci_l3out import register_l3out

load_dotenv()

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
APIC_URL       = os.getenv("APIC_URL", "https://apic.exemplo.com.br")
APIC_USER      = os.getenv("APIC_USER")
APIC_PASS      = os.getenv("APIC_PASS")
APIC_VERIFY    = os.getenv("APIC_VERIFY", "False")
TOKEN_TTL      = int(os.getenv("APIC_TOKEN_TTL_SEC", "300"))
DATA_CACHE_TTL = int(os.getenv("DATA_CACHE_TTL_SEC", "60"))
APIC_PAGE_SIZE = int(os.getenv("APIC_PAGE_SIZE", "1000"))
APIC_MAX_RETRY = int(os.getenv("APIC_MAX_RETRY", "3"))
APIC_TIMEOUT   = int(os.getenv("APIC_TIMEOUT_SEC", "20"))

if not APIC_USER or not APIC_PASS:
    raise RuntimeError("APIC_USER e APIC_PASS devem estar definidos como variáveis de ambiente")

def parse_verify(value):
    value = str(value).strip()
    if value.lower() in ("true", "1", "yes"):
        return True
    if value.lower() in ("false", "0", "no", ""):
        return False
    return value  # Caminho para o arquivo de CA.


VERIFY = parse_verify(APIC_VERIFY)

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("aci-reports")

# ---------------------------------------------------------------------------
# Flask & requests session
# ---------------------------------------------------------------------------
app     = Flask(__name__)
session = requests.Session()
session.verify = VERIFY

# ---------------------------------------------------------------------------
# Token cache (thread-safe)
# ---------------------------------------------------------------------------
_token_lock  = threading.Lock()
_token_cache = {"token": None, "timestamp": 0}


def apic_login(force=False):
    now = time.time()
    with _token_lock:
        if not force and _token_cache["token"] and (now - _token_cache["timestamp"] < TOKEN_TTL):
            return _token_cache["token"]
        url     = f"{APIC_URL}/api/aaaLogin.json"
        payload = {"aaaUser": {"attributes": {"name": APIC_USER, "pwd": APIC_PASS}}}
        try:
            resp = session.post(url, json=payload,
                                headers={"Content-Type": "application/json"},
                                timeout=APIC_TIMEOUT)
            resp.raise_for_status()
        except RequestException:
            logger.exception("Erro ao autenticar no APIC")
            raise
        try:
            token = resp.json()["imdata"][0]["aaaLogin"]["attributes"]["token"]
        except Exception:
            raise RuntimeError("Resposta de login do APIC inesperada")
        _token_cache["token"]     = token
        _token_cache["timestamp"] = now
        logger.info("Token APIC renovado")
        return token


# ---------------------------------------------------------------------------
# APIC GET — paginação automática + retry exponencial
# ---------------------------------------------------------------------------
def apic_get(path, params=None):
    params   = dict(params or {})
    all_data = []
    page     = 0
    while True:
        paged_params = {**params, "page": page, "page-size": APIC_PAGE_SIZE}
        data = _apic_get_page(path, paged_params)
        all_data.extend(data)
        if len(data) < APIC_PAGE_SIZE:
            break
        page += 1
    return all_data


def _apic_get_page(path, params):
    token   = apic_login()
    url     = f"{APIC_URL}{path}"
    attempt = 0
    while True:
        headers = {"Cookie": f"APIC-cookie={token}"}
        try:
            resp = session.get(url, headers=headers, params=params, timeout=APIC_TIMEOUT)
            if resp.status_code == 401:
                logger.warning("Token expirado — renovando")
                token = apic_login(force=True)
                headers = {"Cookie": f"APIC-cookie={token}"}
                resp = session.get(url, headers=headers, params=params, timeout=APIC_TIMEOUT)
            resp.raise_for_status()
            data = resp.json().get("imdata", [])
            for item in data:
                if "error" in item:
                    error = item["error"].get("attributes", {})
                    raise RuntimeError(f"APIC retornou erro {error.get('code', '')}: {error.get('text', '')}")
            return data
        except RequestException as exc:
            attempt += 1
            if attempt >= APIC_MAX_RETRY:
                logger.exception("Falha após %d tentativas em %s", APIC_MAX_RETRY, path)
                raise
            wait = 2 ** attempt
            logger.warning("Tentativa %d/%d falhou (%s). Aguardando %ds…",
                           attempt, APIC_MAX_RETRY, exc, wait)
            time.sleep(wait)


# ---------------------------------------------------------------------------
# Cache de dados (thread-safe, TTL configurável)
# ---------------------------------------------------------------------------
_data_cache: dict = {}
_cache_lock        = threading.Lock()


def collection_warning(message):
    logger.warning(message)
    if has_request_context():
        g.collection_warnings = getattr(g, "collection_warnings", []) + [message]


def cached(key_fn=None):
    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            key = key_fn() if key_fn else fn.__name__
            refresh = has_request_context() and request.args.get("refresh") == "1"
            now = time.time()
            with _cache_lock:
                entry = _data_cache.get(key)
                if not refresh and entry and now - entry["ts"] < DATA_CACHE_TTL:
                    if has_request_context():
                        g.collection_warnings = getattr(g, "collection_warnings", []) + entry["warnings"]
                        g.report_meta = {"ts": entry["ts"], "cached": True}
                    return entry["data"]
            before = len(getattr(g, "collection_warnings", [])) if has_request_context() else 0
            result = fn(*args, **kwargs)
            warnings = getattr(g, "collection_warnings", [])[before:] if has_request_context() else []
            stamp = time.time()
            if has_request_context() and getattr(g, "report_meta", {}).get("cached"):
                stamp = min(stamp, g.report_meta["ts"])
            with _cache_lock:
                _data_cache[key] = {"data": result, "ts": stamp, "warnings": warnings}
            if has_request_context():
                g.report_meta = {"ts": stamp, "cached": False}
            return result
        return wrapper
    return decorator


@app.route("/api/cache/clear", methods=["POST"])
def clear_cache():
    with _cache_lock:
        _data_cache.clear()
    return jsonify({"status": "ok", "message": "Cache limpo"})


# ---------------------------------------------------------------------------
# Shared utilities
# ---------------------------------------------------------------------------
def extract_tenant_l3out_instp_from_dn(dn):
    mTenant = re.search(r"(?:^|/)tn-([^/]+)", dn)
    mL3out  = re.search(r"(?:^|/)out-([^/]+)", dn)
    mInstp  = re.search(r"(?:^|/)instP-([^/]+)", dn)
    return (
        mTenant.group(1) if mTenant else "",
        mL3out.group(1)  if mL3out  else "",
        mInstp.group(1)  if mInstp  else "",
    )


# ---------------------------------------------------------------------------
# CSV export genérico
# ---------------------------------------------------------------------------
CSV_REGISTRY = {}


def register_csv(route_name, fn_data, fields, filename):
    CSV_REGISTRY[route_name] = {"fn": fn_data, "fields": fields, "filename": filename}


def _make_csv_response(route_name):
    cfg = CSV_REGISTRY.get(route_name)
    if not cfg:
        return Response("Relatório não encontrado", status=404)
    try:
        data    = cfg["fn"]()
        headers = [f[0] for f in cfg["fields"]]
        keys    = [f[1] for f in cfg["fields"]]
        si = io.StringIO()
        cw = csv.writer(si)
        cw.writerow(headers)
        for row in data:
            cw.writerow([
                csv_cell("; ".join(v) if isinstance(v := row.get(k, ""), list) else v)
                for k in keys
            ])
        return Response(
            si.getvalue(),
            mimetype="text/csv",
            headers={"Content-Disposition": f"attachment; filename={cfg['filename']}"},
        )
    except Exception as e:
        logger.exception("Erro ao gerar CSV: %s", route_name)
        return Response(f"Erro ao gerar CSV: {e}", status=500)


@app.route("/export_csv/<report_name>")
def export_csv(report_name):
    return _make_csv_response(report_name)


# ---------------------------------------------------------------------------
# JSON route helper
# ---------------------------------------------------------------------------
def _json_route(fn):
    try:
        data = fn()
        meta = getattr(g, "report_meta", {"ts": time.time(), "cached": False})
        response = jsonify(data)
        response.headers["X-Collected-At"] = datetime.fromtimestamp(meta["ts"], timezone.utc).isoformat()
        response.headers["X-Data-Cache"] = "hit" if meta["cached"] else "miss"
        warnings = getattr(g, "collection_warnings", [])
        summary = [message[:200] for message in warnings[:5]]
        if len(warnings) > 5:
            summary.append(f"Mais {len(warnings) - 5} falhas; consulte o log do servidor.")
        response.headers["X-Collection-Warnings"] = json.dumps(summary, ensure_ascii=True)
        response.headers["Cache-Control"] = "no-store"
        return response
    except HTTPException as error:
        return jsonify({"error": error.description}), error.code
    except Exception as e:
        logger.exception("Erro na API")
        return jsonify({"error": str(e)}), 500


# ===========================================================================
# FUNÇÕES DE COLETA DE DADOS
# ===========================================================================

def physical_dn(dn):
    return dn[:-5] if dn.endswith("/phys") else dn


def interface_oper_map():
    return {
        physical_dn(item["ethpmPhysIf"]["attributes"]["dn"]): item["ethpmPhysIf"]["attributes"]
        for item in apic_get("/api/class/ethpmPhysIf.json") if "ethpmPhysIf" in item
    }


# --- Interfaces ---

@cached()
def get_interfaces_down():
    imdata = apic_get("/api/node/class/ethpmPhysIf.json",
                      params={"query-target-filter": 'eq(ethpmPhysIf.operSt,"down")'})
    rows = []
    for item in imdata:
        attr = item.get("ethpmPhysIf", {}).get("attributes", {})
        rows.append({
            "access_vlan":     attr.get("accessVlan", ""),
            "backplane_mac":   attr.get("backplaneMac", ""),
            "cfg_access_vlan": attr.get("cfgAccessVlan", ""),
            "dn":              attr.get("dn", ""),
            "oper_st":         attr.get("operSt", ""),
        })
    return rows


@cached()
def get_interfaces_up():
    operations = interface_oper_map()
    imdata = apic_get("/api/class/l1PhysIf.json",
                      params={"query-target-filter": 'eq(l1PhysIf.adminSt,"up")'})
    rows = []
    for item in imdata:
        attr = item.get("l1PhysIf", {}).get("attributes", {})
        op = operations.get(attr.get("dn", ""), {})
        if op.get("operSt") != "up":
            continue
        rows.append({
            "admin_st":    attr.get("adminSt", ""),
            "auto_neg":    attr.get("autoNeg", ""),
            "breakout_map":attr.get("breakT", ""),
            "bandwidth":   attr.get("bw", ""),
            "descr":       attr.get("descr", ""),
            "delay":       attr.get("delay", ""),
            "dn":          attr.get("dn", ""),
            "mtu":         attr.get("mtu", ""),
            "speed":       op.get("operSpeed") or attr.get("speed", ""),
            "status":      op.get("operSt", "unknown"),
            "switching_st":attr.get("switchingSt", ""),
        })
    return rows


@cached()
def get_interfaces_up_full():
    operations = interface_oper_map()
    imdata = apic_get("/api/class/l1PhysIf.json")
    rows = []
    for item in imdata:
        attr = item.get("l1PhysIf", {}).get("attributes", {})
        rows.append({
            "adminSt":    attr.get("adminSt"),
            "autoNeg":    attr.get("autoNeg"),
            "breakT":     attr.get("breakT"),
            "bw":         attr.get("bw"),
            "descr":      attr.get("descr"),
            "delay":      attr.get("delay"),
            "dn":         attr.get("dn"),
            "mtu":        attr.get("mtu"),
            "speed":      operations.get(attr.get("dn", ""), {}).get("operSpeed") or attr.get("speed"),
            "status":     operations.get(attr.get("dn", ""), {}).get("operSt", "unknown"),
            "switchingSt":attr.get("switchingSt"),
        })
    return rows


@cached()
def get_portchannels():
    imdata = apic_get(
        "/api/node/class/pcAggrIf.json",
        params={"rsp-subtree": "full", "rsp-subtree-class": "pcRsMbrIfs"},
    )
    rows = []
    for item in imdata:
        a        = item.get("pcAggrIf", {}).get("attributes", {})
        children = item.get("pcAggrIf", {}).get("children", [])
        members  = [
            c["pcRsMbrIfs"]["attributes"].get("tDn") or c["pcRsMbrIfs"]["attributes"].get("tSKey", "")
            for c in children if "pcRsMbrIfs" in c
        ]
        rows.append({
            "name":        a.get("name", ""),
            "dn":          a.get("dn", ""),
            "pod":         (re.search(r"pod-(\d+)", a.get("dn", "")) or [None, ""])[1],
            "node":        (re.search(r"node-(\d+)", a.get("dn", "")) or [None, ""])[1],
            "mode":        a.get("mode", ""),
            "pcMode":      a.get("pcMode", ""),
            "status":      a.get("switchingSt", ""),
            "portChannel": a.get("id", ""),
            "speed":       a.get("speed", ""),
            "members":     members,
        })
    grouped = {}
    for index, r in enumerate(rows):
        k = r["dn"] or ("unknown", index)
        if k not in grouped:
            grouped[k] = {**r, "members": []}
        grouped[k]["members"] += r["members"]

    def _fmt_member(tdn):
        m = re.search(r"pod-(\d+)/node-(\d+).*phys-\[(.+?)\]", tdn)
        return f"pod-{m.group(1)} / node-{m.group(2)} / {m.group(3)}" if m else tdn

    results = []
    for g in grouped.values():
        unique_members = sorted(set(g["members"]))
        results.append({**g, "members": [_fmt_member(x) for x in unique_members]})
    results.sort(key=lambda x: x["name"])
    return results


@cached()
def get_acc_ports():
    accs = apic_get("/api/class/infraAccPortGrp.json",
                    params={"order-by": "infraAccPortGrp.name|asc", "rsp-subtree": "children"})
    groups = {}
    all_ports = []
    for item in accs:
        group = item.get('infraAccPortGrp')
        if not group:
            continue
        attr = group.get('attributes', {})
        name = attr.get('name', '')
        dn = attr.get('dn') or f'uni/infra/funcprof/accportgrp-{name}'
        policies, selectors, aeps = [], [], []
        for child in group.get('children', []):
            for kind, obj in child.items():
                rel = obj.get('attributes', {})
                target = rel.get('tDn', '')
                if kind == 'infraRtAccBaseGrp':
                    if target: selectors.append(target)
                elif kind == 'infraRsAttEntP':
                    if target: aeps.append(target)
                elif kind.startswith('infraRs'):
                    value = target or next((str(v) for k, v in rel.items() if k.startswith('tn') and k.endswith('Name') and v), '')
                    if value:
                        policies.append(f"{kind}: {value} ({rel.get('state', 'indisponível')})")
        groups[name] = dict(group_descr=attr.get('descr', ''), policy_group_dn=dn,
                            aep='; '.join(sorted(set(aeps))) or 'Não informado',
                            policies='; '.join(sorted(set(policies))) or 'Não informadas',
                            selectors='; '.join(sorted(set(selectors))) or 'Não informados')
        ports = []
        try:
            _collect_acc_ports(dn, ports)
        except Exception:
            logger.exception('Falha ao coletar portas do grupo %s', name)
            collection_warning(f'Coleta incompleta: não foi possível consultar o grupo {name}.')
        for port in ports:
            port['acc'] = name
        all_ports.extend(ports or [dict(acc=name, dn='', pod='', node='', iface='')])

    l1_map = {
        x["l1PhysIf"]["attributes"]["dn"]: x["l1PhysIf"]["attributes"]
        for x in apic_get('/api/class/l1PhysIf.json',
                          params={"query-target-filter": 'eq(l1PhysIf.portT,"leaf")'})
    }
    ethpm_map = {
        physical_dn(x["ethpmPhysIf"]["attributes"]["dn"]):
        x["ethpmPhysIf"]["attributes"]
        for x in apic_get('/api/class/ethpmPhysIf.json',
                          params={"query-target-filter": 'eq(ethpmPhysIf.intfT,"phy")'})
    }
    rows, seen = [], set()
    for p in all_ports:
        key = (p['acc'], p['dn'])
        if key in seen:
            continue
        seen.add(key)
        l1a = l1_map.get(p["dn"], {})
        op  = ethpm_map.get(p["dn"], {})
        rows.append({
            **groups[p['acc']],
            "descr":  l1a.get("descr") or groups[p['acc']]['group_descr'],
            "status": op.get("operSt", "-"),
            "acc":    p["acc"],
            "path":   f"pod-{p['pod']} / node-{p['node']} / {p['iface']}" if p['dn'] else 'Interface não informada pelo deployment', 
            "speed":  op.get("operSpeed") or l1a.get("speed") or "-",
        })
    rows.sort(key=lambda x: (x["acc"], x["path"]))
    return rows


def _collect_acc_ports(acc, all_ports):
    """Resolve access/bundle policy groups using their full deployment tree."""
    group_dn = acc if acc.startswith("uni/") else f"uni/infra/funcprof/accportgrp-{acc}"
    group_name = group_dn.rsplit("/", 1)[-1].split("-", 1)[-1]
    deployment = apic_get(
        f"/api/node/mo/{quote(group_dn, safe='/')}.json",
        params={"rsp-subtree-include": "full-deployment", "target-path": "AccBaseGrpToEthIf"},
    )
    if not deployment:
        raise RuntimeError(f"Grupo não encontrado: {group_dn}")
    seen = set()

    def walk(objects):
        for item in objects:
            for kind, obj in item.items():
                if not isinstance(obj, dict):
                    continue
                if kind == "pconsResourceCtx":
                    dn = physical_dn(obj.get("attributes", {}).get("ctxDn", ""))
                    match = re.search(r"pod-(\d+)/node-(\d+)/.*phys-\[(.+?)\]$", dn)
                    if match and dn not in seen:
                        seen.add(dn)
                        all_ports.append({"acc": group_name, "pod": match[1], "node": match[2],
                                          "iface": match[3], "dn": dn, "policy_group_dn": group_dn})
                walk(obj.get("children", []))

    walk(deployment)


# --- Endpoints ---

@cached()
def get_endpoints():
    imdata = apic_get("/api/node/class/uni/fvCEp.json")
    rows = []
    for item in imdata:
        attr = item.get("fvCEp", {}).get("attributes", {})
        rows.append({
            "fabricPathDn": attr.get("fabricPathDn", ""),
            "bdDn":         attr.get("bdDn", ""),
            "mac":          attr.get("mac", ""),
            "contName":     attr.get("contName", ""),
        })
    return rows


@cached()
def get_vmware_vms():
    imdata = apic_get("/api/class/compVm.json", params={"order-by": "compVm.name|asc"})
    rows = []
    for item in imdata:
        attr = item.get("compVm", {}).get("attributes", {})
        rows.append({
            "name":  attr.get("name", ""),
            "os":    attr.get("os", "") or attr.get("cfgdOs", ""),
            "state": attr.get("state", ""),
            "dn":    attr.get("dn", ""),
        })
    return rows


@cached()
def get_ip_endpoints():
    imdata = apic_get(
        "/api/class/fvCEp.json",
        params={"rsp-subtree": "children", "rsp-subtree-class": "fvIp"},
    )
    rows = []
    seen = set()
    for item in imdata:
        cep_attr  = item.get("fvCEp", {}).get("attributes", {})
        children  = item.get("fvCEp", {}).get("children", [])
        mac       = cep_attr.get("mac", "")
        fabric_dn = cep_attr.get("fabricPathDn", "")
        bd_dn     = cep_attr.get("bdDn", "")
        cont_name = cep_attr.get("contName", "")
        for child in children:
            ip_attr = child.get("fvIp", {}).get("attributes", {})
            ip = ip_attr.get("addr", "")
            if not ip or ip == "0.0.0.0":
                continue
            key = (cep_attr.get("dn", ""), bd_dn, fabric_dn, mac, ip)
            if key in seen:
                continue
            seen.add(key)
            rows.append({
                "ip":          ip,
                "mac":         mac,
                "fabric_path": fabric_dn,
                "bd":          bd_dn,
                "description": cont_name,
                "endpoint_dn": cep_attr.get("dn", ""),
                "tenant": extract_tenant_l3out_instp_from_dn(cep_attr.get("dn", ""))[0],
            })
    rows.sort(key=lambda x: x["ip"])
    return rows


# --- L3Out helpers ---

@cached()
def get_l3out_raw():
    return apic_get("/api/class/l3extSubnet.json")






# --- L3Out functions ---

@cached()
def get_l3out_subnets():
    imdata = get_l3out_raw()
    rows, seen = [], set()
    for item in imdata:
        attr   = item.get("l3extSubnet", {}).get("attributes", {})
        dn     = attr.get("dn", "")
        tenant, l3out, instp = extract_tenant_l3out_instp_from_dn(dn)
        key = f"{tenant}|{l3out}|{instp}|{attr.get('ip','')}|{attr.get('scope','')}"
        if key in seen:
            continue
        seen.add(key)
        rows.append({
            "tenant": tenant, "l3out": l3out, "instp": instp,
            "ip": attr.get("ip", ""), "scope": attr.get("scope", ""),
        })
    rows.sort(key=lambda x: (x["tenant"], x["l3out"], x["instp"], x["ip"]))
    return rows

# --- Políticas & Fabric ---

@cached()
def get_vrfs():
    imdata = apic_get("/api/class/fvCtx.json")
    rows, seen = [], set()
    for item in imdata:
        attr   = item.get("fvCtx", {}).get("attributes", {})
        dn     = attr.get("dn", "")
        tenant, _, _ = extract_tenant_l3out_instp_from_dn(dn)
        name   = attr.get("name", "")
        key    = f"{tenant}|{name}"
        if key in seen:
            continue
        seen.add(key)
        rows.append({
            "tenant":          tenant,
            "name":            name,
            "policy_enforced": attr.get("pcEnfDir", ""),
            "descr":           attr.get("descr", ""),
            "dn":              dn,
        })
    rows.sort(key=lambda x: (x["tenant"], x["name"]))
    return rows


@cached()
def get_contracts():
    imdata = apic_get("/api/class/vzBrCP.json")
    rows = []
    for item in imdata:
        attr   = item.get("vzBrCP", {}).get("attributes", {})
        dn     = attr.get("dn", "")
        tenant, _, _ = extract_tenant_l3out_instp_from_dn(dn)
        rows.append({
            "tenant":   tenant,
            "name":     attr.get("name", ""),
            "scope":    attr.get("scope", ""),
            "priority": attr.get("prio", ""),
            "descr":    attr.get("descr", ""),
            "dn":       dn,
        })
    rows.sort(key=lambda x: (x["tenant"], x["name"]))
    return rows


@cached()
def get_epgs():
    imdata = apic_get("/api/class/fvAEPg.json")
    rows, seen = [], set()
    for item in imdata:
        attr   = item.get("fvAEPg", {}).get("attributes", {})
        dn     = attr.get("dn", "")
        tenant, _, _ = extract_tenant_l3out_instp_from_dn(dn)
        m_app  = re.search(r"ap-([^/]+)", dn)
        app    = m_app.group(1) if m_app else ""
        key    = f"{tenant}|{app}|{attr.get('name','')}"
        if key in seen:
            continue
        seen.add(key)
        rows.append({
            "tenant": tenant,
            "app":    app,
            "name":   attr.get("name", ""),
            "pc_enf": attr.get("pcEnfPref", ""),
            "descr":  attr.get("descr", ""),
            "dn":     dn,
        })
    rows.sort(key=lambda x: (x["tenant"], x["app"], x["name"]))
    return rows


@cached()
def get_bds():
    imdata = apic_get("/api/class/fvBD.json", params={
        "rsp-subtree": "children", "rsp-subtree-class": "fvSubnet"})
    rows = []
    for item in imdata:
        attr   = item.get("fvBD", {}).get("attributes", {})
        dn     = attr.get("dn", "")
        tenant, _, _ = extract_tenant_l3out_instp_from_dn(dn)
        rows.append({
            "tenant":        tenant,
            "name":          attr.get("name", ""),
            "subnets":       sorted({child["fvSubnet"]["attributes"]["ip"]
                                     for child in item.get("fvBD", {}).get("children", [])
                                     if child.get("fvSubnet", {}).get("attributes", {}).get("ip")}),
            "arp_flood":     attr.get("arpFlood", ""),
            "unicast_route": attr.get("unicastRoute", ""),
            "descr":         attr.get("descr", ""),
            "dn":            dn,
        })
    rows.sort(key=lambda x: (x["tenant"], x["name"]))
    return rows


# --- AEP ---
@cached()
def get_aep_interfaces():
    import re

    # 1) Todos os AEPs
    aeps_raw = apic_get("/api/class/infraAttEntityP.json")
    aep_names = [
        x["infraAttEntityP"]["attributes"]["name"]
        for x in aeps_raw if "infraAttEntityP" in x
    ]

    # 2) Para cada AEP, descobrir quais policy groups estão vinculados
    rs_data = apic_get("/api/class/infraRsAttEntP.json")

    aep_to_pgs: dict[str, set] = {name: set() for name in aep_names}
    for item in rs_data:
        attr   = item.get("infraRsAttEntP", {}).get("attributes", {})
        tdn    = attr.get("tDn", "")
        src_dn = attr.get("dn", "")
        m = re.search(r"attentp-(.+)$", tdn)
        if not m:
            continue
        aep_name = m.group(1)
        if aep_name in aep_to_pgs:
            pg_m = re.search(r"(?:accportgrp|accbundle)-(.+?)(?:/|$)", src_dn)
            if pg_m:
                aep_to_pgs[aep_name].add(src_dn.rsplit("/", 1)[0])

    # 3) Para cada policy group, resolver interfaces físicas via full-deployment
    pg_to_ports: dict[str, list] = {}
    all_pgs = {pg for pgs in aep_to_pgs.values() for pg in pgs}

    for pg in all_pgs:
        ports = []
        try:
            _collect_acc_ports(pg, ports)
        except Exception:
            logger.exception("AEP: falha ao resolver interfaces do PG %s", pg)
            collection_warning(f"Coleta incompleta: não foi possível resolver as interfaces de {pg}.")
        pg_to_ports[pg] = ports

    # 4) Enriquecer com descrição e status operacional
    l1_map = {
        x["l1PhysIf"]["attributes"]["dn"]: x["l1PhysIf"]["attributes"]
        for x in apic_get('/api/class/l1PhysIf.json',
                          params={"query-target-filter": 'eq(l1PhysIf.portT,"leaf")'})
    }
    ethpm_map = {
        physical_dn(x["ethpmPhysIf"]["attributes"]["dn"]):
        x["ethpmPhysIf"]["attributes"]
        for x in apic_get('/api/class/ethpmPhysIf.json',
                          params={"query-target-filter": 'eq(ethpmPhysIf.intfT,"phy")'})
    }

    # 5) Montar linhas flat: uma por AEP + interface
    rows = []
    seen = set()

    for aep_name, pgs in sorted(aep_to_pgs.items()):
        if not pgs:
            rows.append({
                "aep":         aep_name,
                "policy_group": "",
                "pod":         "",
                "node":        "",
                "interface":   "",
                "path":        "",
                "status":      "",
                "speed":       "",
                "descr":       "",
            })
            continue

        for pg in sorted(pgs):
            ports = pg_to_ports.get(pg, [])
            if not ports:
                rows.append({
                    "aep":          aep_name,
                    "policy_group": pg.rsplit("/", 1)[-1].split("-", 1)[-1],
                    "policy_group_dn": pg,
                    "pod":          "",
                    "node":         "",
                    "interface":    "",
                    "path":         "",
                    "status":       "",
                    "speed":        "",
                    "descr":        "",
                })
                continue

            for p in ports:
                key = (aep_name, pg, p["dn"])
                if key in seen:
                    continue
                seen.add(key)

                l1a = l1_map.get(p["dn"], {})
                op  = ethpm_map.get(p["dn"], {})

                rows.append({
                    "aep":          aep_name,
                    "policy_group": pg.rsplit("/", 1)[-1].split("-", 1)[-1],
                    "policy_group_dn": pg,
                    "pod":          p.get("pod", ""),
                    "node":         p.get("node", ""),
                    "interface":    p.get("iface", ""),
                    "path":         f"pod-{p['pod']} / node-{p['node']} / {p['iface']}",
                    "status":       op.get("operSt", ""),
                    "speed":        op.get("operSpeed") or l1a.get("speed") or "",
                    "descr":        l1a.get("descr", ""),
                })

    return rows


# --- Operacional ---

@cached()
def get_faults():
    SEV_ORDER = {"critical": 0, "major": 1, "minor": 2, "warning": 3, "info": 4, "cleared": 5}
    imdata = apic_get("/api/class/faultInst.json",
                      params={"order-by": "faultInst.severity|asc"})
    rows = []
    for item in imdata:
        attr = item.get("faultInst", {}).get("attributes", {})
        rows.append({
            "severity":        attr.get("severity", ""),
            "code":            attr.get("code", ""),
            "cause":           attr.get("cause", ""),
            "description":     attr.get("descr", ""),
            "dn":              attr.get("dn", ""),
            "created":         attr.get("created", ""),
            "last_transition": attr.get("lastTransition", ""),
            "affected": attr.get("affected", ""),
            "type":            attr.get("type", ""),
            "subject":         attr.get("subject", ""),
        })
    rows.sort(key=lambda x: (SEV_ORDER.get(x["severity"].lower(), 9), x["created"]))
    return rows


@cached()
def get_fabric_nodes():
    imdata = apic_get("/api/class/fabricNode.json")
    rows = []
    for item in imdata:
        attr = item.get("fabricNode", {}).get("attributes", {})
        role = attr.get("role", "")
        if role not in ("leaf", "spine"):
            continue
        rows.append({
            "name":    attr.get("name", ""),
            "node_id": attr.get("id", ""),
            "role":    role,
            "model":   attr.get("model", ""),
            "serial":  attr.get("serial", ""),
            "version": attr.get("fabricSt", ""),
            "address": attr.get("address", ""),
            "dn":      attr.get("dn", ""),
        })
    fw_data = apic_get("/api/class/firmwareRunning.json")
    fw_map = {}
    for item in fw_data:
        attr = item.get("firmwareRunning", {}).get("attributes", {})
        dn   = attr.get("dn", "")
        m = re.search(r"node-(\d+)", dn)
        if m:
            fw_map[m.group(1)] = attr.get("version", "")
    for r in rows:
        r["firmware"] = fw_map.get(r["node_id"], "—")
    rows.sort(key=lambda x: (x["role"], int(x["node_id"]) if x["node_id"].isdigit() else 0))
    return rows


# ===========================================================================
# REGISTRO CSV
# ===========================================================================

register_csv("down", get_interfaces_down, [
    ("Access VLAN","access_vlan"),("Backplane MAC","backplane_mac"),
    ("Cfg Access VLAN","cfg_access_vlan"),("DN","dn"),("Oper Status","oper_st"),
], "interfaces_down.csv")

register_csv("up", get_interfaces_up, [
    ("Admin","admin_st"),("AutoNeg","auto_neg"),("Breakout","breakout_map"),
    ("Bandwidth","bandwidth"),("Description","descr"),("Delay","delay"),
    ("DN","dn"),("MTU","mtu"),("Speed","speed"),("Oper Status","status"),("Switching","switching_st"),
], "interfaces_up.csv")

register_csv("interfaces_up_full", get_interfaces_up_full, [
    ("Admin","adminSt"),("AutoNeg","autoNeg"),("Breakout","breakT"),
    ("Bandwidth","bw"),("Description","descr"),("Delay","delay"),
    ("DN","dn"),("MTU","mtu"),("Speed","speed"),("Oper Status","status"),("Switching","switchingSt"),
], "interfaces_up_full.csv")

register_csv("portchannels", get_portchannels, [
    ("Name","name"),("Pod","pod"),("Node","node"),("DN","dn"),("Mode","mode"),("Protocol","pcMode"),
    ("Status","status"),("PortChannel","portChannel"),("Speed","speed"),("Members","members"),
], "portchannels.csv")

register_csv("aep_interfaces", get_aep_interfaces, [
    ("AEP",           "aep"),
    ("Policy Group",  "policy_group"),
    ("Path",          "path"),
    ("Status",        "status"),
    ("Speed",         "speed"),
    ("Description",   "descr"),
], "aep_interfaces.csv")

register_csv("acc_ports", get_acc_ports, [
    ("Description","descr"),("Status","status"),
    ("Policy Group","acc"),("Path","path"),("Speed","speed"),
    ("AEP","aep"),("Policies","policies"),("Selectors","selectors"),("Group DN","policy_group_dn"),
], "acc_ports.csv")

register_csv("endpoints", get_endpoints, [
    ("Localização","fabricPathDn"),("BD/TN","bdDn"),("MAC","mac"),("Descrição","contName"),
], "endpoints.csv")

register_csv("vmware", get_vmware_vms, [
    ("Name","name"),("OS","os"),("State","state"),("DN","dn"),
], "vmware.csv")

register_csv("ip_endpoints", get_ip_endpoints, [
    ("IP","ip"),("MAC","mac"),("Tenant","tenant"),("Endpoint DN","endpoint_dn"),("Fabric Path","fabric_path"),("BD","bd"),("Description","description"),
], "ip_endpoints.csv")

register_csv("l3out_subnets", get_l3out_subnets, [
    ("Tenant","tenant"),("L3Out","l3out"),("InstP","instp"),("Subnet","ip"),("Scope","scope"),
], "l3out_subnets.csv")


register_csv("vrfs", get_vrfs, [
    ("Tenant","tenant"),("VRF","name"),("PolicyEnforced","policy_enforced"),("Descrição","descr"),("DN","dn"),
], "vrfs.csv")
register_csv("contracts", get_contracts, [
    ("Tenant","tenant"),("Contract","name"),("Scope","scope"),("Prioridade","priority"),("Descrição","descr"),("DN","dn"),
], "contracts.csv")
register_csv("epgs", get_epgs, [
    ("Tenant","tenant"),("APP","app"),("EPG","name"),("PolicyEnf","pc_enf"),("Descrição","descr"),("DN","dn"),
], "epgs.csv")
register_csv("bds", get_bds, [
    ("Tenant","tenant"),("BD","name"),("Subnets","subnets"),("ARP Flood","arp_flood"),("UnicastRoute","unicast_route"),("Descrição","descr"),("DN","dn"),
], "bds.csv")

register_csv("faults", get_faults, [
    ("Severity","severity"),("Code","code"),("Cause","cause"),("Description","description"),
    ("Subject","subject"),("Created","created"),("Last Transition","last_transition"),("DN","dn"),
], "faults.csv")
register_csv("fabric_nodes", get_fabric_nodes, [
    ("Name","name"),("Node ID","node_id"),("Role","role"),("Model","model"),
    ("Serial","serial"),("Firmware","firmware"),("Address","address"),("DN","dn"),
], "fabric_nodes.csv")


# ===========================================================================
# ROTAS — Páginas HTML
# ===========================================================================

@app.route("/")
def home():
    return render_template("home.html")

@app.route("/down")
def report_down():
    return render_template("report_down.html")

@app.route("/up")
def report_up():
    return render_template("report_up.html")

@app.route("/interfaces/up_full")
def report_interfaces_up_full():
    return render_template("report_interfaces_up_full.html")

@app.route("/portchannels")
def report_portchannels():
    return render_template("portchannel_overview.html")

@app.route("/acc_ports")
def report_acc_ports():
    return render_template("report_acc_ports.html")

@app.route("/aep_interfaces")
def report_aep_interfaces():
    return render_template("report_aep_interfaces.html")

@app.route("/endpoints")
def report_endpoints():
    return render_template("report_endpoints.html")

@app.route("/vmware")
def report_vmware():
    return render_template("report_vmware.html")

@app.route("/ip_endpoints")
def report_ip_endpoints():
    return render_template("report_ip_endpoints.html")

@app.route("/l3out")
def report_l3out():
    return redirect("/l3out_explorer", code=302)












@app.route("/vrfs")
def report_vrfs():
    return render_template("report_vrfs.html")

@app.route("/contracts")
def report_contracts():
    return render_template("report_contracts.html")

@app.route("/epgs")
def report_epgs():
    return render_template("report_epgs.html")

@app.route("/bds")
def report_bds():
    return render_template("report_bds.html")

@app.route("/faults")
def report_faults():
    return render_template("report_faults.html")

@app.route("/fabric_nodes")
def report_fabric_nodes():
    return render_template("report_fabric_nodes.html")


# ===========================================================================
# ROTAS — APIs JSON
# ===========================================================================

@app.route("/api/interfaces/down")
def api_down():
    return _json_route(get_interfaces_down)

@app.route("/api/interfaces/up")
def api_up():
    return _json_route(get_interfaces_up)

@app.route("/api/interfaces/up_full")
def api_interfaces_up_full():
    return _json_route(get_interfaces_up_full)

@app.route("/api/portchannels")
def api_portchannels():
    return _json_route(get_portchannels)

@app.route("/api/acc_ports")
def api_acc_ports():
    return _json_route(get_acc_ports)

@app.route("/api/aep_interfaces")
def api_aep_interfaces():
    return _json_route(get_aep_interfaces)

@app.route("/api/endpoints")
def api_endpoints():
    return _json_route(get_endpoints)

@app.route("/api/vmware")
def api_vmware():
    return _json_route(get_vmware_vms)

@app.route("/api/ip_endpoints")
def api_ip_endpoints():
    return _json_route(get_ip_endpoints)

@app.route("/api/l3out_subnets")
def api_l3out_subnets():
    return _json_route(get_l3out_subnets)












@app.route("/api/vrfs")
def api_vrfs():
    return _json_route(get_vrfs)

@app.route("/api/contracts")
def api_contracts():
    return _json_route(get_contracts)

@app.route("/api/epgs")
def api_epgs():
    return _json_route(get_epgs)

@app.route("/api/bds")
def api_bds():
    return _json_route(get_bds)

@app.get('/api/object_faults')
def object_faults():
    from aci_access import GROUP
    from aci_diagnostics import PHYSICAL_DN
    dn = request.args.get('dn', '')
    if not (GROUP.fullmatch(dn) or PHYSICAL_DN.fullmatch(dn)):
        return jsonify(error='DN de interface ou Leaf Access Port inválido.'), 400
    def collect():
        return [row for row in get_faults() if fault_matches(row, dn)]
    return _json_route(collect)


def fault_matches(row, dn):
    affected = row.get('affected', '')
    fault_dn = row.get('dn', '')
    return affected == dn or affected.startswith(dn + '/') or fault_dn.startswith(dn + '/')


@app.route("/api/faults")
def api_faults():
    return _json_route(get_faults)

@app.route("/api/fabric_nodes")
def api_fabric_nodes():
    return _json_route(get_fabric_nodes)


# ===========================================================================
# Endpoint lookup and physical-interface diagnostics (read-only).
register_diagnostics(app, lambda *args, **kwargs: apic_get(*args, **kwargs), cached, _json_route, collection_warning,
                     lambda *args, **kwargs: _collect_acc_ports(*args, **kwargs))
register_portchannels(app, lambda *args, **kwargs: apic_get(*args, **kwargs),
                      lambda *args, **kwargs: _collect_acc_ports(*args, **kwargs),
                      cached, _json_route, collection_warning)

register_access(app, lambda *args, **kwargs: apic_get(*args, **kwargs), cached, _json_route, collection_warning)

register_history(app, lambda *args, **kwargs: _apic_get_page(*args, **kwargs), _json_route)
register_resources(app, lambda *args, **kwargs: apic_get(*args, **kwargs), cached, _json_route, collection_warning)

register_l3out(app, lambda *args, **kwargs: apic_get(*args, **kwargs), get_l3out_subnets, cached, _json_route)


def retired_l3out_page():
    return redirect("/l3out_explorer", code=302)

for index, rule in enumerate([
    '/l3out_fw_internet_prod',
    '/l3out_fw_pix_unibc_prod',
    '/l3out_fw_pix_sede_prod',
    '/l3out_fw_servidores_prod',
    '/l3out_storage_offload',
    '/l3out_fw_pix_homologa_sede',
    '/l3out_fw_pix_homologa_unibc',
    '/l3out_fw_pix_teste_sede_prod',
    '/l3out_fw_pix_teste_unibc_prod',
    '/l3out_sw_distribuicao_2ss_prod',
    '/l3out_sw_distribuicao_unibc_prod',
]):
    app.add_url_rule(rule, f"retired_l3out_{index}", retired_l3out_page)

# RUN
# ===========================================================================
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 8000)), debug=False)
