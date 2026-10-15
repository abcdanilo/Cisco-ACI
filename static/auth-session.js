/* No credentials or APIC tokens are exposed to the browser. */
(() => {
 'use strict';
 document.addEventListener('DOMContentLoaded',()=>{
  const bar=document.getElementById('aciSessionBar');
  if(bar)(document.querySelector('main, .page')||document.body).prepend(bar);
 });
 const original=window.fetch;
 window.fetch=async function(...args){
  const response=await original.apply(this,args);
  if(response.status===401&&new URL(response.url,location.href).origin===location.origin){
   location.replace('/login?'+new URLSearchParams({next:location.pathname+location.search}));
   throw Error('Sessão expirada. Entre novamente.');
  }
  return response;
 };
 window.addEventListener('pageshow',event=>{if(event.persisted)location.reload();});
})();
