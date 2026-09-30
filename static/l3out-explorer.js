(() => {
 const $=id=>document.getElementById(id),initial=new URLSearchParams(location.search);let data=null,page=1;
 const option=(select,value,label=value)=>select.add(new Option(label,value));
 function setOptions(id,values,selected){const s=$(id);s.replaceChildren(new Option('Todos',''));values.forEach(v=>option(s,v));if(selected&&!values.includes(selected))option(s,selected,selected+' (não localizado)');s.value=selected;}
 function outs(selected=''){setOptions('l3out',[...new Set(data.l3outs.filter(o=>!$('tenant').value||o.tenant===$('tenant').value).map(o=>o.name))].sort(),selected);}
 function render(reset=true){if(reset)page=1;const tenant=$('tenant').value,out=$('l3out').value,q=$('query').value.trim().toLowerCase();
 const query=new URLSearchParams();for(const [k,v] of Object.entries({tenant,l3out:out,q}))if(v)query.set(k,v);history.replaceState(null,'','/l3out_explorer'+(query.size?'?'+query:''));
 $('l3Rows').replaceChildren();$('csv').hidden=true;if(!data){$('l3Count').textContent='';$('prev').disabled=$('next').disabled=true;return;}
 const groups=data.l3outs.filter(o=>(!tenant||o.tenant===tenant)&&(!out||o.name===out));
 const rows=data.rows.filter(r=>(!tenant||r.tenant===tenant)&&(!out||r.l3out===out)&&(!q||Object.values(r).join(' ').toLowerCase().includes(q)));
 const pages=Math.max(1,Math.ceil(rows.length/50));page=Math.min(page,pages);$('l3Count').textContent=groups.length+' L3Out(s) • '+rows.length+' registro(s) de prefixo';
 $('l3Empty').hidden=rows.length>0;$('l3Empty').textContent=q?'Nenhum prefixo corresponde à pesquisa.':groups.length?'L3Out(s) localizado(s), sem prefixos de External EPG retornados.':'Nenhum L3Out localizado para esta seleção.';
 for(const r of rows.slice((page-1)*50,page*50)){const tr=document.createElement('tr');for(const k of ['tenant','l3out','instp','ip','scope']){const td=document.createElement('td');td.textContent=r[k]||'—';tr.append(td);}$('l3Rows').append(tr);}
 $('csv').hidden=!rows.length;$('csv').href='/export_csv/l3out_selection?'+query;$('page').textContent='Página '+page+'/'+pages;$('prev').disabled=page===1;$('next').disabled=page===pages;
 }
 async function load(force=false){$('reload').disabled=true;$('l3Error').hidden=true;$('l3Status').textContent='Consultando tenants, L3Outs e prefixos…';
 const tenant=$('tenant').value||initial.get('tenant')||'',out=$('l3out').value||initial.get('l3out')||'';initial.delete('tenant');initial.delete('l3out');
 try{const r=await fetch('/api/l3out_inventory'+(force?'?refresh=1':''),{cache:'no-store'});const body=await r.json();if(!r.ok)throw Error(body.error||'Coleta indisponível.');data=body;setOptions('tenant',data.tenants,tenant);outs(out);
 const stamp=r.headers.get('X-Collected-At');$('l3Status').textContent='Coleta: '+(stamp?new Date(stamp).toLocaleString('pt-BR'):'indisponível');render();
 }catch(e){data=null;render();$('l3Empty').hidden=true;$('l3Status').textContent='Consulta não concluída.';$('l3Error').textContent=e.message;$('l3Error').hidden=false;}
 finally{$('reload').disabled=false;}}
 $('query').value=initial.get('q')||'';$('tenant').addEventListener('change',()=>{if(data){outs();render();}});$('l3out').addEventListener('change',()=>render());$('query').addEventListener('input',()=>render());$('l3Filters').addEventListener('submit',e=>{e.preventDefault();render();});$('reload').addEventListener('click',()=>load(true));$('clear').addEventListener('click',()=>{$('tenant').value='';$('query').value='';if(data)outs();render();});$('prev').addEventListener('click',()=>{page--;render(false);});$('next').addEventListener('click',()=>{page++;render(false);});load();
})();
