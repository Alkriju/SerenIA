# Capa de IA multi-proveedor: rota entre varias API keys y cae al siguiente proveedor si una se agota.
#   Orden por defecto: Gemini (N keys) -> GitHub Models -> Cohere -> Anthropic (opcional)
#   Cada llamada empieza por una key distinta (round-robin) para repartir el gasto de cuota.
#   Si una key da 429 (cuota), 401/403 (inválida) o 5xx, entra en "enfriamiento" y se salta un rato.
import os, re, time, threading, httpx
E = os.environ

class LLMError(Exception): pass

LIMIT = {"gemini": 90000, "github": 22000, "cohere": 60000, "anthropic": 90000}  # caracteres de contexto que se envían a cada proveedor
NAMES = {"gemini": "GEMINI_API_KEYS", "github": "GITHUB_MODELS_TOKENS", "cohere": "COHERE_API_KEYS", "anthropic": "ANTHROPIC_API_KEY"}
_cool, _rr, _lock = {}, {}, threading.Lock()

def keys(p):  # acepta varias keys separadas por coma, punto y coma, espacio o salto de línea
    v = E.get(NAMES[p], "")
    if p == "gemini" and not v: v = E.get("GEMINI_API_KEY", "")
    return [k for k in re.split(r"[,;\s]+", v) if k and not k.endswith("...")]
def order(): return [p for p in re.split(r"[,\s]+", E.get("LLM_ORDER", "gemini,github,cohere,anthropic")) if p in LIMIT]
def available(o=None): return any(keys(p) for p in (o or order()))
def status():
    now = time.time()
    return {p: {"keys": len(keys(p)), "en_pausa": sum(1 for k in keys(p) if _cool.get((p, k[-8:]), 0) > now)} for p in order()}

def _norm(msgs):  # une turnos seguidos del mismo rol y asegura que el primero sea del usuario
    out = []
    for m in msgs:
        t = (m.get("content") or "").strip()
        if not t: continue
        if out and out[-1]["role"] == m["role"]: out[-1]["content"] += "\n" + t
        else: out.append({"role": m["role"], "content": t})
    while out and out[0]["role"] != "user": out.pop(0)
    return out
def _fit(system, msgs, limit):  # recorta lo más antiguo para respetar el límite de cada proveedor (GitHub Models free es el más estricto)
    system = system[: int(limit * 0.6)]
    room, used, out = limit - len(system), 0, []
    for m in reversed(msgs):
        if out and used + len(m["content"]) > room: break
        out.append(m); used += len(m["content"])
    return system, _norm(out[::-1])

class Budget(Exception): pass
_tl = threading.local()
def _left(): return (getattr(_tl, "dl", 0) - time.time()) if getattr(_tl, "dl", 0) else 20
def _post(url, headers, body, timeout=None):  # cada intento tiene tope propio y TODA la respuesta tiene un presupuesto total (LLM_BUDGET, 35 s por defecto)
    left = _left()
    if left <= 1: raise Budget()
    r = httpx.post(url, headers=headers, json=body, timeout=httpx.Timeout(min(float(E.get("LLM_TIMEOUT", "25")), left), connect=5)); r.raise_for_status(); return r.json()
_mcool = {}
def gemini_models(): return [m for m in re.split(r"[,\s]+", E.get("GEMINI_MODEL", "gemini-3.6-flash,gemini-3.5-flash-lite,gemini-3.1-flash-lite")) if m]
def _gemini_call(k, body):  # cada modelo tiene su propia cuota: si uno se agota (429) con esta key, prueba el siguiente modelo
    last = None
    for mdl in gemini_models():
        if _mcool.get((k[-8:], mdl), 0) > time.time(): continue
        try:
            j = _post(f"https://generativelanguage.googleapis.com/v1beta/models/{mdl}:generateContent", {"x-goog-api-key": k}, body)
        except httpx.TimeoutException as e:  # modelo lento: prueba el siguiente modelo de la lista en vez de rendirse
            last = e; _mcool[(k[-8:], mdl)] = time.time() + 30; print(f"[llm] gemini {mdl} timeout", flush=True); continue
        except httpx.HTTPStatusError as e:
            c = e.response.status_code; last = e
            if c in (429, 404, 500, 503): _mcool[(k[-8:], mdl)] = time.time() + (90 if c == 429 else 60); print(f"[llm] gemini {mdl} HTTP {c}: {e.response.text[:120]}", flush=True); continue
            raise
        parts = ((j.get("candidates") or [{}])[0].get("content") or {}).get("parts") or []
        out = "".join(p.get("text", "") for p in parts).strip()
        if out: return out
    if last: raise last
    return ""
def _gemini(k, system, msgs, mt, temp):
    return _gemini_call(k, {"systemInstruction": {"parts": [{"text": system}]},
        "contents": [{"role": "model" if m["role"] == "assistant" else "user", "parts": [{"text": m["content"]}]} for m in msgs],
        "generationConfig": {"maxOutputTokens": max(mt, 1024), "temperature": temp, **({"thinkingConfig": {"thinkingLevel": E["GEMINI_THINKING_LEVEL"]}} if E.get("GEMINI_THINKING_LEVEL") else {})}})  # los modelos con "thinking" gastan parte del límite pensando
def _github(k, system, msgs, mt, temp):
    j = _post("https://models.github.ai/inference/chat/completions", {"Authorization": f"Bearer {k}", "Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"},
        {"model": E.get("GITHUB_MODEL", "openai/gpt-4.1-mini"), "messages": [{"role": "system", "content": system}] + msgs, "max_tokens": mt, "temperature": temp})
    return (j["choices"][0]["message"]["content"] or "").strip()
def _cohere(k, system, msgs, mt, temp):
    j = _post("https://api.cohere.com/v2/chat", {"Authorization": f"Bearer {k}"},
        {"model": E.get("COHERE_MODEL", "command-a-03-2025"), "messages": [{"role": "system", "content": system}] + msgs, "max_tokens": mt, "temperature": temp})
    return "".join(c.get("text", "") for c in j["message"]["content"] if c.get("type", "text") == "text").strip()
def _anthropic(k, system, msgs, mt, temp):
    j = _post("https://api.anthropic.com/v1/messages", {"x-api-key": k, "anthropic-version": "2023-06-01"},
        {"model": E.get("MODEL", "claude-sonnet-4-6"), "max_tokens": mt, "temperature": temp, "system": system, "messages": msgs})
    return "".join(c.get("text", "") for c in j["content"]).strip()
CALL = {"gemini": _gemini, "github": _github, "cohere": _cohere, "anthropic": _anthropic}
# --- Proveedores con API tipo OpenAI: groq, openai (GPT), deepseek, qwen. Varias keys por coma, igual que Gemini. ---
OAI = {"groq": "https://api.groq.com/openai/v1", "openai": "https://api.openai.com/v1", "deepseek": "https://api.deepseek.com",
       "qwen": "https://dashscope-intl.aliyuncs.com/compatible-mode/v1"}   # cada URL se puede cambiar con <PROVEEDOR>_BASE_URL
OAI_MODEL = {"groq": "llama-3.3-70b-versatile,openai/gpt-oss-20b", "openai": "gpt-4.1-mini", "deepseek": "deepseek-v4-flash,deepseek-v4-pro", "qwen": "qwen-plus"}  # cambiables con <PROVEEDOR>_MODEL
LIMIT.update({"groq": 20000, "openai": 90000, "deepseek": 90000, "qwen": 90000})
NAMES.update({p: p.upper() + "_API_KEYS" for p in OAI})
import json as _json
def _oai(p):
    def f(k, system, msgs, mt, temp):
        u = E.get(p.upper() + "_BASE_URL", OAI[p]).rstrip("/") + "/chat/completions"
        ex = _json.loads(E.get(p.upper() + "_EXTRA", "") or "{}"); last = None   # <P>_EXTRA: JSON extra para el cuerpo (ej. desactivar thinking)
        for m in [x.strip() for x in E.get(p.upper() + "_MODEL", OAI_MODEL[p]).split(",") if x.strip()]:
            for extra in ([ex, {}] if ex else [{}]):
                try:
                    j = _post(u, {"Authorization": f"Bearer {k}"}, {"model": m, "messages": [{"role": "system", "content": system}] + msgs,
                                                                  "max_tokens": mt, "temperature": temp, **extra})
                    return (j["choices"][0]["message"]["content"] or "").strip()
                except httpx.HTTPStatusError as e:
                    last = e
                    if e.response.status_code not in (400, 404): raise
        raise last
    return f
CALL.update({p: _oai(p) for p in OAI})

def _pause(code): return 3600 if code in (401, 403) else 60 if code == 404 else 60 if code == 429 else 20 if code >= 500 else 0
def _run(p, fn, errs):  # prueba las keys de un proveedor empezando por una distinta cada vez
    ks = keys(p)
    if not ks: return None
    with _lock: start = _rr.get(p, 0); _rr[p] = start + 1
    for i in range(len(ks)):
        idx = (start + i) % len(ks); k = ks[idx]; sid = (p, k[-8:])
        if _cool.get(sid, 0) > time.time(): continue
        try:
            out = fn(k)
            if out: return out, f"{p}#{idx + 1}"
            errs.append(f"{p}#{idx + 1}: respuesta vacía")
        except Budget: errs.append(f"{p}: sin tiempo"); return None
        except httpx.HTTPStatusError as e:
            c = e.response.status_code; _cool[sid] = time.time() + _pause(c); errs.append(f"{p}#{idx + 1}: HTTP {c}")
            print(f"[llm] {p}#{idx + 1} HTTP {c}: {e.response.text[:160]}", flush=True)
        except Exception as e:
            _cool[sid] = time.time() + 20; errs.append(f"{p}#{idx + 1}: {type(e).__name__}"); print(f"[llm] {p}#{idx + 1} {type(e).__name__}: {e}", flush=True)
    return None

def generate(system, messages, max_tokens=600, temperature=0.7, order_=None):
    """Devuelve (texto, 'proveedor#n'). Lanza LLMError si TODAS las keys/proveedores fallan."""
    msgs, errs = _norm(messages), []
    if not msgs: raise LLMError("sin mensajes")
    _tl.dl = time.time() + float(E.get("LLM_BUDGET", "35"))
    try:
        for p in (order_ or order()):
            if _left() <= 1: break
            s, m = _fit(system, msgs, LIMIT[p])
            r = _run(p, lambda k: CALL[p](k, s, m, max_tokens, temperature), errs)
            if r: return r
    finally: _tl.dl = 0
    raise LLMError("; ".join(errs) or "No hay API keys configuradas (revisa .env)")

def transcribe(b64, mime="audio/wav"):  # solo Gemini entiende audio; se usa como respaldo si el navegador no trae reconocimiento de voz
    body = {"contents": [{"role": "user", "parts": [{"inlineData": {"mimeType": mime, "data": b64}},
            {"text": "Transcribe literalmente este audio en español. Devuelve solo el texto dicho, sin comillas ni comentarios."}]}], "generationConfig": {"temperature": 0}}
    errs = []; _tl.dl = time.time() + 25
    try: r = _run("gemini", lambda k: _gemini_call(k, body), errs)
    finally: _tl.dl = 0
    if r: return r[0]
    raise LLMError("; ".join(errs) or "sin keys de Gemini")

def diagnose():
    """Prueba cada key con una petición mínima y dice qué pasa (sin mostrar las keys). Limpia las pausas."""
    _cool.clear(); _mcool.clear(); out = []
    for p in order():
        ks = keys(p)
        if not ks: out.append({"proveedor": p, "estado": "SIN KEYS en .env"}); continue
        for i, k in enumerate(ks):
            try:
                if p == "gemini":
                    for mdl in gemini_models():
                        try:
                            _post(f"https://generativelanguage.googleapis.com/v1beta/models/{mdl}:generateContent", {"x-goog-api-key": k}, {"contents": [{"role": "user", "parts": [{"text": "di ok"}]}], "generationConfig": {"maxOutputTokens": 64}})
                            out.append({"proveedor": f"gemini#{i + 1}", "modelo": mdl, "estado": "OK"})
                        except httpx.HTTPStatusError as e:
                            out.append({"proveedor": f"gemini#{i + 1}", "modelo": mdl, "estado": f"ERROR HTTP {e.response.status_code}", "detalle": e.response.text[:200]})
                else:
                    t = CALL[p](k, "Responde solo: ok", [{"role": "user", "content": "di ok"}], 32, 0)
                    out.append({"proveedor": f"{p}#{i + 1}", "estado": "OK" if t else "respuesta vacía"})
            except httpx.HTTPStatusError as e: out.append({"proveedor": f"{p}#{i + 1}", "estado": f"ERROR HTTP {e.response.status_code}", "detalle": e.response.text[:200]})
            except Exception as e: out.append({"proveedor": f"{p}#{i + 1}", "estado": f"ERROR {type(e).__name__}", "detalle": str(e)[:200]})
    return out

# ---------- Voz natural (Gemini TTS) ----------
import base64, struct
TTS_MODELS = lambda: [m for m in re.split(r"[,\s]+", E.get("GEMINI_TTS_MODEL", "gemini-3.8-flash-tts,gemini-3.1-flash-tts-preview,gemini-2.5-flash-preview-tts")) if m]
_tcool = {}
def _wav(pcm, sr=24000): return b"RIFF" + struct.pack("<I", 36 + len(pcm)) + b"WAVEfmt " + struct.pack("<IHHIIHH", 16, 1, 1, sr, sr * 2, 2, 16) + b"data" + struct.pack("<I", len(pcm)) + pcm
_tts_ok = {}   # modelo -> (forma, con_estilo) que ya funcionó: así no se repiten intentos fallidos en cada respuesta (menos espera)
def _tts_gemini(k, text, voice):
    style = E.get("TTS_STYLE", "Habla en español colombiano, de forma natural, cálida y cercana, como un amigo que te habla tranquilo; sin sonar robótico.")
    shapes = [{"voiceConfig": {"prebuiltVoiceConfig": {"voiceName": voice}}}, {"voiceConfig": {"voice": voice}}]
    last = None
    for mdl in TTS_MODELS():
        if _tcool.get((k[-8:], mdl), 0) > time.time(): continue
        combos = [(si, meta) for si in (0, 1) for meta in (True, False)]
        if mdl in _tts_ok: combos = [_tts_ok[mdl]] + [c for c in combos if c != _tts_ok[mdl]]
        for si, meta in combos:
            part = {"text": text, **({"speech_metadata": {"style": style}} if meta else {})}
            try:
                j = _post(f"https://generativelanguage.googleapis.com/v1beta/models/{mdl}:generateContent", {"x-goog-api-key": k},
                          {"contents": [{"role": "user", "parts": [part]}], "generationConfig": {"responseModalities": ["AUDIO"], "speechConfig": shapes[si]}})
                for p_ in ((j.get("candidates") or [{}])[0].get("content") or {}).get("parts") or []:
                    d = (p_.get("inlineData") or {}).get("data")
                    if d:
                        _tts_ok[mdl] = (si, meta); raw_ = base64.b64decode(d); return base64.b64encode(raw_ if raw_[:4] == b"RIFF" else _wav(raw_)).decode()
            except httpx.HTTPStatusError as e:
                last = e; c = e.response.status_code
                if c == 400: continue            # forma no aceptada por este modelo: prueba la siguiente
                if c in (404, 429, 500, 503): _tcool[(k[-8:], mdl)] = time.time() + 60; break
                raise
    if last: raise last
    return ""
def _tts_openai(k, text, voice):  # voces de OpenAI (multilingües, suenan bien en español); "instructions" es un campo aparte: no se lee en voz alta
    last = None
    for mdl in [m for m in re.split(r"[,\s]+", E.get("OPENAI_TTS_MODEL", "gpt-4o-mini-tts,tts-1")) if m]:
        if _tcool.get((k[-8:], mdl), 0) > time.time(): continue
        left = _left()
        if left <= 1: raise Budget()
        body = {"model": mdl, "input": text, "voice": voice, "response_format": "wav"}
        if "gpt-4o" in mdl: body["instructions"] = E.get("TTS_STYLE", "Habla en español colombiano, de forma natural, cálida y cercana, como un amigo que te habla tranquilo; sin sonar robótico.")
        try:
            r = httpx.post(E.get("OPENAI_BASE_URL", "https://api.openai.com/v1").rstrip("/") + "/audio/speech", headers={"Authorization": f"Bearer {k}"}, json=body, timeout=httpx.Timeout(min(20, left), connect=5)); r.raise_for_status()
            if r.content: return base64.b64encode(r.content).decode()
        except httpx.HTTPStatusError as e:
            last = e; c = e.response.status_code
            if c in (400, 404, 429, 500, 503): _tcool[(k[-8:], mdl)] = time.time() + 60; continue   # este modelo no está disponible para esta key: prueba el siguiente
            raise
    if last: raise last
    return ""
def tts(text, voice="Aoede", oa_voice="nova"):
    """Texto -> (audio WAV base64, 'proveedor#n'). Rota igual que el chat: Gemini y luego OpenAI (TTS_ORDER). Groq no tiene voz en español, así que no participa.
    Lanza LLMError si ninguno puede (el navegador entonces lee con su voz)."""
    text = text.strip()[:900]   # SOLO el texto a leer: cualquier instrucción dentro del texto se lee en voz alta
    errs = []
    for prov in [p for p in re.split(r"[,\s]+", E.get("TTS_ORDER", "gemini")) if p in ("gemini", "openai")]:
        if not keys(prov): continue
        _tl.dl = time.time() + float(E.get("TTS_BUDGET", "14"))   # cada proveedor tiene su propio tope de espera
        try: r = _run(prov, (lambda k: _tts_gemini(k, text, voice)) if prov == "gemini" else (lambda k: _tts_openai(k, text, oa_voice)), errs)
        finally: _tl.dl = 0
        if r: return r
    raise LLMError("; ".join(errs) or "sin keys de Gemini ni OpenAI para voz")
