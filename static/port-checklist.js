(() => {
  'use strict';
  let sequence = 0, pending;
  const labels = {ok:'OK', issue:'Inconsistência', unknown:'Não verificado'};
  const el = (tag, text, cls) => {
    const node = document.createElement(tag);
    node.textContent = text;
    if (cls) node.className = cls;
    return node;
  };
  window.addEventListener('object-selected', async event => {
    const panel = document.getElementById('portChecklist');
    if (!panel) return;
    const id = ++sequence, {dn, force} = event.detail;
    pending?.abort(); pending = new AbortController();
    const status = document.getElementById('portChecklistStatus');
    const scope = document.getElementById('portChecklistScope');
    const items = document.getElementById('portChecklistItems');
    panel.hidden = false; items.replaceChildren(); scope.textContent = '';
    status.textContent = 'Verificando configuração da porta…';
    try {
      const response = await fetch('/api/port_checklist?' + new URLSearchParams({dn,...(force?{refresh:'1'}:{})}),
        {cache:'no-store',signal:pending.signal});
      const data = await response.json();
      if (id !== sequence) return;
      if (!response.ok) throw Error(data.error || 'Consulta indisponível.');
      const date = response.headers.get('X-Collected-At');
      status.textContent = `${data.counts.ok} OK · ${data.counts.issue} inconsistência(s) · ${data.counts.unknown} não verificado(s) · Coleta: ${date?new Date(date).toLocaleString('pt-BR'):'indisponível'}`;
      scope.textContent = data.scope;
      for (const check of data.checks) {
        const item = el('article', '', 'checklist-item');
        const heading = el('h3', check.title);
        heading.prepend(el('span', labels[check.status] || labels.unknown, 'checklist-badge '+check.status));
        item.append(heading, el('p', check.message));
        if (check.evidence.length) {
          const details = el('details', '');
          details.append(el('summary', 'Ver objetos consultados'));
          for (const dn of check.evidence) {
            const row = el('p', '', 'mono'); row.append(el('span', dn+' '));
            const link = el('a', 'Histórico'); link.href = '/history?'+new URLSearchParams({dn});
            row.append(link);
            if (dn.startsWith('uni/infra/funcprof/accportgrp-')) {
              const group = el('a', ' · Abrir Policy Group'); group.href = '/access_group?'+new URLSearchParams({dn}); row.append(group);
            }
            details.append(row);
          }
          item.append(details);
        }
        items.append(item);
      }
    } catch (error) {
      if (id === sequence && error.name !== 'AbortError') status.textContent = 'Checklist não verificado: '+error.message;
    }
  });
})();
