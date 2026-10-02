(() => {
  'use strict';

  const $=id=>document.getElementById(id),params=new URLSearchParams(location.search);
  let rows=[],busy=false,exactPath=params.get('path')||'';
  const kinds={vpc:'vPC',pc:'Port-channel',unassociated:'Não associado'};
  const mappings={confirmed:'Associação confirmada por membros físicos',inferred:'Correlacionado por nome exato, pod e node do caminho lógico. Deployment físico não confirmado.',ambiguous:'Associação ambígua',unresolved:'Agregado não identificado',standalone:'Sem caminho lógico associado'};
  const create=(tag,text,cls)=>{const e=document.createElement(tag);if(text!=null)e.textContent=text;if(cls)e.className=cls;return e;};
  const badge=value=>create('span',value||'Indisponível','badge '+(['up','down'].includes(value)?value:''));
  function memberTable(members){
    const wrap=create('div',null,'pc-table-scroll'),table=create('table',null,'pc-table'),head=create('thead'),tr=create('tr');
    ['Interface','Admin','Operacional','Velocidade','Descrição'].forEach(t=>tr.append(create('th',t)));head.append(tr);table.append(head);
    const body=create('tbody');
    for(const member of members){
      const row=create('tr'),cell=create('td'),a=create('a',member.interface);
      a.href='/interface_details?'+new URLSearchParams({dn:member.dn});cell.append(a);row.append(cell);
      for(const state of [member.admin_state,member.oper_state]){const td=create('td');td.append(badge(state));row.append(td);}
      row.append(create('td',member.speed||'Indisponível'),create('td',member.description||'—'));body.append(row);
    }
    table.append(body);wrap.append(table);return wrap;
  }
  let currentPage=1;
  function table(groups){
    const wrap=create('div',null,'compact-scroll'),t=create('table',null,'compact-pc'),head=create('thead'),header=create('tr');
    ['Grupo','Tipo','Pod / Nodes','Port-channel por node','Estado por node','Membros / velocidade','Detalhes'].forEach(label=>{const th=create('th',label);th.scope='col';header.append(th);});
    head.append(header);t.append(head);const body=create('tbody');
    for(const group of groups){
      const row=create('tr',null,'group-start'),name=create('td',null,'group-name');
      name.append(create('strong',group.name));
      if(group.kind!=='unassociated'){const link=create('a','VLANs / EPGs');link.href='/epg_bindings?'+new URLSearchParams({path:group.id});const line=create('div');line.append(link);name.append(line);}
      if(group.coverage==='partial')name.append(create('small','Associação parcial','stale'));
      if(group.nodes.some(n=>n.mapping==='inferred'))name.append(create('small','Associação por nome + topologia','muted'));
      const peers=create('td',`Pod ${group.pod}`,'mono'),pcs=create('td'),states=create('td'),members=create('td',null,'compact-members');
      const cell=create('td'),details=create('details');details.append(create('summary','Ver detalhes'),create('p',group.id,'mono muted'));
      for(const node of group.nodes){
        const pc=node.aggregate;
        peers.append(create('div','Node '+node.node,'peer-line'));
        pcs.append(create('div',`Node ${node.node}: ${pc?.id||'Não identificado'}`,'peer-line mono'));
        const state=create('div',null,'peer-line');state.append(create('span',`Node ${node.node}: `),badge(pc?.oper_state));states.append(state);
        const ports=create('div',null,'peer-line');ports.append(create('strong','Node '+node.node));
        for(const member of node.members){const a=create('a',`pod-${group.pod} / node-${node.node} / ${member.interface} • ${member.speed||'Velocidade indisponível'}`,'member-chip');a.href='/interface_details?'+new URLSearchParams({dn:member.dn});ports.append(a);}
        if(!node.members.length)ports.append(create('div','Membros não informados','muted'));
        members.append(ports);
        details.append(create('h3','Node '+node.node),create('p',mappings[node.mapping]),create('p','Administrativo: '+(pc?.admin_state||'indisponível')+' • Protocolo/modo: '+(pc?.mode||'indisponível')));
        if(!pc&&node.members.length)details.append(create('p','Portas do deployment; vínculo com o agregado não confirmado.','stale'));
        if(node.members.length)details.append(memberTable(node.members));
      }
      cell.append(details);row.append(name,create('td',kinds[group.kind]),peers,pcs,states,members,cell);body.append(row);
    }
    t.append(body);wrap.append(t);return wrap;
  }
  function filter(reset=true){
    if(reset)currentPage=1;
    const q=$('query').value.trim().toLowerCase(),kind=$('kind').value,pod=$('pod').value,node=$('node').value,state=$('state').value;
    const visible=rows.filter(g=>(!q||g.search_text.includes(q))&&(!kind||g.kind===kind)&&(!pod||g.pod===pod)&&(!exactPath||g.id===exactPath)&&g.nodes.some(n=>(!node||n.node===node)&&(!state||n.aggregate?.oper_state===state)));
    $('groups').replaceChildren();$('count').textContent=visible.length+' grupo(s) encontrado(s)';
    $('pathFilter').hidden=!exactPath;$('pathFilter').textContent=exactPath?'Caminho selecionado: '+exactPath:'';
    const query=new URLSearchParams();for(const [key,val] of Object.entries({q:$('query').value.trim(),kind,pod,node,state,path:exactPath}))if(val)query.set(key,val);
    history.replaceState(null,'','/portchannel_overview'+(query.size?'?'+query:''));
    $('export').href='/export_csv/portchannel_overview?'+query;$('export').hidden=!visible.length;
    if(!visible.length){$('groups').append(create('p','Nenhum grupo encontrado com estes filtros.','empty'));return;}
    const size=10,pages=Math.ceil(visible.length/size);currentPage=Math.min(currentPage,pages);
    const start=(currentPage-1)*size,subset=visible.slice(start,start+size);
    $('groups').append(table(subset));
    const nav=create('nav',null,'compact-pagination');nav.setAttribute('aria-label','Paginação dos grupos');
    const previous=create('button','Anterior','secondary'),next=create('button','Próxima','secondary');
    previous.type=next.type='button';previous.disabled=currentPage===1;next.disabled=currentPage===pages;
    previous.addEventListener('click',()=>{currentPage--;filter(false);});next.addEventListener('click',()=>{currentPage++;filter(false);});
    nav.append(create('span',`Grupos ${start+1}–${Math.min(start+size,visible.length)} de ${visible.length} • Página ${currentPage}/${pages}`),previous,next);
    $('groups').append(nav);
  }

  async function load(force=false){
    if(busy)return;busy=true;$('refresh').disabled=true;$('status').textContent='Consultando agregados, caminhos e membros físicos…';$('warning').hidden=true;
    try{
      const response=await fetch('/api/portchannel_overview'+(force?'?refresh=1':''),{cache:'no-store'});
      const body=await response.json();if(!response.ok)throw new Error(body.error||'Falha na consulta.');if(!Array.isArray(body))throw new Error('Resposta inesperada.');
      rows=body;const pod=$('pod').value||params.get('pod')||'';params.delete('pod');$('pod').replaceChildren(new Option('Todos',''));
      [...new Set([...rows.map(g=>g.pod),...(pod?[pod]:[])])].sort((a,b)=>+a-+b).forEach(p=>$('pod').add(new Option(p,p)));$('pod').value=pod;
      const node=$('node').value||params.get('node')||'';params.delete('node');$('node').replaceChildren(new Option('Todos',''));
      [...new Set([...rows.flatMap(g=>g.nodes.map(n=>n.node)),...(node?[node]:[])])].sort((a,b)=>+a-+b).forEach(n=>$('node').add(new Option(n,n)));$('node').value=node;
      const notices=JSON.parse(response.headers.get('X-Collection-Warnings')||'[]');$('warning').textContent=notices.join('\n');$('warning').hidden=!notices.length;
      const stamp=new Date(response.headers.get('X-Collected-At') || NaN);
      $('status').textContent='Coleta: '+(Number.isFinite(stamp.getTime())?stamp.toLocaleString('pt-BR'):'indisponível')+(response.headers.get('X-Data-Cache')==='hit'?' • dados do cache':'');
      filter();
    }catch(error){rows=[];filter();$('status').textContent='A consulta não foi concluída.';$('warning').textContent=error.message;$('warning').hidden=false;}
    finally{busy=false;$('refresh').disabled=false;}
  }
  $('query').value=params.get('q')||'';$('kind').value=params.get('kind')||'';
  $('state').value=params.get('state')||'';
  $('filters').addEventListener('submit',event=>{event.preventDefault();filter();});
  $('query').addEventListener('input',filter);for(const id of ['kind','pod','node','state'])$(id).addEventListener('change',filter);
  $('refresh').addEventListener('click',()=>load(true));
  $('clear').addEventListener('click',()=>{for(const id of ['query','kind','pod','node','state'])$(id).value='';exactPath='';params.delete('pod');params.delete('node');filter();});
  load();
})();
