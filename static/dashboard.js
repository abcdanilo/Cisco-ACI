(() => {
  const root=document.getElementById('operationalCards'),button=document.getElementById('dashboardRefresh');
  const groups=[
    {api:'/api/fabric_nodes',cards:[['Switches (leaf/spine)','/fabric_nodes',r=>r.length]]},
    {api:'/api/interfaces/up_full',cards:[['Interfaces físicas','/interfaces/up_full',r=>r.length],['Interfaces UP','/interfaces/up_full?status=up',r=>r.filter(x=>x.status==='up').length],['Interfaces DOWN','/interfaces/up_full?status=down',r=>r.filter(x=>x.status==='down').length]]},
    {api:'/api/endpoints',cards:[['Endpoints','/endpoints',r=>r.length]]},
    {api:'/api/faults',cards:[['Falhas críticas','/faults?severity=critical',r=>r.filter(x=>x.severity==='critical').length],['Falhas major','/faults?severity=major',r=>r.filter(x=>x.severity==='major').length],['Registros de falhas (inclui cleared)','/faults',r=>r.length]]}
  ];
  const el=(tag,text)=>{const e=document.createElement(tag);e.textContent=text;return e;};
  async function load(force=false){button.disabled=true;root.replaceChildren();
    await Promise.all(groups.map(async group=>{
      const cards=group.cards.map(([title,href,count])=>{const a=el('a','');a.href=href;a.className='operational-card';const value=el('strong','…'),note=el('small','Consultando…');a.append(el('span',title),value,note);root.append(a);return {value,note,count};});
      try{const r=await fetch(group.api+(force?'?refresh=1':''),{cache:'no-store'});const rows=await r.json();if(!r.ok||!Array.isArray(rows))throw Error('Consulta indisponível');
        const date=r.headers.get('X-Collected-At'),warnings=JSON.parse(r.headers.get('X-Collection-Warnings')||'[]');
        for(const c of cards){c.value.textContent=c.count(rows).toLocaleString('pt-BR');c.note.textContent=(warnings.length?'Coleta parcial · ':'')+(date?new Date(date).toLocaleString('pt-BR'):'Horário indisponível');c.note.title=warnings.join('\n');}
      }catch(e){for(const c of cards){c.value.textContent='—';c.note.textContent='Indisponível; tente atualizar.';}}
    }));button.disabled=false;
  }
  button.addEventListener('click',()=>load(true));load();
})();
