(() => {
 'use strict';
 const $=id=>document.getElementById(id),el=(tag,text,cls)=>{const x=document.createElement(tag);x.textContent=text;if(cls)x.className=cls;return x;};
 let rows=[],stamp='';const initial=new URLSearchParams(location.search);
 function box(kind,title,tone){const x=el('section','','map-box');x.dataset.level=tone;x.append(el('p',kind,'map-kind'),el('h3',title));return x;}
 function evidence(container,a){const d=el('details','');d.append(el('summary','DN e atributos da APIC'));for(const [k,v] of Object.entries(a))if(v!==''&&v!=null)d.append(el('p',k+': '+v,'mono'));container.append(d);}
 function address(container,label,value){if(value)container.append(el('p',label+': '+value,'map-address'));}
 function related(container,label,page,args){const a=el('a',label);a.href=page+'?'+new URLSearchParams(args);container.append(a);}
 function render(){const row=rows.find(r=>r.dn===$('out').value);$('map').replaceChildren();if(!row){$('status').textContent='Nenhum L3Out corresponde à seleção. '+stamp;return;}
  $('status').textContent=stamp;history.replaceState(null,'','/l3out_map?'+new URLSearchParams({dn:row.dn}));
  const layout=el('div','','map-layout'),tenant=box('Tenant',row.tenant,'tenant');
  const vrf=row.vrfs.length===1?row.vrfs[0]:null;
  const context=box('Contexto de VRF — associação',vrf?(vrf.tDn||vrf.tnFvCtxName||'Destino não informado'):'VRF não confirmada','vrf');
  if(vrf){context.append(el('p','Relação: '+(vrf.state||'não informado'),'map-note'));evidence(context,vrf);}else context.append(el('p','Nenhuma relação única de VRF retornada.','map-note'));
  const out=box('L3Out',row.name,'l3out');if(row.description)out.append(el('p',row.description));out.append(el('p','Protocolos configurados: '+(row.protocols.join(', ')||'não informados'),'muted'));
  related(out,'Consultar rotas e prefixos','/l3out_explorer',{tenant:row.tenant,l3out:row.name});
  const remote=el('aside','','map-box');remote.dataset.level='external';remote.append(el('p','Destino das rotas estáticas','map-kind'),el('h2','Next hops externos'),el('p','Endereços configurados; não comprovam identidade, disponibilidade ou VIP do firewall.','map-note'));
  let hops=0;
  if(!row.profiles.length)out.append(el('p','Nenhum node profile retornado.','map-note'));
  for(const profile of row.profiles){const p=box('Node profile',profile.attributes.name||'Sem nome','node');
   for(const node of profile.nodes){const n=el('div','','map-path');n.append(el('strong',node.attributes.tDn||'Node não identificado'),el('p','Relação: '+(node.attributes.state||'não informada'),'muted'));address(n,'Router ID',node.attributes.rtrId);evidence(n,node.attributes);p.append(n);
    for(const route of node.routes){for(const hop of route.next_hops){hops++;const h=el('div','','map-path');address(h,'Next hop',hop.nhAddr);h.append(el('p','Prefixo: '+(route.attributes.ip||'não informado')),el('p','Node: '+(node.attributes.tDn||'não identificado'),'mono'),el('p','Profile: '+(profile.attributes.name||'não informado'),'muted'));evidence(h,hop);remote.append(h);}}
   }
   if(!profile.nodes.length)p.append(el('p','Nenhuma associação de node retornada.','map-note'));
   for(const iface of profile.interfaces){const i=box('Perfil de interface',iface.attributes.name||'Sem nome','interface');
    if(!iface.paths.length)i.append(el('p','Nenhum caminho de interface retornado.','map-note'));
    for(const path of iface.paths){const a=path.attributes,c=el('div','','map-path');c.append(el('p',a.tDn||'Caminho não identificado','mono'),el('p',(a.ifInstT||'tipo não informado')+' · '+(a.encap||'encap não informado')+' · Relação: '+(a.state||'não informada'),'muted'));address(c,'Endereço da interface',a.addr);
     for(const secondary of path.secondary){address(c,'Endereço adicional da APIC',secondary.addr);evidence(c,secondary);}
     for(const member of path.members){address(c,'Membro '+(member.attributes.side||'?'),member.attributes.addr);for(const secondary of member.secondary)address(c,'Adicional do membro '+(member.attributes.side||'?'),secondary.addr);evidence(c,member.attributes);}
     evidence(c,a);i.append(c);
    }p.append(i);
   }out.append(p);
  }
  if(!hops)remote.append(el('p','Nenhum next hop estático retornado. Rotas dinâmicas não são representadas nesta área.','muted'));
  remote.append(el('p','Nome do firewall, membros do cluster, localização e VIP externos: não identificados por esta consulta.','map-note'));
  const epgs=box('Políticas externas','External EPGs e contratos','epg');
  if(!row.epgs.length)epgs.append(el('p','Nenhum External EPG retornado.','map-note'));
  for(const epg of row.epgs){const e=el('details','','map-path');e.append(el('summary',(epg.attributes.name||'External EPG')+' · '+epg.providers.length+' fornece / '+epg.consumers.length+' consome'));
   for(const [label,contracts] of [['Fornece',epg.providers],['Consome',epg.consumers]])for(const contract of contracts){e.append(el('p',label+': '+(contract.tDn||contract.tnVzBrCPName||'não identificado')+' · '+(contract.state||'estado não informado'),'mono'));related(e,'Ver relações do contrato','/contract_relations',{q:contract.tDn||contract.tnVzBrCPName||''});}
   if(!epg.providers.length&&!epg.consumers.length)e.append(el('p','Nenhuma relação direta retornada; isso não comprova ausência de contratos efetivos.','map-note'));
   for(const prefix of epg.prefixes)e.append(el('p',(prefix.ip||'prefixo não informado')+' · '+(prefix.scope||'scope não informado'),'mono'));evidence(e,epg.attributes);epgs.append(e);
  }out.append(epgs);context.append(out);tenant.append(context);layout.append(tenant,remote);$('map').append(layout);
 }
 function options(preferred){const q=$('searchMap').value.trim().toLowerCase();const list=rows.filter(r=>(!$('tenant').value||r.tenant===$('tenant').value)&&(!q||JSON.stringify(r).toLowerCase().includes(q)));const previous=preferred||$('out').value;$('out').replaceChildren();for(const row of list)$('out').add(new Option(row.tenant+' / '+row.name,row.dn));if(list.some(r=>r.dn===previous))$('out').value=previous;render();}
 async function load(force=false){$('refresh').disabled=true;$('status').textContent='Consultando a hierarquia…';$('map').replaceChildren();const selected=$('out').value||initial.get('dn');
  try{const r=await fetch('/api/l3out_map'+(force?'?refresh=1':''),{cache:'no-store'}),data=await r.json();if(!r.ok)throw Error(data.error||'Consulta indisponível.');rows=data.l3outs;const date=r.headers.get('X-Collected-At');stamp='Coleta: '+(date?new Date(date).toLocaleString('pt-BR'):'indisponível');$('scope').textContent=data.scope;
   const t=$('tenant').value;$('tenant').replaceChildren(new Option('Todos',''));[...new Set(rows.map(r=>r.tenant))].sort().forEach(v=>$('tenant').add(new Option(v,v)));if([...$('tenant').options].some(o=>o.value===t))$('tenant').value=t;options(selected);
  }catch(e){rows=[];$('out').replaceChildren();$('status').textContent='Consulta não concluída: '+e.message;}finally{$('refresh').disabled=false;}
 }
 $('mapFilters').addEventListener('submit',e=>{e.preventDefault();options();});$('tenant').addEventListener('change',()=>options());$('searchMap').addEventListener('input',()=>options());$('out').addEventListener('change',render);$('refresh').addEventListener('click',()=>load(true));$('printMap').addEventListener('click',()=>window.print());load();
})();
