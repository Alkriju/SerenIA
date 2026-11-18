/* Lee legal.json y completa los datos de la empresa, la versión y la tabla de proveedores.
   Los datos vacíos se ven resaltados como [COMPLETAR: …] para que no se publique nada a medias. */
(function(){
  var esc=function(s){return String(s==null?'':s).replace(/[&<>"']/g,function(c){return{'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]})};
  var todo=function(l){return '<mark class="todo">[COMPLETAR: '+esc(l)+']</mark>'};
  function get(o,p){return p.split('.').reduce(function(a,k){return a&&a[k]},o)}
  function toc(){
    var h=document.querySelectorAll('main h2'),box=document.getElementById('toc');if(!box||!h.length)return;
    var li='';h.forEach(function(e,i){if(!e.id)e.id='s'+(i+1);li+='<li><a href="#'+e.id+'">'+esc(e.textContent.replace(/^\d+\.\s*/,''))+'</a></li>'});
    box.innerHTML='<b>Contenido</b><ol>'+li+'</ol>';
  }
  function fill(L){
    document.querySelectorAll('[data-f]').forEach(function(e){
      var v=get(L,e.dataset.f),lab=e.dataset.l||e.dataset.f;
      if(!v){e.innerHTML=todo(lab);return}
      if(/email|dpo_email/.test(e.dataset.f))e.innerHTML='<a href="mailto:'+esc(v)+'">'+esc(v)+'</a>';
      else if(/website/.test(e.dataset.f))e.innerHTML='<a href="'+esc(v)+'" rel="noopener">'+esc(v)+'</a>';
      else e.textContent=v;
    });
    document.querySelectorAll('[data-v]').forEach(function(e){e.textContent=L.version});
    document.querySelectorAll('[data-days]').forEach(function(e){e.textContent=L.retention&&L.retention.backups_days||14});
    document.querySelectorAll('[data-consentlog]').forEach(function(e){var v=L.retention&&L.retention.consent_log;if(v)e.textContent=v;else e.innerHTML=todo('plazo, p. ej. 5 años, a confirmar con asesor legal')});
    document.querySelectorAll('.draft').forEach(function(e){e.hidden=!L.draft});
    var pv=document.getElementById('providers');
    if(pv){
      var rows=(L.providers||[]).filter(function(p){return p.active}).map(function(p){
        var n=p.name?esc(p.name)+(p.link?' <a href="'+esc(p.link)+'" target="_blank" rel="noopener">(política)</a>':''):todo('nombre del proveedor de hosting');
        return '<tr><td>'+n+'</td><td>'+(p.country?esc(p.country):todo('país del hosting'))+'</td><td>'+esc(p.purpose)+'</td><td>'+esc(p.data)+'</td></tr>'});
      pv.innerHTML='<table class="pv"><caption class="sr" style="position:absolute;left:-9999px">Proveedores que procesan datos</caption><thead><tr><th scope="col">Proveedor</th><th scope="col">País</th><th scope="col">Para qué</th><th scope="col">Qué datos recibe</th></tr></thead><tbody>'+rows.join('')+'</tbody></table>';
    }
    var off=document.getElementById('providers_off');
    if(off){var o=(L.providers||[]).filter(function(p){return !p.active}).map(function(p){return esc(p.name)+' ('+esc(p.country)+')'});off.textContent=o.length?o.join(', '):'ninguno'}
  }
  function start(L){fill(L||{version:'',draft:true,company:{},providers:[],retention:{}});toc()}
  fetch('/legal/legal.json',{cache:'no-cache'}).then(function(r){return r.json()}).then(start,function(){start(null)});
})();
