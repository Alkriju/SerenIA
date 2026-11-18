// Frontend real + backend real (bases en memoria): registro con casillas + captcha PoW + código + chat + exportar + borrar cuenta.
const { chromium } = require('playwright'); const B = 'http://127.0.0.1:8113'; const fails = [];
const ok = (c, m) => { console.log((c ? 'OK   ' : 'FAIL ') + m); if (!c) fails.push(m) };
const J = async (p, path) => (await p.request.get(B + path)).json();
(async () => {
  const br = await chromium.launch(); const ctx = await br.newContext({ viewport: { width: 1280, height: 800 }, acceptDownloads: true }); const page = await ctx.newPage();
  const errs = []; page.on('console', m => { if (m.type() === 'error' && !/Failed to load resource/.test(m.text())) errs.push(m.text()) }); page.on('pageerror', e => errs.push(e.message));
  await page.goto(B); await page.waitForSelector('#login:not([hidden])');
  await page.click('#swl'); await page.fill('#em', 'ana@uni.edu'); await page.fill('#pw', 'Clave-Segura-2026');
  await page.check('#r_terms'); await page.check('#r_sens'); await page.check('#r_ai');
  const t0 = Date.now(); await page.click('#go'); await page.waitForSelector('#cdw:not([hidden])', { timeout: 30000 });
  ok(true, 'registro con captcha PoW aceptado por el backend REAL (' + (Date.now() - t0) + ' ms)');
  const code = (await J(page, '/__code?email=ana@uni.edu')).code; ok(/^\d{6}$/.test(code), 'código generado');
  await page.fill('#cd', code); await page.click('#go'); await page.waitForSelector('#app:not([hidden])', { timeout: 10000 }); ok(true, 'verificación → app (cookie de sesión)');
  const me = await page.evaluate(() => fetch('/api/auth/me').then(r => r.json())); ok(me.email === 'ana@uni.edu' && me.consent_ok && me.ai_improve, 'GET /me: consentimiento vigente y mejora de IA activada');
  let s = await J(page, '/__state'); ok(s.consent.length === 3 && s.consent.every(c => c[1] === 1), 'registro de aceptación guardado: ' + JSON.stringify(s.consent));
  await page.waitForSelector('#survey:not([hidden])', { timeout: 8000 }).then(() => ok(true, 'aparece la encuesta diagnóstica inicial'), () => ok(false, 'no apareció la encuesta inicial')); await page.waitForTimeout(600); await page.locator('#survey button:has-text("Ahora no")').dispatchEvent('click');
  await page.evaluate(() => { if (!chatIsOpen()) openChat() }); await page.waitForTimeout(600); const inp = await page.$('#t'); if (inp) { await inp.fill('Hola, me siento estresada por el parcial'); await page.keyboard.press('Enter'); await page.waitForTimeout(1200); s = await J(page, '/__state'); ok(s.chat >= 1, 'el chat funciona con la sesión y la guarda (' + s.chat + ' mensajes)'); } else ok(false, 'no encontré el cuadro de chat');
  await page.click('.nv[data-v=prefs]'); await page.waitForSelector('#privcard');
  const [dl] = await Promise.all([page.waitForEvent('download'), page.click('#exp_btn, #privcard button:has-text("Descargar")')]); ok(dl.suggestedFilename() === 'mis-datos-serenia.json', 'exportar mis datos');
  const txt = require('fs').readFileSync(await dl.path(), 'utf8'); ok(txt.includes('estresada') && !txt.includes('SECRETO'), 'la exportación trae mis datos');
  await page.click('#privcard button:has-text("Eliminar")'); await page.waitForSelector('[role=dialog]'); await page.click('[role=dialog] button:has-text("Sí, eliminar")');
  await page.waitForSelector('#login:not([hidden])', { timeout: 10000 }); s = await J(page, '/__state');
  ok(s.credentials === 0 && s.chat === 0 && s.lake === 0, 'cuenta eliminada en todos los almacenes: ' + JSON.stringify({ c: s.credentials, chat: s.chat, lake: s.lake }));
  const me2 = await page.evaluate(() => fetch('/api/auth/me').then(r => r.status)); ok(me2 === 401, 'la sesión ya no sirve (401)');
  ok(errs.length === 0, 'sin errores JS: ' + errs.join(' | ')); await br.close(); console.log(fails.length ? 'FALLOS: ' + fails.length : 'E2E OK'); process.exit(fails.length ? 1 : 0);
})();
