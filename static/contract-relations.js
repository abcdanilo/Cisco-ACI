(() => {
 'use strict';
 const byId=id=>document.getElementById(id);
 const el=(tag,text,cls)=>{const e=document.createElement(tag);e.textContent=text;if(cls)e.className=cls;return e;};
 let rows=[],shown=[],offset=0,stamp='';
 const initial=new URLSearchParams(location.search);
 byId('query').value=initial.get('q')||'';
 function attributes(values){const dl=el('dl','','properties');for(const [k,v] of Object.entries(values)){if(v!==''&&v!=null){dl.append(el('dt',k),el('dd',String(v),'mono'));}}return dl;}
 function participant(container,title,list){
   container.append(el('h3',title));
   if(!list.length)container.append(el('p','Nenhuma relação retornada nesta consulta.','muted'));
   for(const r of list){const p=el('p',r.type+' · '+r.dn,'mono');p.append(el('br',''),el('span',r.state+' · '+r.association,r.confirmed?'':'muted'));container.append(p);}
 }
 function card(row){
   const box=el('details','','endpoint-result');
   const summary=el('summary',`${row.tenant} / ${row.name||'Contrato sem nome'} · ${row.providers.length} fornecedor(es) · ${row.consumers.length} consumidor(es)`);
   summary.style.cssText='padding:18px;cursor:pointer;overflow-wrap:anywhere';box.append(summary);
   box.addEventListener('toggle',()=>{
    if(!box.open||box.dataset.loaded)return;box.dataset.loaded='1';
    const content=el('div','','panel');content.append(el('p',row.dn||'Destino não resolvido','mono'),el('p','Escopo: '+(row.scope||'Indisponível')));
    if(!row.available)content.append(el('p','Objeto contrato ausente ou não retornado. Não é possível confirmar os filtros.','warning'));
    if(row.description)content.append(el('p',row.description));
    const peers=el('div','','peer-grid');const prov=el('section','','peer'),cons=el('section','','peer');
    participant(prov,'Fornecedores',row.providers);participant(cons,'Consumidores',row.consumers);peers.append(prov,cons);content.append(peers);
    content.append(el('h3','Subjects e filtros'));
    if(!row.subjects.length)content.append(el('p','Nenhum subject retornado. Isso não comprova ausência de regras.','muted'));
    for(const subject of row.subjects){const section=el('section','','checklist-item');section.append(el('h3',subject.name||subject.dn));
     const options=el('details','');options.append(el('summary','Opções do subject'),attributes(subject.attributes));section.append(options);
     if(!subject.filters.length)section.append(el('p','Nenhuma associação de filtro retornada.'));
     for(const filter of subject.filters){const detail=el('details','');detail.style.cssText='padding:12px 0';detail.append(el('summary',`${filter.name||filter.target||'Filtro não resolvido'} · ${filter.direction} · ação: ${filter.action||'não informada'}`));
      detail.append(el('p',filter.target||'DN de destino não informado','mono'),el('p',filter.state+' · '+filter.association));
      if(!filter.available)detail.append(el('p','Filtro não retornado; entradas não verificadas.','warning'));
      if(filter.available&&!filter.entries.length)detail.append(el('p','Nenhuma entrada retornada para este filtro.'));
      for(const entry of filter.entries){const rule=el('section','','checklist-item');rule.append(el('h4',entry.name||'Entrada de filtro'));
       const fields={'EtherType':entry.etherT,'Protocolo':entry.prot,'Porta origem inicial':entry.sFromPort,'Porta origem final':entry.sToPort,'Porta destino inicial':entry.dFromPort,'Porta destino final':entry.dToPort,'Stateful':entry.stateful,'Flags TCP':entry.tcpRules};
       rule.append(attributes(fields));const all=el('details','');all.append(el('summary','Todos os atributos da entrada'),attributes(entry));rule.append(all);detail.append(rule);}
      const raw=el('details','');raw.append(el('summary','Atributos da associação'),attributes(filter.attributes));detail.append(raw);section.append(detail);
     }
     for(const service of subject.services){const extra=el('details','');extra.append(el('summary','Service graph associado — não avaliado'),attributes(service.attributes));section.append(extra);}
     content.append(section);
    }
    if(row.dn){const link=el('a','Histórico do contrato');link.href='/history?'+new URLSearchParams({dn:row.dn});content.append(link);}
    box.append(content);
   });return box;
 }
 function more(){const next=shown.slice(offset,offset+30);byId('results').append(...next.map(card));offset+=next.length;byId('more').hidden=offset>=shown.length;}
 function filter(){const q=byId('query').value.trim().toLocaleLowerCase(),tenant=byId('tenant').value;
  shown=rows.filter(r=>(!tenant||r.tenants.includes(tenant))&&(!q||r.search.includes(q)));offset=0;byId('results').replaceChildren();
  byId('status').textContent=shown.length+' contrato(s) / referência(s) · '+stamp;
  if(!shown.length)byId('results').append(el('p','Nenhum resultado para os filtros atuais.'));more();
  const params=new URLSearchParams();if(q)params.set('q',byId('query').value);if(tenant)params.set('tenant',tenant);history.replaceState(null,'','/contract_relations'+(params.size?'?'+params:''));
 }
 async function load(force=false){byId('refresh').disabled=true;byId('status').textContent='Consultando contratos, participantes e filtros…';
  rows=[];byId('results').replaceChildren();byId('more').hidden=true;byId('warnings').hidden=true;
  try{const response=await fetch('/api/contract_relations'+(force?'?refresh=1':''),{cache:'no-store'});const data=await response.json();if(!response.ok)throw Error(data.error||'Falha na consulta.');
   rows=data.rows;const date=response.headers.get('X-Collected-At');stamp='Coleta: '+(date?new Date(date).toLocaleString('pt-BR'):'indisponível');
   byId('scope').textContent=data.scope;byId('warnings').textContent=data.warnings.join(' ');byId('warnings').hidden=!data.warnings.length;
   const selected=byId('tenant').value||initial.get('tenant')||'';byId('tenant').replaceChildren(new Option('Todos',''));
   [...new Set(rows.flatMap(r=>r.tenants))].filter(Boolean).sort().forEach(t=>byId('tenant').add(new Option(t,t)));
   if([...byId('tenant').options].some(o=>o.value===selected))byId('tenant').value=selected;filter();
  }catch(error){byId('status').textContent='Consulta não concluída: '+error.message;}finally{byId('refresh').disabled=false;}
 }
 byId('contractForm').addEventListener('submit',e=>{e.preventDefault();filter();});
 byId('query').addEventListener('input',filter);byId('tenant').addEventListener('change',filter);byId('more').addEventListener('click',more);
 byId('refresh').addEventListener('click',()=>load(true));byId('clear').addEventListener('click',()=>{byId('query').value='';byId('tenant').value='';filter();});load();
})();
