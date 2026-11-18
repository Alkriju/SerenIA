/* SerenIA · seguridad, privacidad y accesibilidad del cliente.
   Se carga ANTES del script principal. Contiene: verificación anti-bots (prueba de trabajo), consentimientos,
   banner de cookies, borrado/descarga de datos, diálogos accesibles y navegación por teclado. */
(function () {
  'use strict';
  var $ = function (i) { return document.getElementById(i); };
  var esc = function (s) { return String(s == null ? '' : s).replace(/[&<>"']/g, function (c) { return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]; }); };
  var st = {
    get: function (k) { try { return localStorage.getItem(k); } catch (e) { return null; } },
    set: function (k, v) { try { localStorage.setItem(k, v); } catch (e) {} },
    del: function (k) { try { localStorage.removeItem(k); } catch (e) {} }
  };
  var Sec = window.Sec = { state: { me: null } };

  /* ───────── Movimiento reducido: los canvas se actualizan muy despacio ───────── */
  if (window.matchMedia && matchMedia('(prefers-reduced-motion:reduce)').matches) {
    window.requestAnimationFrame = function (cb) { return setTimeout(function () { cb(performance.now()); }, 700); };
  }

  /* ───────── Red: 403 consent_required en cualquier servicio, y sesión vencida ───────── */
  var _fetch = window.fetch.bind(window), reloading = false;
  window.fetch = function (input, init) {
    return _fetch(input, init).then(function (r) {
      var url = typeof input === 'string' ? input : (input && input.url) || '';
      if (r.status === 403) {
        r.clone().json().then(function (d) { if (d && d.code === 'consent_required') Sec.consent(); }).catch(function () {});
      } else if (r.status === 401 && !reloading && /\/api\//.test(url) && !/\/api\/auth\/(signin|verify|register|challenge)/.test(url)) {
        var app = $('app'); if (app && !app.hidden) { reloading = true; location.reload(); }   // la sesión venció: volver al inicio de sesión
      }
      return r;
    });
  };
  function api(method, url, body) {
    return _fetch(url, { method: method, headers: body ? { 'Content-Type': 'application/json' } : {}, body: body ? JSON.stringify(body) : undefined, credentials: 'same-origin' })
      .then(function (r) { if (!r.ok) throw r; return r.status === 204 ? {} : r.json().catch(function () { return {}; }); });
  }
  Sec.api = api;
  /* Mensaje seguro para mostrar: solo el texto "detail" de errores 4xx; nunca detalles internos */
  Sec.errText = async function (x) {
    if (x && typeof x.status === 'number' && typeof x.json === 'function') {
      var d = null, s = x.status; try { d = await x.json(); } catch (e) {}
      if (s >= 400 && s < 500 && s !== 404 && d && typeof d.detail === 'string' && d.detail.length < 300) return d.detail;
      if (s === 429) return 'Demasiados intentos. Espera unos minutos e intenta de nuevo.';
      if (s === 400 || s === 422) return 'Revisa los datos ingresados e intenta de nuevo.';
      if (s === 401) return 'Correo o contraseña incorrectos.';
      if (s === 403) return 'No tienes permiso para realizar esta acción.';
    }
    if (x && x.name === 'TypeError') return 'No se pudo conectar. Revisa tu conexión e intenta de nuevo.';
    return 'Ocurrió un error. Intenta de nuevo en un momento.';
  };

  /* ───────── Verificación anti-bots: prueba de trabajo (sin servicios de terceros) ───────── */
  function leadingZeroBits(h, bits) {
    var full = bits >> 3, rest = bits & 7, i;
    for (i = 0; i < full; i++) if (h[i] !== 0) return false;
    return rest === 0 || (h[full] >> (8 - rest)) === 0;
  }
  Sec.pow = async function () {
    if (!(window.crypto && crypto.subtle)) throw new Error('nocrypto');
    var ch = await _fetch('/api/auth/challenge', { cache: 'no-store', credentials: 'same-origin' }).then(function (r) { if (!r.ok) throw r; return r.json(); });
    var enc = new TextEncoder(), n = 0, B = 256;
    for (;;) {
      var batch = [];
      for (var i = 0; i < B; i++) batch.push(crypto.subtle.digest('SHA-256', enc.encode(ch.salt + ':' + (n + i))));
      var res = await Promise.all(batch);
      for (var k = 0; k < B; k++) if (leadingZeroBits(new Uint8Array(res[k]), ch.bits)) return { id: ch.id, salt: ch.salt, bits: ch.bits, exp: ch.exp, sig: ch.sig, nonce: String(n + k) };
      n += B;
      if (ch.exp && Date.now() / 1000 > ch.exp) throw new Error('expired');
      await new Promise(function (r) { setTimeout(r, 0); });   // cede el hilo para que la página siga fluida
    }
  };

  /* ───────── Diálogos accesibles: foco atrapado, Esc, devolver el foco ───────── */
  var stack = [];
  function focusables(el) {
    return [].filter.call(el.querySelectorAll('a[href],button,input,select,textarea,[tabindex]'), function (e) {
      return e.tabIndex >= 0 && !e.disabled && e.getAttribute('aria-disabled') !== 'true' && e.getClientRects().length > 0;
    });
  }
  document.addEventListener('keydown', function (e) {
    var t = stack[stack.length - 1]; if (!t) return;
    if (e.key === 'Escape') { if (t.esc) { e.preventDefault(); t.esc(); } return; }
    if (e.key === 'Tab') {
      var f = focusables(t.el); if (!f.length) { e.preventDefault(); return; }
      var a = document.activeElement, i = f.indexOf(a);
      if (e.shiftKey) { if (i <= 0 || !t.el.contains(a)) { e.preventDefault(); f[f.length - 1].focus(); } }
      else if (i === f.length - 1 || !t.el.contains(a)) { e.preventDefault(); f[0].focus(); }
    }
  }, true);
  function openDialog(el, o) {
    o = o || {}; var t = { el: el, esc: o.esc, opener: document.activeElement };
    stack.push(t);
    setTimeout(function () {
      var f = o.initial ? el.querySelector(o.initial) : null;
      if (!f || f.getClientRects().length === 0) f = focusables(el)[0];
      if (f) f.focus();
    }, 0);
    return function release() {
      var i = stack.indexOf(t); if (i > -1) stack.splice(i, 1);
      var op = t.opener;
      try { if (op && document.contains(op) && op.getClientRects().length) op.focus(); else if ($('main')) $('main').focus(); } catch (e) {}
    };
  }
  function dlg(id, title, html, o) {
    o = o || {};
    var ov = document.createElement('div'); ov.className = 'ov sec'; ov.id = id;
    ov.innerHTML = '<div class="md" role="dialog" aria-modal="true" aria-labelledby="' + id + '_t"><div class="hd"><div><h2 id="' + id + '_t">' + esc(title) + '</h2></div>' +
      (o.closable ? '<button type="button" class="x" data-x aria-label="Cerrar"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" aria-hidden="true"><path d="M6 6l12 12M18 6 6 18"/></svg></button>' : '') + '</div>' + html + '</div>';
    document.body.append(ov);
    var rel = openDialog(ov, { esc: o.closable ? close : null, initial: o.initial });
    function close() { rel(); ov.remove(); }
    ov.close = close;
    var x = ov.querySelector('[data-x]'); if (x) x.onclick = close;
    return ov;
  }
  /* Diálogos que ya existen en la página (juego, encuesta): se vigilan por su atributo hidden */
  function watch(id, escFn, initial) {
    var el = $(id); if (!el) return; var rel = null;
    new MutationObserver(function () {
      if (!el.hidden && !rel) rel = openDialog(el, { esc: escFn, initial: initial });
      else if (el.hidden && rel) { rel(); rel = null; }
    }).observe(el, { attributes: true, attributeFilter: ['hidden'] });
  }

  /* ───────── Datos legales (contacto) y enlaces al pie ───────── */
  var LEGAL = null;
  function legal() { if (!LEGAL) LEGAL = _fetch('/legal/legal.json').then(function (r) { return r.json(); }).catch(function () { return { company: {} }; }); return LEGAL; }
  function linksHtml() {
    return '<a href="/legal/terminos.html" target="_blank" rel="noopener">Términos</a><a href="/legal/privacidad.html" target="_blank" rel="noopener">Privacidad</a>' +
      '<a href="/legal/cookies.html" target="_blank" rel="noopener">Cookies</a><a href="/legal/derechos-autor.html" target="_blank" rel="noopener">Derechos de autor</a>' +
      '<a class="lcontact" href="/legal/privacidad.html#s1" target="_blank" rel="noopener">Contacto</a><button type="button" class="linklike" data-cc>Preferencias de cookies</button>';
  }
  function paintLinks() {
    document.querySelectorAll('.legal-links').forEach(function (n) { n.innerHTML = linksHtml(); });
    legal().then(function (L) {
      var m = L && L.company && L.company.email_general;
      if (m) document.querySelectorAll('.lcontact').forEach(function (a) { a.href = 'mailto:' + m; a.removeAttribute('target'); });
    });
  }
  document.addEventListener('click', function (e) {
    var b = e.target.closest && e.target.closest('[data-cc]'); if (b) { e.preventDefault(); openPrefs(); }
  });

  /* ───────── Cookies ─────────
     Hoy SerenIA NO usa analítica, publicidad ni rastreadores: solo lo necesario (cookie de sesión `t` y localStorage).
     Cómo registrar un servicio opcional en el futuro (nada debe cargarse antes del permiso):

       Consent.onAllow('analytics', function () {
         var s = document.createElement('script'); s.src = 'https://…/sdk.js'; s.async = true; document.head.append(s);
       });

     La función solo se ejecuta si la persona aceptó esa categoría ('analytics' o 'marketing'), ya sea ahora o en una visita anterior.
     Si la persona retira el permiso, la página se recarga para que lo ya cargado desaparezca. No agregues <script> de terceros directamente en el HTML. */
  var CK = 'cc', waiting = [];
  function readCC() { try { var c = JSON.parse(st.get(CK)); return c && c.v === 1 ? c : null; } catch (e) { return null; } }
  function runWaiting() {
    var c = readCC();
    waiting = waiting.filter(function (w) { if (c && c[w.cat]) { try { w.fn(); } catch (e) {} return false; } return true; });
  }
  function saveCC(a, m) {
    var prev = readCC(), c = { v: 1, ts: Date.now(), analytics: !!a, marketing: !!m };
    st.set(CK, JSON.stringify(c));
    if (prev && ((prev.analytics && !c.analytics) || (prev.marketing && !c.marketing))) { location.reload(); return; }
    runWaiting(); hideBanner();
  }
  window.Consent = {
    get: readCC,
    allowed: function (cat) { var c = readCC(); return !!(c && c[cat]); },
    onAllow: function (cat, fn) { if (cat !== 'analytics' && cat !== 'marketing') return; if (this.allowed(cat)) { try { fn(); } catch (e) {} } else waiting.push({ cat: cat, fn: fn }); },
    open: function () { openPrefs(); }
  };
  function hideBanner() { var b = $('ccb'); if (b) b.hidden = true; }
  function buildBanner() {
    var d = document.createElement('div'); d.id = 'ccb'; d.className = 'ccb'; d.hidden = true;
    d.setAttribute('role', 'dialog'); d.setAttribute('aria-modal', 'false'); d.setAttribute('aria-labelledby', 'cct'); d.setAttribute('aria-describedby', 'ccd');
    d.innerHTML = '<div class="cct"><b id="cct">Tu privacidad, tu decisión</b><p id="ccd">Usamos solo las cookies y el almacenamiento necesarios para que SerenIA funcione (por ejemplo, mantener tu sesión). No usamos analítica ni publicidad, y no cargaremos rastreadores sin tu permiso. <a href="/legal/cookies.html" target="_blank" rel="noopener">Más información</a></p></div>' +
      '<div class="cca"><button type="button" class="btn" id="cc_n">Solo necesarias</button><button type="button" class="btn" id="cc_c">Personalizar</button><button type="button" class="btn pri" id="cc_a">Aceptar todas</button></div>';
    var sk = $('skip'); document.body.insertBefore(d, sk ? sk.nextSibling : document.body.firstChild);
    $('cc_n').onclick = function () { saveCC(false, false); };
    $('cc_a').onclick = function () { saveCC(true, true); };
    $('cc_c').onclick = function () { openPrefs(); };
    if (!readCC()) d.hidden = false;
  }
  function openPrefs() {
    if ($('ccp')) return;
    var c = readCC() || { analytics: false, marketing: false };
    var row = function (id, t, d, on, dis) {
      return '<div class="ccrow"><div><b id="' + id + '_l">' + t + '</b><small id="' + id + '_d">' + d + '</small></div><button type="button" class="swt" id="' + id + '" role="switch" aria-checked="' + on + '" aria-labelledby="' + id + '_l" aria-describedby="' + id + '_d"' + (dis ? ' aria-disabled="true"' : '') + '><i></i></button></div>';
    };
    var ov = dlg('ccp', 'Preferencias de cookies',
      '<p class="cmtxt">Elige qué puede guardar SerenIA en tu navegador. Más detalles en la <a href="/legal/cookies.html" target="_blank" rel="noopener" style="color:var(--p2);font-weight:600">Política de Cookies</a>.</p>' +
      row('cc_t_nec', 'Necesarias', 'Mantienen tu sesión y recuerdan estas preferencias. Siempre activas.', true, true) +
      row('cc_t_an', 'Analítica', 'Medir el uso de la app. Hoy no usamos ninguna herramienta de analítica.', !!c.analytics, false) +
      row('cc_t_mk', 'Marketing y terceros', 'Publicidad y rastreo de terceros. Hoy no usamos ninguno.', !!c.marketing, false) +
      '<div class="acts end"><button type="button" class="btn" id="cc_p_n">Solo necesarias</button><button type="button" class="btn pri" id="cc_p_s">Guardar mi elección</button></div>',
      { closable: true });
    ov.querySelectorAll('.swt:not([aria-disabled])').forEach(function (b) { b.onclick = function () { b.setAttribute('aria-checked', b.getAttribute('aria-checked') === 'true' ? 'false' : 'true'); }; });
    var on = function (id) { return $(id).getAttribute('aria-checked') === 'true'; };
    $('cc_p_s').onclick = function () { saveCC(on('cc_t_an'), on('cc_t_mk')); ov.close(); };
    $('cc_p_n').onclick = function () { saveCC(false, false); ov.close(); };
  }

  /* ───────── Casillas de consentimiento (registro y compuerta) ───────── */
  Sec.consentFields = function (box, p) {
    box.innerHTML =
      '<label class="ck"><input type="checkbox" id="' + p + '_terms" required aria-required="true"><span>Soy mayor de 18 años y acepto los <a href="/legal/terminos.html" target="_blank" rel="noopener">Términos y Condiciones</a> y la <a href="/legal/privacidad.html" target="_blank" rel="noopener">Política de Privacidad</a>. <b class="req">(obligatorio)</b></span></label>' +
      '<label class="ck"><input type="checkbox" id="' + p + '_sens" required aria-required="true"><span>Autorizo de forma expresa el tratamiento de mis datos sensibles (estado emocional y de salud mental) y su procesamiento por los <a href="/legal/terminos.html#proveedores" target="_blank" rel="noopener">proveedores de IA listados</a>, para prestar el servicio. <b class="req">(obligatorio)</b></span></label>' +
      '<label class="ck"><input type="checkbox" id="' + p + '_ai"><span>Permito que mis datos se usen de forma seudonimizada para mejorar la calidad de la IA (puedo retirarlo cuando quiera). <b class="opt">(opcional)</b></span></label>';
  };
  var reqOk = function (p) { return !!($(p + '_terms') && $(p + '_terms').checked && $(p + '_sens') && $(p + '_sens').checked); };
  Sec.consentOk = reqOk;
  Sec.syncGo = function () {   // el botón de registro se activa solo con las dos casillas obligatorias
    var go = $('go'); if (!go) return;
    var reg = Sec.mode === 'reg', verifying = $('cdw') && !$('cdw').hidden;
    go.disabled = !!(reg && !verifying && !reqOk('r'));
  };

  /* Compuerta: personas que aún no aceptaron la versión vigente (Microsoft, o cambio de términos) */
  Sec.consent = function (me) {
    if ($('cm')) return;
    var ov = dlg('cm', 'Antes de continuar',
      '<p class="cmtxt">Para usar SerenIA necesitamos tu autorización. Puedes leer los documentos antes de aceptar.</p><div class="consents" id="m_box"></div><p id="m_msg" class="cmtxt" role="status" aria-live="polite" style="color:var(--danger);min-height:20px;margin:10px 0 0"></p>' +
      '<div class="acts end"><button type="button" class="btn" id="m_out">Cerrar sesión</button><button type="button" class="btn pri" id="m_ok" disabled>Aceptar y continuar</button></div>',
      { closable: false, initial: '#m_terms' });
    Sec.consentFields($('m_box'), 'm');
    var sync = function () { $('m_ok').disabled = !reqOk('m'); };
    $('m_box').addEventListener('change', sync);
    $('m_out').onclick = function () { if (window.logout) window.logout(); else location.reload(); };
    $('m_ok').onclick = function () {
      $('m_ok').disabled = true; $('m_msg').textContent = '';
      api('POST', '/api/auth/consent', { accept_terms: true, accept_sensitive: true, ai_improve: $('m_ai').checked })
        .then(function () { ov.close(); if (window.init) window.init(); })
        .catch(function (x) { Sec.errText(x).then(function (t) { $('m_msg').textContent = t; sync(); }); });
    };
  };

  /* ───────── Privacidad y datos (Personalizar) ───────── */
  function say(t) { var n = $('priv_ok'); if (n) n.textContent = t; }
  function paintAi(on) { var s = $('ai_sw'); if (s) s.setAttribute('aria-checked', on ? 'true' : 'false'); }
  Sec.afterInit = function (me) { Sec.state.me = me; paintAi(!!(me && me.ai_improve)); };
  function wirePrivacy() {
    var s = $('ai_sw'); if (!s) return;
    s.onclick = function () {
      var want = s.getAttribute('aria-checked') !== 'true'; paintAi(want); say('Guardando…');
      api('POST', '/api/auth/consent/ai', { ai_improve: want })
        .then(function () { say(want ? 'Listo: usaremos tus datos de forma seudonimizada para mejorar la IA.' : 'Listo: dejamos de usar tus datos para mejorar la IA.'); if (Sec.state.me) Sec.state.me.ai_improve = want; })
        .catch(function (x) { paintAi(!want); Sec.errText(x).then(say); });
    };
    $('btn_export').onclick = async function () {
      say('Preparando tu archivo…');
      try {
        var r = await _fetch('/api/auth/export', { credentials: 'same-origin' }); if (!r.ok) throw r;
        var b = await r.blob(), a = document.createElement('a'); a.href = URL.createObjectURL(b); a.download = 'mis-datos-serenia.json';
        document.body.append(a); a.click(); setTimeout(function () { URL.revokeObjectURL(a.href); a.remove(); }, 1500);
        say('Listo: se descargó tu archivo mis-datos-serenia.json.');
      } catch (x) { say(await Sec.errText(x)); }
    };
    $('btn_del').onclick = confirmDelete;
  }
  function confirmDelete() {
    if ($('cd_dlg')) return;
    var ov = dlg('cd_dlg', '¿Eliminar tu cuenta?',
      '<p class="cmtxt"><b style="color:var(--t)">Se borrarán todos tus datos de forma inmediata e irreversible</b>: conversaciones, encuestas, juegos, preferencias y perfil. No podremos recuperarlos.</p>' +
      '<p id="cd_msg" class="cmtxt" role="status" aria-live="polite" style="color:var(--danger);min-height:20px;margin:6px 0 0"></p>' +
      '<div class="acts end"><button type="button" class="btn" id="cd_no" data-cancel>Cancelar</button><button type="button" class="btn dangerx" id="cd_yes">Sí, eliminar mi cuenta</button></div>',
      { closable: true, initial: '[data-cancel]' });
    $('cd_no').onclick = function () { ov.close(); };
    $('cd_yes').onclick = function () {
      $('cd_yes').disabled = true; $('cd_msg').textContent = 'Eliminando…';
      api('POST', '/api/auth/account/delete', { confirm: true }).then(function () {
        ['last', 'mute', 'vol'].forEach(st.del); try { speechSynthesis.cancel(); } catch (e) {}
        location.reload();
      }).catch(function (x) { Sec.errText(x).then(function (t) { $('cd_msg').textContent = t; $('cd_yes').disabled = false; }); });
    };
  }

  /* ───────── Teclado y lectores de pantalla ───────── */
  var BAD = /^(BUTTON|INPUT|SELECT|TEXTAREA|SUMMARY|LABEL|OPTION)$/;
  function kd(e) {
    if (e.target !== this) return;   // si la tecla viene de un botón interno, no se duplica
    if (e.key === 'Enter' || e.key === ' ' || e.key === 'Spacebar') { e.preventDefault(); this.dispatchEvent(new MouseEvent('click', { bubbles: true, cancelable: true, view: window })); }
  }
  function enhance(root) {
    if (!root || root.nodeType !== 1) return;
    var list = []; if (root.matches && root.matches('[onclick]')) list.push(root);
    list.push.apply(list, root.querySelectorAll('[onclick]'));
    list.forEach(function (e) {
      if (BAD.test(e.tagName) || (e.tagName === 'A' && e.hasAttribute('href')) || e.dataset.enh) return;
      e.dataset.enh = '1';
      if (!e.hasAttribute('tabindex')) e.setAttribute('tabindex', '0');
      if (!e.hasAttribute('role')) e.setAttribute('role', 'button');
      if (!e.getAttribute('aria-label') && !(e.textContent || '').trim() && e.title) e.setAttribute('aria-label', e.title);
      e.addEventListener('keydown', kd);
    });
    root.querySelectorAll('#bz [data-z]').forEach(function (p) {   // zonas del cuerpo (SVG)
      if (p.dataset.enh) return; p.dataset.enh = '1';
      p.setAttribute('tabindex', '0'); p.setAttribute('role', 'button'); p.setAttribute('aria-label', 'Zona ' + p.dataset.z + ': Enter o espacio para cambiar la intensidad');
      p.addEventListener('keydown', kd);
    });
    root.querySelectorAll('button.bb').forEach(function (b) { if (!b.getAttribute('aria-label')) b.setAttribute('aria-label', 'Burbuja: Enter para explotarla'); });
    root.querySelectorAll('button').forEach(function (b) {
      if (!b.getAttribute('aria-label') && !(b.textContent || '').trim() && !b.querySelector('[aria-label]') && b.title) b.setAttribute('aria-label', b.title);
    });
  }
  var syncT = null;
  function syncAria() {
    clearTimeout(syncT);
    syncT = setTimeout(function () {
      document.querySelectorAll('.nv').forEach(function (b) { if (b.classList.contains('on')) b.setAttribute('aria-current', 'page'); else b.removeAttribute('aria-current'); });
      document.querySelectorAll('[role=tab]').forEach(function (b) { b.setAttribute('aria-selected', b.classList.contains('on') ? 'true' : 'false'); });
      document.querySelectorAll('.chips button,.sc button,.vc,.ts').forEach(function (b) { b.setAttribute('aria-pressed', (b.classList.contains('on') || b.classList.contains('ok')) ? 'true' : 'false'); });
    }, 40);
  }
  Sec.syncAria = syncAria;

  function skipLink() {
    var a = document.createElement('a'); a.id = 'skip'; a.className = 'skip'; a.href = '#main'; a.textContent = 'Saltar al contenido';
    a.addEventListener('click', function (e) {
      e.preventDefault();
      var t = ($('login') && !$('login').hidden) ? $('lh') : $('main'); if (t) { t.setAttribute('tabindex', '-1'); t.focus(); }
    });
    document.body.insertBefore(a, document.body.firstChild);
  }

  function ready(fn) { if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', fn); else fn(); }
  ready(function () {
    skipLink(); buildBanner(); paintLinks();
    var rx = $('regx'); if (rx) Sec.consentFields(rx, 'r');
    if (rx) rx.addEventListener('change', Sec.syncGo);
    wirePrivacy(); Sec.syncGo();
    watch('game', function () { if (window.closeGame) window.closeGame(); }, '#gb button,#gb input,#gb textarea,#gb [tabindex="0"]');
    watch('survey', function () { if (window.closeSurvey) window.closeSurvey(); }, '#sf button,#sf input,#sf textarea');
    enhance(document.body); syncAria(); runWaiting();
    new MutationObserver(function (ms) {
      ms.forEach(function (m) { m.addedNodes.forEach(enhance); });
      syncAria();
    }).observe(document.body, { childList: true, subtree: true, attributes: true, attributeFilter: ['class'] });
  });
})();
