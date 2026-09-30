(() => {
  let sequence=0;
  const el=(tag,text)=>{const e=document.createElement(tag);e.textContent=text;return e;};
  window.addEventListener('object-selected',async event=>{
    const id=++sequence,{dn,force}=event.detail;
    const panel=document.getElementById('objectFaultPanel'),status=document.getElementById('objectFaultStatus'),list=document.getElementById('objectFaultList');
    let history=panel.querySelector('[data-history]');if(!history){history=document.createElement('a');history.dataset.history='';history.textContent='Ver histórico deste objeto →';panel.insertBefore(history,status);}history.href='/history?'+new URLSearchParams({dn});
    panel.hidden=false;list.replaceChildren();status.textContent='Consultando falhas…';
    try {
      const response=await fetch('/api/object_faults?'+new URLSearchParams({dn,...(force?{refresh:'1'}:{})}),{cache:'no-store'});
      const rows=await response.json();if(id!==sequence)return;
      if(!response.ok)throw Error(rows.error||'Falha na consulta.');
      if(!Array.isArray(rows))throw Error('Resposta inesperada.');
      const date=response.headers.get('X-Collected-At');
      status.textContent=rows.length+' falha(s) relacionada(s). Coleta: '+(date?new Date(date).toLocaleString('pt-BR'):'indisponível');
      if(!rows.length)list.append(el('p','Nenhuma falha retornada para este objeto e seus descendentes.'));
      for(const row of rows){const item=el('details','');item.style.cssText='padding:12px 0;border-bottom:1px solid var(--border);overflow-wrap:anywhere';
        item.append(el('summary',row.severity.toUpperCase()+' · '+row.code+' · '+row.description));
        for(const [label,value] of [['Causa',row.cause],['Criada em',row.created],['Última transição',row.last_transition],['Objeto afetado',row.affected],['DN',row.dn]])item.append(el('p',label+': '+(value||'Indisponível')));
        list.append(item);}
    }catch(error){if(id===sequence)status.textContent='Falhas indisponíveis: '+error.message;}
  });
})();
