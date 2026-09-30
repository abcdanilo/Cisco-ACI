/* Shared controls for the existing report pages. All APIC text is inserted as text. */
(() => {
  'use strict';
  let forceRefresh = false;
  const selected = new Map();
  for (const key of ['status','severity']) { const value=new URLSearchParams(location.search).get(key); if(value)selected.set(key,value); }
  const searchInput = document.getElementById('searchInput');
  const requestedQuery = new URLSearchParams(location.search).get('q');
  if (searchInput && requestedQuery) searchInput.value = requestedQuery;
  const panel = document.createElement('section');
  panel.className = 'report-tools';
  panel.setAttribute('aria-label', 'Atualização e filtros do relatório');
  const style = document.createElement('style');
  style.textContent = '.report-tools{display:flex;flex-wrap:wrap;align-items:center;gap:12px;margin:16px 0;padding:14px;border:1px solid var(--border,#888);border-radius:10px;background:var(--surface,#fff);color:var(--text,#222)}.report-tools label{display:flex;gap:6px;align-items:center;font-size:12px}.report-tools select,.report-tools button{padding:7px;border:1px solid var(--border,#888);border-radius:6px;background:var(--surface-2,#eee);color:inherit;max-width:240px}.report-tools button{cursor:pointer}.report-tools button:disabled{opacity:.5;cursor:wait}.report-tools-status{flex-basis:100%;font-size:12px}.report-tools-warning{color:var(--orange,#b45309);white-space:pre-wrap}';
  document.head.append(style);
  const toolbar = document.querySelector('.toolbar');
  const table = document.querySelector('table');
  if (toolbar) toolbar.before(panel);
  else if (table) table.parentElement.before(panel);
  else document.body.append(panel);
  const button = document.createElement('button');
  button.type = 'button';
  button.textContent = 'Atualizar dados';
  panel.append(button);
  const status = document.createElement('div');
  status.className = 'report-tools-status';
  status.setAttribute('role', 'status');
  status.textContent = 'Consultando dados…';
  const warnings = document.createElement('div');
  warnings.className = 'report-tools-status report-tools-warning';
  warnings.setAttribute('role', 'alert');
  panel.append(status, warnings);

  const fields = [['tenant','Tenant'],['pod','Pod'],['node','Node'],
    ['policy_group','Policy Group'],['acc','Policy Group'],['adminSt','Administrativo'],
    ['admin_st','Administrativo'],['status','Estado'],['severity','Severidade']];
  function fieldValue(row, field) {
    if (row[field] != null && row[field] !== '') return String(row[field]);
    const dn = row.dn || row.endpoint_dn || row.fabric_path || row.path || '';
    const patterns = {tenant: /(?:^|\/)tn-([^/]+)/, pod: /pod-(\d+)/, node: /node-(\d+)/};
    return patterns[field] ? (String(dn).match(patterns[field]) || [,''])[1] : '';
  }
  window.matchesReportFilters = row => [...selected].every(([field, value]) => !value || fieldValue(row, field) === value);
  function populateFilters(rows) {
    panel.querySelectorAll('label').forEach(el => el.remove());
    for (const [field, title] of fields) {
      const values = [...new Set(rows.map(row => fieldValue(row, field)).filter(Boolean))].sort((a,b) => a.localeCompare(b, undefined, {numeric:true}));
      if (!values.length && !selected.get(field)) { selected.delete(field); continue; }
      const label = document.createElement('label');
      label.append(document.createTextNode(title + ' '));
      const select = document.createElement('select');
      select.setAttribute('aria-label', title);
      select.add(new Option('Todos', ''));
      values.forEach(value => select.add(new Option(value, value)));
      const previous = selected.get(field) || '';
      if(previous && !values.includes(previous)) select.add(new Option(previous,previous));
      select.value = previous;
      selected.set(field, select.value);
      select.addEventListener('change', () => {
        selected.set(field, select.value);
        if (typeof applyFilter === 'function') applyFilter();
      });
      label.append(select);
      panel.insertBefore(label, status);
    }
  }
  window.fetchReport = async url => {
    button.disabled = true;
    status.textContent = 'Consultando dados…';
    warnings.textContent = '';
    try {
      const target = new URL(url, location.href);
      if (forceRefresh) target.searchParams.set('refresh', '1');
      forceRefresh = false;
      const response = await fetch(target, {cache:'no-store'});
      if (!response.ok) throw new Error('Falha na consulta (HTTP ' + response.status + '). Tente atualizar novamente.');
      const rows = await response.clone().json();
      if (!Array.isArray(rows)) throw new Error('Resposta de dados inesperada.');
      populateFilters(rows);
      const collected = response.headers.get('X-Collected-At');
      const timestamp = collected ? new Date(collected).toLocaleString('pt-BR') : 'indisponível';
      const cache = response.headers.get('X-Data-Cache') === 'hit' ? ' — dados do cache' : '';
      status.textContent = 'Coleta: ' + timestamp + cache + ' — ' + rows.length + ' registros';
      const notices = JSON.parse(response.headers.get('X-Collection-Warnings') || '[]');
      warnings.textContent = notices.length ? 'Resultado parcial:\n' + notices.join('\n') : '';
      return response;
    } catch (error) {
      status.textContent = 'Não foi possível atualizar os dados.';
      warnings.textContent = error.message;
      throw error;
    } finally {
      button.disabled = false;
    }
  };
  button.addEventListener('click', async () => {
    forceRefresh = true;
    if (typeof fetchData === 'function') await fetchData();
  });

  // Add drill-down links after the existing report renderer updates the table.
  function physicalDnFromText(text) {
    const direct = text.match(/^topology\/pod-(\d+)\/node-(\d+)\/sys\/phys-\[(eth\d+\/\d+(?:\/\d+)?)\](?:\/phys)?$/);
    const path = text.match(/^pod-(\d+)\s*\/\s*node-(\d+)\s*\/\s*(eth\d+\/\d+(?:\/\d+)?)$/);
    const fabric = text.match(/^topology\/pod-(\d+)\/paths-(\d+)\/pathep-\[(eth\d+\/\d+(?:\/\d+)?)\]$/);
    const match = direct || path || fabric;
    return match ? `topology/pod-${match[1]}/node-${match[2]}/sys/phys-[${match[3]}]` : '';
  }
  const tbody = document.getElementById('tableBody');
  if (tbody) {
    const addLinks = () => {
      const headings = [...document.querySelectorAll('thead th')];
      for (const row of tbody.rows) for (const cell of row.cells) {
        if (cell.querySelector('a') || cell.colSpan > 1) continue;
        const text = cell.textContent.trim();
        const dn = physicalDnFromText(text);
        const key = headings[cell.cellIndex]?.dataset.key;
        const endpoint = ['/endpoints','/ip_endpoints'].includes(location.pathname) && ['mac','ip'].includes(key) && text && text !== '—';
        if (!dn && !endpoint) continue;
        const anchor = document.createElement('a');
        anchor.href = dn ? '/interface_details?' + new URLSearchParams({dn}) : '/endpoint_lookup?' + new URLSearchParams({q:text});
        anchor.style.color = 'var(--blue, #66a5ff)';
        anchor.title = dn ? 'Ver estado e estatísticas da interface' : 'Localizar este endpoint';
        anchor.append(...cell.childNodes);
        cell.append(anchor);
      }
    };
    new MutationObserver(addLinks).observe(tbody, {childList:true, subtree:true});
    addLinks();
  }
})();
