(() => {
 const $=id=>document.getElementById(id),params=new URLSearchParams(location.search);let page=0,active=null,busy=false,more=false;
 const el=(tag,text,cls)=>{const e=document.createElement(tag);e.textContent=text;if(cls)e.className=cls;return e;};
 const local=d=>new Date(d.getTime()-d.getTimezoneOffset()*60000).toISOString().slice(0,16);
 const now=new Date();$('end').value=local(now);$('start').value=local(new Date(now-86400000));$('dn').value=params.get('dn')||'';$('query').value=params.get('q')||'';
 if(['audit','events'].includes(params.get('kind')))$('kind').value=params.get('kind');
 async function load(target){if(busy)return;busy=true;$('search').disabled=true;$('previous').disabled=true;$('next').disabled=true;$('historyError').hidden=true;$('historyRows').replaceChildren();$('historyStatus').textContent='Consultando histórico…';
 try{const response=await fetch('/api/history?'+new URLSearchParams({...active,page:target}),{cache:'no-store'});const data=await response.json();if(!response.ok)throw Error(data.error||'Consulta indisponível.');page=data.page;more=data.has_more;active.start=data.start;active.end=data.end;
 $('historyStatus').textContent=data.rows.length+' registro(s) nesta página.';$('pageLabel').textContent='Página '+(page+1);
 for(const r of data.rows){const card=el('article','', 'panel');card.append(el('h3',r.descr||'Sem descrição'));const d=new Date(r.created);card.append(el('p',(isNaN(d)?r.created:d.toLocaleString('pt-BR'))+' • '+(r.user||'Usuário não informado')));card.append(el('p','Código: '+r.code+' · Ação: '+(r.ind||'—')+' · Severidade: '+(r.severity||'—')));card.append(el('p','Objeto: '+(r.affected||'Não informado'),'mono'));const details=el('details','');details.append(el('summary','Detalhes do registro'),el('p','Causa: '+(r.cause||'—')),el('p',r.dn,'mono'));card.append(details);$('historyRows').append(card);}
 if(!data.rows.length)$('historyRows').append(el('p','Nenhum registro retornado para estes filtros.','empty'));
 }catch(e){more=false;$('historyStatus').textContent='Consulta não concluída.';$('historyError').textContent=e.message;$('historyError').hidden=false;}
 finally{busy=false;$('search').disabled=false;$('previous').disabled=page===0;$('next').disabled=!more;}}
 function search(){try{active={kind:$('kind').value,start:new Date($('start').value).toISOString(),end:new Date($('end').value).toISOString(),dn:$('dn').value.trim(),q:$('query').value.trim()};page=0;load(0);}catch(e){$('historyError').hidden=false;$('historyError').textContent='Informe datas válidas.';}}
 $('historyForm').addEventListener('submit',e=>{e.preventDefault();search();});$('previous').addEventListener('click',()=>load(page-1));$('next').addEventListener('click',()=>load(page+1));search();
})();
