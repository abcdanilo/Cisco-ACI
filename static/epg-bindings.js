(() => {
 'use strict';
 const $=id=>document.getElementById(id),initial=new URLSearchParams(location.search);let data=[],page=1,path=initial.get('path')||'',loaded=false;
 function options(id,values){const selected=$(id).value||initial.get(id)||'';initial.delete(id);$(id).replaceChildren(new Option('Todos',''));[...new Set([...values,...(selected?[selected]:[])])].sort().forEach(v=>$(id).add(new Option(v,v)));$(id).value=selected;}
 function render(reset=true){
  if(reset)page=1;const q=$('query').value.trim().toLowerCase(),tenant=$('tenant').value,node=$('node').value,source=$('source').value;
  const selected=data.filter(r=>(!tenant||r.tenant===tenant)&&(!source||r.source===source)&&(!node||r.nodes.includes(node))&&(!path||r.path===path)&&(!q||Object.values(r).join(' ').toLowerCase().includes(q)));
  const query=new URLSearchParams();for(const [k,v] of Object.entries({tenant,node,q,path,source}))if(v)query.set(k,v);
  history.replaceState(null,'','/epg_bindings'+(query.size?'?'+query:''));$('csv').href='/export_csv/port_vlans?'+query;$('csv').hidden=!selected.length;
  $('pathFilter').hidden=!path;$('pathFilter').textContent=path?'Caminho selecionado: '+path:'';
  const pages=Math.max(1,Math.ceil(selected.length/50));page=Math.min(page,pages);$('count').textContent=selected.length+' associação(ões) • '+new Set(selected.map(r=>r.tenant)).size+' tenant(s)';$('rows').replaceChildren();
  $('empty').hidden=!loaded||selected.length>0;
  $('empty').textContent=tenant&&!data.some(r=>r.tenant===tenant)
   ? 'Nenhuma associação foi retornada para '+tenant+'. Verifique avisos de coleta e permissões da APIC. Isso não comprova ausência de VLANs.'
   : 'Nenhuma associação corresponde aos filtros selecionados. Use Limpar filtros para consultar toda a coleta.';
  $('coverage').textContent=loaded?new Set(data.map(r=>r.tenant)).size+' tenant(s) com dados. '+['Estático','AEP','VMM','Deployment dinâmico','L3Out'].map(s=>s+': '+data.filter(r=>r.source===s).length).join(' • ')+'. Registros de origens distintas não representam uma contagem de VLANs únicas.':'';
  for(const r of selected.slice((page-1)*50,page*50)){
   const encap=(!r.vlan||r.vlan==='unknown')?'Não informado':r.vlan;
   const tr=document.createElement('tr');for(const value of [r.tenant,`${r.source} / ${r.evidence}`,r.application,r.epg||r.l3out,encap,r.state,`${r.pod||'—'} / ${r.nodes.join(', ')||'—'}`,r.port||'Não resolvida']){const td=document.createElement('td');td.textContent=value||'—';tr.append(td);}
   tr.lastChild.title=r.path;
   const td=document.createElement('td'),details=document.createElement('details'),summary=document.createElement('summary');summary.textContent='Ver detalhes';details.append(summary);
   for(const [label,value] of [['AEP',r.aep],['Domínio',r.domain],['Modo',r.mode],['Deployment',r.deployment],['Endereço',r.address],['Tipo de interface',r.interface_type],['Caminho',r.path],['Observação',r.note],['DN',r.dn]])if(value){const p=document.createElement('p');p.textContent=label+': '+value;p.style.overflowWrap='anywhere';p.style.whiteSpace='normal';details.append(p);}
   td.style.minWidth='220px';td.append(details);tr.append(td);$('rows').append(tr);
  }
  $('page').textContent='Página '+page+'/'+pages+' • '+(selected.length?(page-1)*50+1:0)+'–'+Math.min(page*50,selected.length)+' de '+selected.length;$('prev').disabled=page===1;$('next').disabled=page===pages;
 }
 async function read(url){const response=await fetch(url,{cache:'no-store'}),body=await response.json();if(!response.ok)throw Error(body.error||'Consulta indisponível.');if(!Array.isArray(body))throw Error('Resposta inesperada.');return {response,body};}
 async function load(force=false){$('reload').disabled=true;$('error').hidden=true;loaded=false;data=[];render(false);$('status').textContent='Consultando vínculos e tenants…';
  try{
   const suffix=force?'?refresh=1':'',results=await Promise.allSettled([read('/api/port_vlans'+suffix),read('/api/epg_binding_tenants'+suffix)]);
   const [bindings,inventory]=results;
   if(bindings.status==='rejected')throw bindings.reason;
   const {response:r,body}=bindings.value;data=body;loaded=true;
   const tenants=inventory.status==='fulfilled'?inventory.value.body:[];
   options('tenant',[...tenants,...data.map(r=>r.tenant)]);options('node',data.flatMap(r=>r.nodes));options('source',data.map(r=>r.source));render();
   const notices=JSON.parse(r.headers.get('X-Collection-Warnings')||'[]');
   if(inventory.status==='rejected')notices.push('Inventário de tenants indisponível. O filtro mostra apenas tenants dos vínculos retornados. '+inventory.reason.message);
   if(notices.length){$('error').textContent=notices.join(' ');$('error').hidden=false;}
   const stamp=r.headers.get('X-Collected-At');$('status').textContent='Coleta de vínculos: '+(stamp?new Date(stamp).toLocaleString('pt-BR'):'indisponível')+(r.headers.get('X-Data-Cache')==='hit'?' • dados do cache':'');
  }
  catch(e){data=[];loaded=false;render();$('error').textContent=e.message;$('error').hidden=false;$('status').textContent='Consulta não concluída.';}
  finally{$('reload').disabled=false;}
 }
 $('query').value=initial.get('q')||'';for(const id of ['tenant','node','source'])$(id).addEventListener('change',()=>render());$('query').addEventListener('input',()=>render());$('bindingFilters').addEventListener('submit',e=>{e.preventDefault();render();});$('reload').addEventListener('click',()=>load(true));$('clear').addEventListener('click',()=>{path='';for(const id of ['tenant','node','source','query'])$(id).value='';render();});$('prev').addEventListener('click',()=>{page--;render(false);});$('next').addEventListener('click',()=>{page++;render(false);});load();
})();
