(() => {
 'use strict';
 const $=id=>document.getElementById(id),initial=new URLSearchParams(location.search);let data=[],page=1,path=initial.get('path')||'',loaded=false;
 function options(id,values){const selected=$(id).value||initial.get(id)||'';initial.delete(id);$(id).replaceChildren(new Option('Todos',''));[...new Set([...values,...(selected?[selected]:[])])].sort().forEach(v=>$(id).add(new Option(v,v)));$(id).value=selected;}
 function render(reset=true){
  if(reset)page=1;const q=$('query').value.trim().toLowerCase(),tenant=$('tenant').value,node=$('node').value;
  const selected=data.filter(r=>(!tenant||r.tenant===tenant)&&(!node||r.nodes.includes(node))&&(!path||r.path===path)&&(!q||Object.values(r).join(' ').toLowerCase().includes(q)));
  const query=new URLSearchParams();for(const [k,v] of Object.entries({tenant,node,q,path}))if(v)query.set(k,v);
  history.replaceState(null,'','/epg_bindings'+(query.size?'?'+query:''));$('csv').href='/export_csv/epg_bindings?'+query;$('csv').hidden=!selected.length;
  $('pathFilter').hidden=!path;$('pathFilter').textContent=path?'Caminho selecionado: '+path:'';
  const pages=Math.max(1,Math.ceil(selected.length/50));page=Math.min(page,pages);$('count').textContent=selected.length+' vínculo(s) configurado(s)';$('rows').replaceChildren();
  $('empty').hidden=!loaded||selected.length>0;
  $('empty').textContent=tenant&&!data.some(r=>r.tenant===tenant)
   ? 'Nenhum vínculo estático direto de EPG foi retornado para '+tenant+'. Isso não comprova ausência de VLANs: associações via AEP, VMM e interfaces L3Out não são consultadas nesta tela.'
   : 'Nenhum vínculo estático corresponde aos filtros selecionados. Use Limpar filtros para consultar toda a coleta.';
  $('coverage').textContent=loaded?new Set(data.map(r=>r.tenant)).size+' tenant(s) com vínculos estáticos nesta coleta. O filtro inclui também tenants do inventário sem vínculos retornados.':'';
  for(const r of selected.slice((page-1)*50,page*50)){
   const tr=document.createElement('tr');for(const value of [r.tenant,r.application,r.epg,r.vlan,r.mode,r.deployment,r.state,`${r.pod||'—'} / ${r.nodes.join(', ')||'—'}`,r.port||r.path]){const td=document.createElement('td');td.textContent=value||'—';tr.append(td);}
   tr.lastChild.title=r.path;$('rows').append(tr);
  }
  $('page').textContent='Página '+page+'/'+pages+' • '+(selected.length?(page-1)*50+1:0)+'–'+Math.min(page*50,selected.length)+' de '+selected.length;$('prev').disabled=page===1;$('next').disabled=page===pages;
 }
 async function read(url){const response=await fetch(url,{cache:'no-store'}),body=await response.json();if(!response.ok)throw Error(body.error||'Consulta indisponível.');if(!Array.isArray(body))throw Error('Resposta inesperada.');return {response,body};}
 async function load(force=false){$('reload').disabled=true;$('error').hidden=true;loaded=false;data=[];render(false);$('status').textContent='Consultando vínculos e tenants…';
  try{
   const suffix=force?'?refresh=1':'',results=await Promise.allSettled([read('/api/epg_bindings'+suffix),read('/api/epg_binding_tenants'+suffix)]);
   const [bindings,inventory]=results;
   if(bindings.status==='rejected')throw bindings.reason;
   const {response:r,body}=bindings.value;data=body;loaded=true;
   const tenants=inventory.status==='fulfilled'?inventory.value.body:[];
   options('tenant',[...tenants,...data.map(r=>r.tenant)]);options('node',data.flatMap(r=>r.nodes));render();
   if(inventory.status==='rejected'){$('error').textContent='Inventário de tenants indisponível. O filtro mostra apenas tenants dos vínculos retornados. '+inventory.reason.message;$('error').hidden=false;}
   const stamp=r.headers.get('X-Collected-At');$('status').textContent='Coleta de vínculos: '+(stamp?new Date(stamp).toLocaleString('pt-BR'):'indisponível')+(r.headers.get('X-Data-Cache')==='hit'?' • dados do cache':'');
  }
  catch(e){data=[];loaded=false;render();$('error').textContent=e.message;$('error').hidden=false;$('status').textContent='Consulta não concluída.';}
  finally{$('reload').disabled=false;}
 }
 $('query').value=initial.get('q')||'';for(const id of ['tenant','node'])$(id).addEventListener('change',()=>render());$('query').addEventListener('input',()=>render());$('bindingFilters').addEventListener('submit',e=>{e.preventDefault();render();});$('reload').addEventListener('click',()=>load(true));$('clear').addEventListener('click',()=>{path='';for(const id of ['tenant','node','query'])$(id).value='';render();});$('prev').addEventListener('click',()=>{page--;render(false);});$('next').addEventListener('click',()=>{page++;render(false);});load();
})();
