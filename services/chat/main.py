# Microservicio CHAT: IA multi-proveedor (Gemini x N + GitHub Models + Cohere) con memoria total.
# El contexto de cada respuesta sale de lo que el ETL dejó a partir del datalake:
#   MongoDB (historial completo, perfil, resumen de memoria, conocimiento psicológico) + PostgreSQL (encuestas, emociones, juegos).
import re, time, threading, unicodedata, httpx
from fastapi import FastAPI, Request, Depends
from common import *
import llm
import moderation
import base64
from concurrent.futures import ThreadPoolExecutor
POOL = ThreadPoolExecutor(8)
SUGGEST = None   # en Vercel (api/index.py) apunta a games.pick: los 4 servicios viven en un solo proceso
VOICES = {"aoede": ("Aoede", "f", "nova"), "sulafat": ("Sulafat", "f", "coral"), "leda": ("Leda", "f", "shimmer"), "achird": ("Achird", "m", "ash"), "puck": ("Puck", "m", "echo"), "iapetus": ("Iapetus", "m", "onyx")}  # (voz Gemini, género, voz OpenAI parecida)  # 3 voces de mujer y 3 de hombre
TONES = {"amigo": "Habla como un buen amigo: informal, cálido, con confianza.", "calmado": "Habla con tono sereno y pausado, transmitiendo calma.", "motivador": "Habla con energía positiva y motivadora, sin presionar.", "formal": "Habla de forma respetuosa y más formal, sin perder calidez."}
LENGTHS = {"breve": "Respuestas muy breves (máx. ~60 palabras).", "media": "Respuestas breves (máx. ~120 palabras).", "detallada": "Puedes extenderte más (hasta ~220 palabras) con pasos concretos."}
DEFAULT_PREFS = {"voice": "aoede", "tone": "amigo", "length": "media", "name": "", "likes": ""}
app = new_app(max_body=int(E.get("MAX_AUDIO_BYTES", "6000000")) + 4096); boot()   # el cuerpo grande solo se admite por el audio de /transcribe; cada ruta valida su propio tamaño
CRISIS = ["suicid", "matarme", "quitarme la vida", "no quiero vivir", "hacerme daño", "autolesi", "quiero morir", "acabar con todo", "terminar con mi vida", "no quiero seguir viviendo"]
PERSONA = ("Eres SerenIA, una acompañante de apoyo emocional para estudiantes universitarios colombianos. Hablas en español, cálida, cercana y breve (máximo ~120 palabras). "
           "No eres terapeuta: no diagnosticas ni recetas. Si hay riesgo para su vida, deriva a Bienestar Universitario, Línea 106 (salud mental) o 123. "
           "Primero valida la emoción, luego haz UNA sola pregunta o propón un paso pequeño. "
           "Tienes memoria total de este estudiante: usa el resumen, los recuerdos, las encuestas, emociones y juegos que aparecen abajo para dar continuidad y hacer seguimiento natural "
           "(retoma lo que te contó, pregunta cómo salió lo pendiente), sin sonar a ficha técnica ni citar 'mis datos'. "
           "BÓVEDA: solo conoces a ESTE estudiante. Todo lo que aparece abajo es suyo y confidencial; nunca menciones, supongas ni mezcles datos de otras personas, y si no sabes algo de él/ella, pregúntalo en vez de inventarlo. "
           "Si piensa en dejar materias, ayúdale a separar el problema (una materia, la carga, el dinero, la vocación) antes de decidir.")
VOZ = "\nMODO VOZ: tu respuesta se leerá en voz alta. Máximo 3 frases cortas, sin listas, sin markdown y sin emojis."
BUSY = "Ahora mismo estoy con mucha demanda y no pude responderte bien. Dame un minuto y escríbeme de nuevo; aquí sigo contigo. Si es urgente, llama al 123 o a la Línea 106."
RECENT = 30
STOP = set("pero porque para como esto esta este estoy tengo quiero puedo algo muy mucho cuando donde hola gracias tambien entonces aunque sobre desde hasta todo nada cada tiene tengo hacer siento sentir".split())

def words(t):
    t = "".join(c for c in unicodedata.normalize("NFD", t.lower()) if unicodedata.category(c) != "Mn")
    return {w for w in re.findall(r"[a-z]{4,}", t)} - STOP
def day(ts): return time.strftime("%Y-%m-%d", time.localtime(ts))
def retrieve(t):  # RAG simple: conocimiento psicológico del datalake (llegó a Mongo vía ETL) según palabras clave
    t = t.lower(); sc = sorted([(sum(w in t for w in k["keys"]), k) for k in mongo.knowledge.find({}, {"_id": 0}) if k["keys"]], key=lambda x: -x[0])
    base = mongo.knowledge.find_one({"id": "principios"}, {"_id": 0})
    return ([base] if base else []) + [k for n, k in sc[:3] if n]
def save(u, role, text, **x):
    mongo.chat.insert_one({"email": u, "role": role, "text": text, "ts": time.time(), **x}); raw("chat", u, {"role": role, "text": text, **x})

def recent(u):
    docs = list(mongo.chat.find({"email": u}, {"_id": 0}).sort("ts", -1).limit(RECENT))[::-1]
    return [{"role": d["role"], "content": d["text"]} for d in docs], (docs[0]["ts"] if docs else time.time())
def older_memories(u, text, cutoff):  # recuerda TODO: busca en TODO el historial anterior lo que se parece a lo que dice ahora
    q = words(text)
    if not q: return []
    sc = []
    for d in mongo.chat.find({"email": u, "role": "user", "ts": {"$lt": cutoff}}, {"_id": 0, "text": 1, "ts": 1}).sort("ts", -1).limit(4000):
        n = len(q & words(d["text"]))
        if n >= (1 if len(q) <= 3 else 2): sc.append((n, d["ts"], d["text"]))
    sc.sort(key=lambda x: (-x[0], -x[1]))
    return [f'- [{day(ts)}] "{t[:220]}"' for _, ts, t in sc[:5]]
def context(u, text):
    parts = []
    try:
        mem = mongo.memory.find_one({"email": u}, {"_id": 0}) or {}
        if mem.get("summary"): parts.append("RESUMEN DE TODO LO ANTERIOR CON ESTE ESTUDIANTE:\n" + mem["summary"])
    except Exception: pass
    try:
        prof = mongo.profiles.find_one({"email": u}, {"_id": 0, "email": 0}) or {}; first = mongo.chat.find_one({"email": u}, {"ts": 1}, sort=[("ts", 1)])
        parts.append(f"PERFIL (acumulado por el ETL): mensajes={prof.get('msgs', 0)}, temas recurrentes={prof.get('topics', {})}, emociones detectadas={prof.get('emotions', {})}" + (f", habla contigo desde {day(first['ts'])}" if first else ""))
        if prof.get("facts"): parts.append("DATOS ESTRUCTURADOS DEL ESTUDIANTE (extraídos por el ETL): " + "; ".join(prof["facts"][-15:]))
        if prof.get("context"): parts.append("CONTEXTO QUE DIO EN LA ENCUESTA: " + ", ".join(f"{k}={v}" for k, v in prof["context"].items()))
        if prof.get("alertas"): parts.append(f"ALERTAS DE LA ENCUESTA (riesgo {prof.get('riesgo', 'bajo')}): " + ", ".join(prof["alertas"]) + ". Atiéndelas con tacto.")
        gr = list(mongo.game_responses.find({"email": u}, {"_id": 0, "name": 1, "responses": 1, "ts": 1}).sort("ts", -1).limit(4))
        if gr: parts.append("LO QUE ESCRIBIÓ EN SUS JUEGOS (úsalo con delicadeza, sin citarlo textual):\n" + "\n".join(f"- {day(g['ts'])} {g['name']}: " + " | ".join(r['text'][:160] for r in g['responses'][:4]) for g in gr))
        mv = mongo.chat.count_documents({"email": u, "role": "user", "mode": "voice"}); mt = prof.get("msgs", 0)
        if mt >= 10 and mv / max(mt, 1) > 0.5: parts.append("ESTILO: suele hablarte por voz; responde aún más corto y conversado.")
        em = prof.get("emotions", {}); top = max(((v, k) for k, v in em.items() if k not in ("neutral", "desconocida")), default=None)
        tips = {"ansiedad": "prioriza técnicas de calma y respiración", "tristeza": "prioriza validación y pequeñas acciones de cuidado", "estres": "ayuda a priorizar y dividir tareas", "enojo": "deja que se desahogue antes de proponer nada"}
        if top and top[1] in tips: parts.append(f"ADAPTACIÓN: su emoción más frecuente es {top[1]}; {tips[top[1]]}.")
    except Exception as e: print("[ctx] mongo:", type(e).__name__, e, flush=True)
    try:
        c = pg(); cur = c.cursor()
        cur.execute("SELECT kind,mood,stress,sleep,dropout,note,ts,anxiety,risk FROM surveys WHERE email=%s ORDER BY ts DESC LIMIT 3", (u,)); sv = cur.fetchall()
        if sv:
            parts.append("ENCUESTAS (más reciente primero):\n" + "\n".join(f"- {k} {t:%Y-%m-%d}: ánimo {m}/5, estrés {s}/5, sueño {sl}/5, ganas de dejar materias {d}/5" + (f", ansiedad {_a}/5" if _a else "") + (f", riesgo {_r}" if _r else "") + (f', nota: "{n}"' if n else "") for k, m, s, sl, d, n, t, _a, _r in sv))
            k, m, s, sl, d, n, t, an, rk = sv[0]; al = [x for x, c_ in [("riesgo ALTO de deserción", d >= 4), ("estrés alto", s >= 4), ("ánimo bajo", m <= 2), ("mal sueño", sl <= 2)] if c_]
            if al: parts.append("ALERTAS según su última encuesta: " + ", ".join(al) + ". Atiéndelas con tacto.")
        cur.execute("SELECT emotion,intensity,ts FROM emotion_log WHERE email=%s AND emotion<>'desconocida' ORDER BY ts DESC LIMIT 5", (u,)); em = cur.fetchall()
        if em: parts.append("EMOCIONES RECIENTES: " + ", ".join(f"{e} ({i}/5, {t:%m-%d})" for e, i, t in em))
        cur.execute("SELECT game,count(*),max(ts) FROM game_plays WHERE email=%s GROUP BY game ORDER BY max(ts) DESC LIMIT 4", (u,)); gp = cur.fetchall()
        if gp: parts.append("JUEGOS QUE HA JUGADO: " + ", ".join(f"{g} x{n}" for g, n, _ in gp))
        c.close()
    except Exception as e: print("[ctx] postgres:", e, flush=True)
    return parts

from memsum import summarize   # (vive en shared/memsum.py: lo usan el chat en Docker y el ETL en la nube)

def get_prefs(u):
    d = mongo.prefs.find_one({"email": u}, {"_id": 0, "email": 0}) or {}; return {**DEFAULT_PREFS, **d}
def persona(u, m):
    p = get_prefs(u)
    x = " " + TONES.get(p["tone"], TONES["amigo"]) + " " + LENGTHS.get(p["length"], LENGTHS["media"])
    if p.get("name"): x += f" Llámale {p['name'][:30]}."
    if p.get("likes"): x += f" Le gusta/interesa: {p['likes'][:160]}."
    return PERSONA + x + (VOZ if m == "voice" else "")
@app.get("/prefs")
def prefs_get(u=Depends(me)): return {"prefs": get_prefs(u), "voices": [{"id": k, "name": v[0], "g": v[1]} for k, v in VOICES.items()]}
@app.post("/prefs")
def prefs_set(b: dict, u=Depends(me)):
    b = need_json_obj(b); rate(f"prefs:{eh(u)}", 60, 60); d = {}
    for k, allowed in (("voice", VOICES), ("tone", TONES), ("length", LENGTHS)):
        if isinstance(b.get(k), str) and b[k] in allowed: d[k] = b[k]
    for k, n in (("name", 30), ("likes", 160)):   # estos textos entran al prompt de la IA: una sola línea, sin saltos que simulen otras instrucciones
        if isinstance(b.get(k), str): d[k] = " ".join(security.text(b[k], n).split())
    if d: mongo.prefs.update_one({"email": u}, {"$set": d}, upsert=True); raw("pref", u, d)   # también al datalake: la IA aprende de cómo se personaliza
    return get_prefs(u)
_samples = {}
@app.post("/tts")
def tts(b: dict, u=Depends(me)):  # texto -> audio con la voz que el estudiante eligió (o la que se pruebe)
    b = need_json_obj(b); rate(f"tts:{eh(u)}", int(E.get("TTS_PER_MIN", "40")), 60)
    p = get_prefs(u); v = b.get("voice") if b.get("voice") in VOICES else p["voice"]; t = security.text(b.get("text"), 900, "El texto")
    if not t: return {"audio": ""}
    key = (v, t) if b.get("sample") else None
    if key and key in _samples: return {"audio": _samples[key]}
    try: a, via = llm.tts(t, VOICES[v][0], VOICES[v][2])
    except llm.LLMError as e: print("[tts]", e, flush=True); return {"audio": "", "error": True}
    if key: _samples[key] = a
    return {"audio": a, "via": via}

@app.post("/")
def chat(b: dict, req: Request, u=Depends(me)):
    b = need_json_obj(b); rate(f"chat:{eh(u)}", int(E.get("CHAT_PER_MIN", "20")), 60, "Vas muy rápido: espera unos segundos y sigue conversando."); rate(f"chatd:{eh(u)}", int(E.get("CHAT_PER_DAY", "400")), 86400, "Llegaste al límite de mensajes de hoy. Mañana seguimos; si es urgente, llama al 123 o a la Línea 106.")
    text = security.text(b.get("text"), 4000, "El mensaje"); m = "voice" if b.get("mode") == "voice" else "chat"
    if not text: return {"reply": "", "games": []}
    left = moderation.pause_left(u)
    if left: return {"reply": moderation.pausa(left), "topics": [], "blocked": True}   # en pausa: no suma más intentos
    mod = moderation.check(text)
    if mod:
        moderation.strike(u, mod[0], text, "chat")   # no se guarda en la memoria ni llega a la IA
        left = moderation.pause_left(u)
        return {"reply": moderation.pausa(left) if left else mod[1], "topics": [], "blocked": True}
    save(u, "user", text, mode=m); topics = detect(text)
    if any(k in text.lower() for k in CRISIS):
        r = "Lo que sientes importa y no tienes que pasarlo solo/a. Si estás en peligro llama ya al 123 o a la Línea 106 (salud mental). También puedes ir a Bienestar Universitario. ¿Hay alguien cerca que pueda acompañarte ahora?"
        save(u, "assistant", r, crisis=True, mode=m); raw("decision", u, {"crisis": True, "mode": m}); return {"reply": r, "topics": [], "crisis": True}
    t0 = time.time(); msgs, cutoff = recent(u)
    f_ctx, f_old, f_kb = POOL.submit(context, u, text), POOL.submit(older_memories, u, text, cutoff), POOL.submit(retrieve, text)   # en paralelo: menos espera antes de llamar a la IA
    parts = f_ctx.result(); old = f_old.result()
    if old: parts.append("RECUERDOS DE CONVERSACIONES ANTERIORES RELACIONADOS CON LO QUE DICE AHORA:\n" + "\n".join(old))
    try: kb = f_kb.result()
    except Exception: kb = []
    if kb: parts.append(f"CONOCIMIENTO PSICOLÓGICO DE APOYO (aplícalo con tus palabras, sin citarlo): {kb}")
    system = persona(u, m) + "\n\n" + "\n\n".join(parts)
    try: reply, via = llm.generate(system, msgs, max_tokens=170 if m == "voice" else 500)
    except llm.LLMError as e:
        print("[chat] sin respuesta de ninguna IA:", e, flush=True); raw("decision", u, {"error": str(e)[:300], "mode": m})
        return {"reply": BUSY + (f"\n\n[detalle técnico: {str(e)[:260]}]" if (E.get("DEBUG_AI", "0") == "1" and not security.PROD) else ""), "topics": [], "error": True}   # el detalle técnico solo se muestra en desarrollo
    save(u, "assistant", reply, via=via, mode=m)
    def after():   # lo que no hace falta para responder se hace DESPUÉS de devolver la respuesta
        try: raw("decision", u, {"topics": topics, "via": via, "mode": m, "ms": int((time.time() - t0) * 1000)})
        except Exception: pass
        if not SERVERLESS: summarize(u)
    if SERVERLESS: after()   # en Vercel un hilo se congela al terminar la respuesta: se guarda ya (una escritura rápida) y el resumen lo hace el ETL programado
    else: threading.Thread(target=after, daemon=True).start()
    return {"reply": reply, "topics": topics}
@app.post("/games")
def games_for(b: dict, req: Request, u=Depends(me)):  # el juego sugerido se pide aparte, en paralelo a la voz, para no retrasar la respuesta
    b = need_json_obj(b); rate(f"games:{eh(u)}", 40, 60)
    topics = [t for t in (b.get("topics") or []) if isinstance(t, str)][:8]; games = []; why = ""
    try:
        c = pg(); cur = c.cursor(); cur.execute("SELECT mood,stress,anxiety FROM surveys WHERE email=%s ORDER BY ts DESC LIMIT 1", (u,)); sv = cur.fetchone(); c.close()
        def ask(tp):
            pl = {"topics": tp, "stress": (sv[1] or 0) if sv else 0, "mood": (sv[0] or 5) if sv else 5, "anxiety": (sv[2] or 0) if sv else 0}
            if SUGGEST: return SUGGEST(u, pl)["games"]   # modo Vercel: mismo proceso, sin llamada HTTP
            return httpx.post("http://games:8000/suggest", cookies={security.COOKIE: req.cookies.get(security.COOKIE, "")}, timeout=5,
                json=pl).json()["games"]
        now = time.time(); last = mongo.offers.find_one({"email": u}, sort=[("ts", -1)]); ago = now - last["ts"] if last else 1e9
        games = ask(topics); why = "por tema o estado"
        if games and ago < 180: games, why = [], "ya se ofreció hace poco"          # no repetir la sugerencia en cada mensaje
        elif not games and ago > 600 and mongo.chat.count_documents({"email": u, "role": "user", "ts": {"$gt": now - 1800}}) >= 3:
            games = ask(["ansiedad"]); why = "pausa suave tras conversar un rato"    # sin tema claro: una pausa tras varios mensajes
        if games:
            mongo.offers.insert_one({"email": u, "ts": now, "games": [g["id"] for g in games]})
            raw("decision", u, {"games_offered": [g["id"] for g in games], "topics": topics, "why": why})
        print("[games] temas:", topics, "|", why or "sin criterio", "|", [g["id"] for g in games], flush=True)
    except Exception as e: print("[games] error:", type(e).__name__, e, flush=True)
    return {"games": games}
@app.get("/history")
def history(limit: int = 300, u=Depends(me)):
    limit = max(1, min(int(limit), 500))  # se guarda TODO; la pantalla muestra los últimos mensajes
    d = list(mongo.chat.find({"email": u}).sort("ts", -1).limit(limit))[::-1]; return [{"role": m["role"], "text": m["text"]} for m in d]
@app.post("/transcribe")
def transcribe(b: dict, u=Depends(me)):
    b = need_json_obj(b); rate(f"stt:{eh(u)}", int(E.get("STT_PER_MIN", "12")), 60)
    if not isinstance(b.get("audio"), str) or len(b["audio"]) > int(E.get("MAX_AUDIO_BYTES", "6000000")): raise ApiError(413, "El audio es demasiado largo", "too_large")
    if b.get("mime", "audio/wav") not in ("audio/wav", "audio/webm", "audio/ogg", "audio/mp4", "audio/mpeg", "audio/x-wav", "audio/wave"): raise ApiError(400, "Formato de audio no admitido", "bad_input")
    try: return {"text": llm.transcribe(b["audio"], b.get("mime", "audio/wav")).strip()}
    except llm.LLMError as e: print("[stt]", e, flush=True); return {"text": ""}
@app.get("/status")
def status(u=Depends(dbg)): return llm.status()   # diagnóstico: solo administradores
@app.get("/diagnose")
def diagnose(u=Depends(dbg)): return llm.diagnose()
@app.get("/context")
def show_context(q: str = "", u=Depends(dbg)):  # verificación: muestra EXACTAMENTE lo que la IA recibe de las bases de datos (que alimenta el datalake) para este usuario
    msgs, cutoff = recent(u); parts = context(u, q); old = older_memories(u, q, cutoff) if q else []
    try: kb = [k.get("id") for k in retrieve(q)] if q else []
    except Exception: kb = []
    return {"usuario": u, "mensajes_recientes_enviados": len(msgs), "total_mensajes_guardados": mongo.chat.count_documents({"email": u}),
            "bloques_de_contexto": parts, "recuerdos_relacionados": old, "conocimiento_psicologico_usado": kb}
