(() => {
  'use strict';
  const $=id=>document.getElementById(id),dn=new URLSearchParams(location.search).get('dn')||'';
  const el=(tag,text,cls)=>{const e=document.createElement(tag);if(text!=null)e.textContent=text;if(cls)e.className=cls;return e;};
  const labels={adminSt:'Estado administrativo',speed:'Velocidade',autoNeg:'Autonegociação',mtu:'MTU',
    rxSt:'Recepção',txSt:'Transmissão',ctrl:'Controles',descr:'Descrição',tDn:'Objeto associado',state:'Estado da relação'};
  function values(data){const dl=el('dl',null,'properties');for(const [k,v] of Object.entries(data)){const d=el('div');d.append(el('dt',labels[k]||k),el('dd',String(v)));dl.append(d);}return dl;}
  async function load(force=false){
    window.dispatchEvent(new CustomEvent('object-selected',{detail:{dn,force}}));
    $('refresh').disabled=true;$('warning').hidden=true;$('status').textContent='Consultando políticas e perfis…';
    $('policies').replaceChildren();$('usage').replaceChildren();
    try{
      const r=await fetch('/api/access_group?'+new URLSearchParams({dn,...(force?{refresh:'1'}:{})}),{cache:'no-store'});
      const data=await r.json();if(!r.ok)throw Error(data.error||'Falha na consulta.');
      $('groupName').textContent=data.name;$('description').textContent=data.description;$('groupDn').textContent=data.dn;
      const date=r.headers.get('X-Collected-At');$('status').textContent='Coleta: '+(date?new Date(date).toLocaleString('pt-BR'):'indisponível');
      const warnings=JSON.parse(r.headers.get('X-Collection-Warnings')||'[]');$('warning').textContent=warnings.join('\n');$('warning').hidden=!warnings.length;
      for(const p of data.policies){const card=el('article',null,'panel');card.append(el('h3',p.label),el('p',(p.name||'Sem nome')+(p.default?' • Padrão':'')),el('p','Relação: '+p.state,'muted'),el('p',p.dn||'Sem destino informado','mono muted'));
        if(p.available){card.append(values(p.values));if(p.children.length){const more=el('details');more.append(el('summary','Relações e configurações adicionais'));for(const c of p.children){more.append(el('h4',c.class),values(c.values));}card.append(more);}}
        else card.append(el('p','Valores indisponíveis.','warning'));$('policies').append(card);}
      if(!data.policies.length)$('policies').append(el('p','Nenhuma relação de política retornada.','empty'));
      for(const u of data.usage){const card=el('article',null,'panel');card.append(el('h3',u.profile+' → '+u.selector),el('p',u.selector_dn,'mono muted'));
        for(const n of u.switch_profiles){card.append(el('h4','Perfil do switch: '+n.name),el('p',n.dn,'mono muted'),el('p','Relação com perfil de interfaces: '+n.states.join(', ')));
          for(const leaf of n.leaves)card.append(el('p','Seletor de switches '+leaf.name+': '+(leaf.ranges.map(r=>r.from===r.to?r.from:r.from+'–'+r.to).join(', ')||'intervalo não informado')));}
        if(!u.switch_profiles.length)card.append(el('p','Perfil de switch não localizado nas relações consultadas.','warning'));
        card.append(el('p','Relação seletor → Policy Group: '+u.relation_states.join(', ')));
        card.append(el('p','Portas configuradas: '+(u.ports.map(p=>'cartão '+p.fromCard+'–'+p.toCard+' / portas '+p.fromPort+'–'+p.toPort).join('; ')||'intervalos não informados')));
        card.append(el('p','Policy Group: '+data.name));$('usage').append(card);}
      if(!data.usage.length)$('usage').append(el('p','Nenhum seletor encontrado nas consultas disponíveis. Consulte os avisos de coleta antes de concluir que o grupo não é utilizado.','empty'));
    }catch(e){$('status').textContent='Consulta não concluída.';$('warning').textContent=e.message;$('warning').hidden=false;}
    finally{$('refresh').disabled=false;}
  }
  $('refresh').addEventListener('click',()=>load(true));load();
})();
