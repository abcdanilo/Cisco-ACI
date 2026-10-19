(() => {
 'use strict';
 const $=id=>document.getElementById(id), el=(tag,text,cls)=>{const n=document.createElement(tag);n.textContent=text;if(cls)n.className=cls;return n;};
 let rows=[],groups=[],offset=0,stamp='';
 function link(text,path,args){const a=el('a',text);a.href=path+'?'+new URLSearchParams(args);return a;}
 function list(title,values){const section=el('section','','checklist-item');section.append(el('h4',title));if(!values.length)section.append(el('p','Nenhum registro retornado.','muted'));return section;}
 function detail(row){const box=el('details','','endpoint-result');const summary=el('summary',`${row.tenant} / ${row.l3out} · Perfil: ${row.profile||'não informado'} · ${row.protocols.join(', ')||'Protocolo dinâmico não informado'} · ${row.routes.length} rota(s) estática(s)`);summary.style.cssText='padding:16px;cursor:pointer;overflow-wrap:anywhere';box.append(summary);
  const vrf=el('p','VRF: '+(row.vrfs.map(v=>(v.dn||v.name||'não informada')+' ['+v.state+']').join('; ')||'não retornada'),'mono');vrf.style.padding='0 16px';box.append(vrf);
  box.addEventListener('toggle',()=>{if(!box.open||box.dataset.loaded)return;box.dataset.loaded='1';
   const content=el('div','','panel');content.append(el('p','Associação do node: '+row.state+' · Router ID: '+(row.router_id||'não informado')+' · Loopback do Router ID: '+(row.router_id_loopback||'não informado')),el('p',row.profile_dn,'mono'));
   content.append(link('Consultar este L3Out','/l3out_explorer',{tenant:row.tenant,l3out:row.l3out}),el('span',' · '),link('Histórico','/history',{dn:row.out_dn}));
   const ports=list('Interfaces configuradas',row.interfaces);
   for(const port of row.interfaces){const p=el('div','','checklist-item');p.append(el('p',port.path,'mono'),el('p',`Perfil: ${port.profile} · Tipo: ${port.type||'não informado'} · Encap: ${port.encap||'não informado'} · Endereço: ${port.address||'não informado'} · Relação: ${port.state}`));
    for(const m of port.members)p.append(el('p','Membro '+(m.side||'?')+': '+(m.addr||'endereço não informado'),'mono'));
    const match=port.path.match(/^topology\/pod-(\d+)\/paths-(\d+)\/pathep-\[(eth\d+\/\d+(?:\/\d+)?)\]$/);
    if(match)p.append(link('Detalhar interface','/interface_details',{dn:`topology/pod-${match[1]}/node-${match[2]}/sys/phys-[${match[3]}]`}));
    ports.append(p);
   }content.append(ports);
   const routes=list('Rotas estáticas deste node / profile',row.routes);
   for(const route of row.routes){const r=el('div','','checklist-item');r.append(el('p',(route.prefix||'Prefixo não informado')+' · Preferência: '+(route.preference||'não informada'),'mono'));
    for(const hop of route.next_hops)r.append(el('p','Next hop: '+(hop.nhAddr||'não informado')+' · Preferência: '+(hop.pref||'não informada'),'mono'));
    if(!route.next_hops.length)r.append(el('p','Nenhum next hop retornado.','muted'));routes.append(r);
   }content.append(routes);box.append(content);
  });return box;
 }
 function more(){for(const group of groups.slice(offset,offset+15)){const first=group[0],section=el('section','','panel');
   const n=new Set(group.map(r=>r.out_dn)).size;
   section.append(el('h2',`Pod ${first.pod} / Node ${first.node}${first.node_name?' · '+first.node_name:''}`),el('p',`${n} L3Out(s) · ${group.length} associação(ões) de profile · Estado do fabric: ${first.node_state||'indisponível'} · Papel: ${first.node_role||'indisponível'}`,'muted'));
   for(const row of group)section.append(detail(row));$('results').append(section);
  }offset+=15;$('more').hidden=offset>=groups.length;}
 function render(){const q=$('query').value.trim().toLowerCase();const filtered=rows.filter(r=>(!$('tenant').value||r.tenant===$('tenant').value)&&(!$('pod').value||r.pod===$('pod').value)&&(!$('node').value||r.node===$('node').value)&&(!q||JSON.stringify(r).toLowerCase().includes(q)));
  const map=new Map();for(const row of filtered){const k=row.node_dn;if(!map.has(k))map.set(k,[]);map.get(k).push(row);}groups=[...map.values()];offset=0;$('results').replaceChildren();
  $('status').textContent=`${groups.length} node(s) · ${new Set(filtered.map(r=>r.out_dn)).size} L3Out(s) · ${filtered.length} associação(ões) · ${stamp}`;
  if(!groups.length)$('results').append(el('p','Nenhuma associação encontrada para os filtros atuais.'));more();
 }
 async function load(force=false){$('refresh').disabled=true;$('status').textContent='Consultando configurações de L3Out…';rows=[];$('results').replaceChildren();$('more').hidden=true;$('unmapped').hidden=true;$('warnings').hidden=true;
  try{const response=await fetch('/api/l3out_by_leaf'+(force?'?refresh=1':''),{cache:'no-store'});const data=await response.json();if(!response.ok)throw Error(data.error||'Consulta indisponível.');rows=data.rows;
   const date=response.headers.get('X-Collected-At');stamp='Coleta: '+(date?new Date(date).toLocaleString('pt-BR'):'indisponível');$('scope').textContent=data.scope;$('warnings').textContent=data.warnings.join(' ');$('warnings').hidden=!data.warnings.length;
   for(const key of ['tenant','pod','node']){const selected=$(key).value;$(key).replaceChildren(new Option('Todos',''));[...new Set(rows.map(r=>r[key]))].sort((a,b)=>a.localeCompare(b,undefined,{numeric:true})).forEach(v=>$(key).add(new Option(v,v)));if([...$(key).options].some(o=>o.value===selected))$(key).value=selected;}
   $('unmapped').hidden=!data.unmapped.length;$('unmappedTitle').textContent=data.unmapped.length+' configuração(ões) com associação incompleta';$('unmappedItems').replaceChildren();
   for(const row of data.unmapped){const p=el('p',`${row.tenant} / ${row.l3out} · ${row.reason}`);p.append(el('br',''),el('span',row.dn,'mono'));$('unmappedItems').append(p);}render();
  }catch(e){$('status').textContent='Consulta não concluída: '+e.message;}finally{$('refresh').disabled=false;}
 }
 $('filters').addEventListener('submit',e=>{e.preventDefault();render();});for(const id of ['tenant','pod','node'])$(id).addEventListener('change',render);$('query').addEventListener('input',render);
 $('more').addEventListener('click',more);$('refresh').addEventListener('click',()=>load(true));$('clear').addEventListener('click',()=>{for(const id of ['tenant','pod','node','query'])$(id).value='';render();});load();
})();
