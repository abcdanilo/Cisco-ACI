(() => {
  'use strict';
  const $=id=>document.getElementById(id);
  const el=(tag,text,cls)=>{const e=document.createElement(tag);if(text!=null)e.textContent=text;if(cls)e.className=cls;return e;};
  const percent=value=>value==null?'Indisponível':value.toLocaleString('pt-BR',{maximumFractionDigits:2})+'%';
  const date=value=>{const d=new Date(value);return Number.isFinite(d.getTime())?d.toLocaleString('pt-BR'):'Não informada';};
  function metric(label,value,note){
    const card=el('div',null,'stat-card');card.append(el('h3',label),el('p',percent(value),'metric'));
    if(value!=null){const meter=el('meter');meter.min=0;meter.max=100;meter.value=value;meter.setAttribute('aria-label',label);meter.style.width='100%';card.append(meter);}
    card.append(el('p',note,'hint'));return card;
  }
  function controller(row){
    const card=el('article',null,'panel');card.append(el('h2',row.name),el('p',`Pod ${row.pod} / Node ${row.node} • ${row.model||'Modelo não informado'} • ${row.version||'Versão não informada'} • ${row.state||'Estado não informado'}`,'mono'));
    for(const notice of row.notices)card.append(el('p',notice,'warning'));
    const health=row.health,properties=el('dl',null,'properties');
    for(const [label,key] of [['Saúde do controlador','health'],['Estado administrativo','adminSt'],['Estado operacional','operSt'],['Modo APIC','apicMode'],['Failover','failoverStatus']]){
      const entry=el('div');entry.append(el('dt',label),el('dd',health?.[key]||'Indisponível'));properties.append(entry);
    }
    card.append(properties,el('p','Fonte: infraWiNode da visão do próprio controlador • Última alteração: '+date(health?.modTs)+'. Saúde é um estado, não um percentual de utilização.','hint'));
    const metrics=el('div',null,'stats-grid');metrics.append(metric('CPU',row.cpu_percent,'Utilização informada em procEntity.cpuPct.'),metric('Memória alocada em uso',row.memory_percent,'Calculada: (maxMemAlloc − memFree) / maxMemAlloc. Não desconta cache nem equivale à memória disponível do sistema operacional.'));card.append(metrics);
    card.append(el('p','CPU/memória — última alteração do objeto: '+date(row.process_modified),'hint'),el('h3','Discos e sistemas de arquivos'),el('p','Uso informado em eqptStorage.capUtilized. Inclui montagens como tmpfs; os percentuais não são somados.','hint'));
    if(!row.disks.length)return card;
    const wrap=el('div',null,'pc-table-scroll'),table=el('table',null,'pc-table'),head=el('thead'),hr=el('tr');
    for(const label of ['Montagem / dispositivo','Sistema de arquivos','Utilização','Estado','Última alteração'])hr.append(el('th',label));head.append(hr);table.append(head);
    const body=el('tbody');
    for(const disk of row.disks){const tr=el('tr');tr.append(el('td',disk.mount,'mono'),el('td',disk.filesystem||'Não informado'),el('td',percent(disk.percent)),el('td',[disk.state,disk.reason].filter(Boolean).join(' • ')||'Indisponível'),el('td',date(disk.modified)));body.append(tr);}
    table.append(body);wrap.append(table);card.append(wrap);return card;
  }
  async function load(force=false){
    $('refresh').disabled=true;$('status').textContent='Consultando controladores…';$('warning').hidden=true;
    try{
      const response=await fetch('/api/apic_resources'+(force?'?refresh=1':''),{cache:'no-store'}),body=await response.json();
      if(!response.ok)throw Error(body.error||'Falha ao consultar recursos.');if(!Array.isArray(body))throw Error('Resposta inesperada.');
      $('controllers').replaceChildren(...body.map(controller));
      if(!body.length)$('controllers').append(el('p','Nenhum controlador identificado no inventário retornado.','empty'));
      const warnings=JSON.parse(response.headers.get('X-Collection-Warnings')||'[]');$('warning').textContent=warnings.join('\n');$('warning').hidden=!warnings.length;
      $('status').textContent=`${body.length} controlador(es) • Coleta: ${date(response.headers.get('X-Collected-At'))}`+(response.headers.get('X-Data-Cache')==='hit'?' • dados do cache':'');
    }catch(error){$('controllers').replaceChildren();$('warning').textContent=error.message;$('warning').hidden=false;$('status').textContent='Consulta não concluída.';}
    finally{$('refresh').disabled=false;}
  }
  $('refresh').addEventListener('click',()=>load(true));load();
})();
