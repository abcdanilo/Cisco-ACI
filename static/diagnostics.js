(() => {
  'use strict';

  const byId = id => document.getElementById(id);
  const mode = document.body.dataset.page;
  const params = new URLSearchParams(location.search);
  let busy = false, lastQuery = '', lastDn = '';
  let lastMode = 'address';
  if (mode === 'endpoint') byId('lookupMode').value=params.get('mode')==='name'?'name':'address';
  function element(tag, text, className) {
    const result = document.createElement(tag);
    if (text != null) result.textContent = text;
    if (className) result.className = className;
    return result;
  }
  function link(text, pathname, values) {
    const result = element('a', text);
    result.href = pathname + '?' + new URLSearchParams(values);
    return result;
  }
  function property(list, name, value) {
    const block = element('div');
    block.append(element('dt', name));
    const detail = element('dd');
    detail.append(value instanceof Node ? value : document.createTextNode(value === '' || value == null ? 'Indisponível' : String(value)));
    block.append(detail); list.append(block);
  }
  function timestamp(value) {
    const date = new Date(value);
    return value && Number.isFinite(date.getTime()) ? date.toLocaleString('pt-BR') : 'Indisponível';
  }
  function decimal(value, digits = 2) {
    return typeof value === 'number' && Number.isFinite(value) ? value.toLocaleString('pt-BR', {maximumFractionDigits:digits}) : 'Indisponível';
  }
  function counter(value) {
    return typeof value === 'string' && /^\d+$/.test(value) ? BigInt(value).toLocaleString('pt-BR') : 'Indisponível';
  }
  function notices(values) {
    byId('warning').textContent = values.join('\n');
    byId('warning').hidden = values.length === 0;
  }
  async function load(path, values, force) {
    const query = new URLSearchParams(values);
    if (force) query.set('refresh', '1');
    const response = await fetch(path + '?' + query, {cache:'no-store'});
    let body;
    try { body = await response.json(); } catch (_) { throw new Error('O servidor não retornou uma resposta válida.'); }
    if (!response.ok) throw new Error(body.error || 'Falha na consulta (HTTP ' + response.status + ').');
    const warnings = JSON.parse(response.headers.get('X-Collection-Warnings') || '[]');
    notices(warnings);
    return {body, metadata: 'Coleta: ' + timestamp(response.headers.get('X-Collected-At')) +
      (response.headers.get('X-Data-Cache') === 'hit' ? ' • dados do cache' : '')};
  }
  function setBusy(value) {
    busy = value;
    byId('search').disabled = value;
    byId('refresh').disabled = value || !(mode === 'endpoint' ? lastQuery : lastDn);
  }
  function endpointCard(row) {
    const card = element('article', null, 'endpoint-card');
    const heading = element('div', null, 'heading-row');
    heading.append(element('h2', row.mac || 'MAC indisponível'), element('span', row.encap || 'Encapsulamento indisponível', 'badge'));
    card.append(heading);
    const properties = element('dl', null, 'properties');
    property(properties, 'Endereços IP', (row.ips || []).join(' • '));
    property(properties, 'Tenant', row.tenant);
    property(properties, 'Application Profile', row.application);
    property(properties, 'EPG', row.epg_dn ? link(row.epg || row.epg_dn, '/epgs', {q:row.epg_dn}) : row.epg);
    property(properties, 'Bridge Domain (DN)', row.bd_dn);
    property(properties, 'Descrição', row.description);
    property(properties, 'Nomes disponíveis no APIC', (row.names || []).join(' • '));
    card.append(properties);
    const paths = element('div', null, 'paths');
    paths.append(element('h3', 'Conexões no fabric'));
    if (!row.paths?.length) paths.append(element('p', 'Localização não informada pelo APIC.', 'muted'));
    else {
      const list = element('ul');
      for (const path of row.paths) {
        const item = element('li');
        item.append(path.interface_dn ? link(path.label, '/interface_details', {dn:path.interface_dn}) :
          ['vpc','port-channel'].includes(path.kind) ? link(path.label, '/portchannel_overview', {path:path.dn}) : document.createTextNode(path.label));
        if (!path.interface_dn) item.append(element('span', ' • ' + path.kind, 'muted'));
        for(const sw of path.switches||[])item.append(element('p',`Pod ${sw.pod} / Node ${sw.node} • ${sw.name||'Nome do switch indisponível'}`,'muted'));
        item.append(link('VLANs / EPGs deste caminho','/epg_bindings',{path:path.dn}));
        if(path.mapping)item.append(element('p','Associação PC/vPC: '+path.mapping,'muted'));
        for(const ag of path.aggregates||[])item.append(element('p',`Node ${ag.node} • ${ag.id||'Agregado não confirmado'} • Estado: ${ag.oper_state||'Indisponível'} • Associação: ${ag.mapping}`,'muted'));
        for(const port of path.ports||[]){
          const box=element('div',null,'panel');box.append(link(port.dn,'/interface_details',{dn:port.dn}));
          const props=element('dl',null,'properties');
          for(const [label,value] of [['Descrição da porta',port.description],['Administrativo',port.admin_state],['Operacional',port.oper_state],['Velocidade configurada',port.configured_speed],['Velocidade negociada',port.oper_speed]])property(props,label,value);
          box.append(props);
          box.append(element('h4','Vizinhos da porta • LLDP / CDP'));
          for(const n of port.neighbors||[]){
            const neighbor=element('dl',null,'properties');
            for(const [label,value] of [['Protocolo',n.protocol],['Equipamento anunciado',n.name||n.chassis],['Porta remota',n.remote_port],['IP de gerenciamento',n.management_ip],['Descrição remota',n.description],['Descrição da porta remota',n.port_description]])property(neighbor,label,value);
            box.append(neighbor);
          }
          for(const protocol of ['LLDP','CDP']){
            if(!port.neighbor_queries?.[protocol])box.append(element('p',protocol+': consulta indisponível.','muted'));
            else if(!(port.neighbors||[]).some(n=>n.protocol===protocol))box.append(element('p',protocol+': nenhum vizinho retornado.','muted'));
          }
          item.append(box);
        }
        if(!path.interface_dn&&!path.ports?.length)item.append(element('p','Portas físicas não confirmadas. Abra o caminho para investigar.','muted'));
        list.append(item);
      }
      paths.append(list);
    }
    paths.append(element('p', row.dn || 'DN não informado', 'mono muted'));
    card.append(paths);
    return card;
  }
  async function searchEndpoint(query, force = false) {
    if (busy) return;
    setBusy(true); notices([]);
    byId('status').textContent = 'Consultando endpoints…';
    byId('export').hidden = true;
    byId('results').replaceChildren();
    try {
      const lookupMode=force?lastMode:byId('lookupMode').value;
      const {body:rows, metadata} = await load('/api/endpoint_lookup', {q:query,mode:lookupMode}, force);
      if (!Array.isArray(rows)) throw new Error('Formato de endpoints inesperado.');
      lastQuery = query;
      lastMode=lookupMode;
      history.replaceState(null, '', '/endpoint_lookup?' + new URLSearchParams({q:query,mode:lookupMode}));
      byId('status').textContent = rows.length + ' endpoint(s) encontrado(s) • ' + metadata;
      if (!rows.length) byId('results').append(element('div', 'Nenhum endpoint encontrado. Se o nome não estiver disponível na APIC, tente IP ou MAC.', 'empty'));
      else {
        let offset = 0;
        const more = element('button', 'Mostrar mais resultados', 'secondary');
        more.type = 'button';
        const next = () => {
          more.remove();
          rows.slice(offset, offset + 50).forEach(row => byId('results').append(endpointCard(row)));
          offset += 50;
          if (offset < rows.length) byId('results').append(more);
        };
        more.addEventListener('click', next); next();
        byId('export').href = '/export_csv/endpoint_lookup?' + new URLSearchParams({q:query,mode:lookupMode});
        byId('export').hidden = false;
      }
    } catch (error) {
      byId('status').textContent = 'A busca não foi concluída.';
      notices([error.message]);
    } finally { setBusy(false); }
  }
  function sampleCard(sample, title) {
    const card = element('article', null, 'stat-card');
    card.append(element('p', title, 'direction'));
    if (!sample.available) {
      card.append(element('h3', 'Amostra indisponível'), element('p', 'O APIC não forneceu estatísticas de cinco minutos para esta direção.', 'muted'));
      return card;
    }
    const metric = element('div', sample.bytes_per_second == null ? 'Indisponível' : decimal(sample.bytes_per_second * 8 / 1e6, 3), 'metric');
    if (sample.bytes_per_second != null) metric.append(element('span', 'Mbit/s', 'metric-unit'));
    card.append(metric, element('p', 'Taxa média na amostra de 5 minutos', 'muted'));
    const list = element('dl', null, 'properties');
    property(list, 'Bytes/s (média)', decimal(sample.bytes_per_second));
    property(list, 'Pacotes/s (média)', decimal(sample.packets_per_second));
    property(list, 'Bytes no intervalo', counter(sample.bytes_in_interval));
    property(list, 'Pacotes no intervalo', counter(sample.packets_in_interval));
    property(list, 'Bytes acumulados', counter(sample.bytes_cumulative));
    property(list, 'Pacotes acumulados', counter(sample.packets_cumulative));
    card.append(list);
    card.append(element('p', 'Intervalo: ' + timestamp(sample.start) + ' → ' + timestamp(sample.end), 'interval'));
    const end = new Date(sample.end).getTime();
    if (Number.isFinite(end) && Date.now() - end > 15 * 60 * 1000) card.append(element('p', 'Amostra antiga: terminou há mais de 15 minutos.', 'interval stale'));
    return card;
  }
  async function searchInterface(dn, force = false) {
    if (busy) return;
    setBusy(true); notices([]);
    byId('status').textContent = 'Consultando interface e estatísticas…';
    byId('details').hidden = true;
    window.dispatchEvent(new CustomEvent('object-selected',{detail:{dn,force}}));
    const bindingLink=document.getElementById('bindingLink'),physical=dn.match(/^topology\/pod-(\d+)\/node-(\d+)\/sys\/phys-\[(eth\d+\/\d+(?:\/\d+)?)\]$/);
    if(bindingLink){bindingLink.hidden=!physical;if(physical)bindingLink.href='/epg_bindings?'+new URLSearchParams({path:`topology/pod-${physical[1]}/paths-${physical[2]}/pathep-[${physical[3]}]`});}
    try {
      const {body:row, metadata} = await load('/api/interface_details', {dn}, force);
      lastDn = dn;
      history.replaceState(null, '', '/interface_details?' + new URLSearchParams({dn}));
      byId('status').textContent = metadata;
      byId('interfaceTitle').textContent = 'Pod ' + row.pod + ' / Node ' + row.node + ' / ' + row.interface;
      byId('interfaceDn').textContent = row.dn;
      const badge = byId('operBadge');
      badge.textContent = row.oper_state ? row.oper_state.toUpperCase() : 'ESTADO INDISPONÍVEL';
      badge.className = 'badge ' + (['up','down'].includes(row.oper_state) ? row.oper_state : '');
      const props = byId('properties'); props.replaceChildren();
      for (const [name, value] of [['Administrativo',row.admin_state],['Operacional',row.oper_state],['Motivo do estado',row.oper_reason],
        ['Descrição',row.description],['Velocidade configurada',row.configured_speed],['Velocidade operacional',row.oper_speed],
        ['MTU',row.mtu],['Duplex',row.duplex],['Última mudança do link',timestamp(row.last_link_change)]]) property(props,name,value);
      byId('statistics').replaceChildren(sampleCard(row.statistics.ingress,'ENTRADA / RX'),sampleCard(row.statistics.egress,'SAÍDA / TX'));
      byId('details').hidden = false;
    } catch (error) {
      byId('status').textContent = 'Não foi possível consultar a interface.';
      notices([error.message]);
    } finally { setBusy(false); }
  }
  if (mode === 'endpoint') {
    byId('lookupForm').addEventListener('submit', event => { event.preventDefault(); searchEndpoint(byId('query').value.trim()); });
    byId('refresh').addEventListener('click', () => searchEndpoint(lastQuery, true));
    if (params.get('q')) { byId('query').value = params.get('q'); searchEndpoint(params.get('q')); }
  } else {
    byId('interfaceForm').addEventListener('submit', event => {
      event.preventDefault();
      const iface = byId('interface').value.trim().toLowerCase();
      if (!/^eth\d+\/\d+(?:\/\d+)?$/.test(iface)) { notices(['Use uma interface física, por exemplo eth1/1 ou eth1/1/1.']); return; }
      searchInterface('topology/pod-' + byId('pod').value.trim() + '/node-' + byId('node').value.trim() + '/sys/phys-[' + iface + ']');
    });
    byId('refresh').addEventListener('click', () => searchInterface(lastDn, true));
    const dn = params.get('dn');
    if (dn) {
      const match = dn.match(/^topology\/pod-(\d+)\/node-(\d+)\/sys\/phys-\[(eth\d+\/\d+(?:\/\d+)?)\]$/);
      if (match) { byId('pod').value=match[1]; byId('node').value=match[2]; byId('interface').value=match[3]; searchInterface(dn); }
      else notices(['O link contém um DN de interface física inválido.']);
    }
  }
})();
