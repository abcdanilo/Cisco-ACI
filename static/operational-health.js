(() => {
 'use strict';const $=id=>document.getElementById(id),tenant=$('healthPage').dataset.kind==='tenant';let data=[],page=1;
 const el=(tag,text)=>{const e=document.createElement(tag);if(text!=null)e.textContent=text;return e;};
 const value=n=>n==null?'Indisponível':n.toLocaleString('pt-BR',{maximumFractionDigits:2});
 const date=s=>s&&Number.isFinite(Date.parse(s))?new Date(s).toLocaleString('pt-BR'):'Não informado';
 const headers=tenant?['Tenant','Saúde (0–100)','Critical','Major','Minor','Warning','Atualização da saúde','Detalhes']:['Switch','Pod / Node','Tipo','CPU média (%)','Usuário (%)','Kernel (%)','Início da amostra','Fim da amostra','Observação'];
 const head=el('tr');headers.forEach(h=>head.append(el('th',h)));$('head').append(head);
 function render(reset=true){if(reset)page=1;const q=$('query').value.trim().toLowerCase(),role=$('role')?.value||'';
  const selected=data.filter(r=>(!role||r.role===role)&&(!q||[r.tenant,r.name,r.pod,r.node,r.role].filter(Boolean).join(' ').toLowerCase().includes(q)));
  const pages=Math.max(1,Math.ceil(selected.length/50));page=Math.min(page,pages);$('rows').replaceChildren();$('count').textContent=selected.length+' registro(s)';
  for(const r of selected.slice((page-1)*50,page*50)){const tr=el('tr');
   if(tenant){tr.append(el('td',r.tenant),el('td',value(r.score)));
    for(const severity of ['critical','major','minor','warning']){const td=el('td');if(r.faults[severity]!=null){const a=el('a',value(r.faults[severity]));a.href='/faults?'+new URLSearchParams({tenant:r.tenant,severity});td.append(a);}else td.textContent='Indisponível';tr.append(td);}
    tr.append(el('td',date(r.updated)));const details=el('td'),a=el('a','Ver faults');a.href='/faults?'+new URLSearchParams({tenant:r.tenant});details.append(a);for(const note of r.notices)details.append(el('p',note));tr.append(details);
   }else{const old=r.end&&Number.isFinite(Date.parse(r.end))&&Date.now()-Date.parse(r.end)>900000;const notice=[old?'Amostra antiga (>15 min).':'',r.notice].filter(Boolean).join(' ');[r.name,`${r.pod} / ${r.node}`,r.role,value(r.cpu),value(r.user),value(r.kernel),date(r.start),date(r.end),notice||'—'].forEach(v=>tr.append(el('td',v)));if(old)tr.lastChild.className='stale';}
   $('rows').append(tr);
  }
  $('prev').disabled=page===1;$('next').disabled=page===pages;$('page').textContent='Página '+page+'/'+pages;
 }
 async function load(force=false){$('reload').disabled=true;$('warning').hidden=true;$('status').textContent='Consultando APIC…';
  try{const r=await fetch((tenant?'/api/tenant_health':'/api/switch_cpu')+(force?'?refresh=1':''),{cache:'no-store'}),body=await r.json();if(!r.ok)throw Error(body.error||'Consulta indisponível.');if(!Array.isArray(body))throw Error('Resposta inesperada.');data=body;render();const warnings=JSON.parse(r.headers.get('X-Collection-Warnings')||'[]');$('warning').textContent=warnings.join('\n');$('warning').hidden=!warnings.length;$('status').textContent='Coleta: '+date(r.headers.get('X-Collected-At'))+(r.headers.get('X-Data-Cache')==='hit'?' • dados do cache':'');}
  catch(e){data=[];render();$('warning').textContent=e.message;$('warning').hidden=false;$('status').textContent='Consulta não concluída.';}
  finally{$('reload').disabled=false;}
 }
 $('query').addEventListener('input',()=>render());$('role')?.addEventListener('change',()=>render());$('filters').addEventListener('submit',e=>{e.preventDefault();render();});$('reload').addEventListener('click',()=>load(true));$('prev').addEventListener('click',()=>{page--;render(false);});$('next').addEventListener('click',()=>{page++;render(false);});load();
})();
