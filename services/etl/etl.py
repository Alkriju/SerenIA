# HARNESS ETL: datalake (crudo) -> [IA clasifica emociones/problemas] -> PostgreSQL + MongoDB
import json, re, time, psycopg2
from pymongo.errors import PyMongoError
from common import *
import llm
ETL_ORDER = [p for p in E.get("ETL_LLM_ORDER", "deepseek,qwen").split(",") if p in llm.LIMIT]  # SOLO keys del ETL (.env.etl): Qwen / DeepSeek
import survey as sv
EMO = ("tristeza", "ansiedad", "estres", "enojo", "alegria", "neutral")
SYS = ('Eres el paso de transformación (ETL) de una app de apoyo emocional universitaria. Convierte el texto de un estudiante en datos estructurados. Devuelve SOLO JSON válido, sin texto extra: '
       '{"emotion":"tristeza|ansiedad|estres|enojo|alegria|neutral","intensity":1-5,"problems":["tema corto en minúsculas"],"facts":["dato personal o académico estable que dice de sí mismo (carrera, materia, semestre, persona importante, situación, fortaleza), en 3ra persona"],"risk":"none|low|high"}. '
       'No inventes: si no hay datos, listas vacías.')
def classify(t):  # estructura el texto con IA (con respaldo por palabras clave si no hay keys o fallan)
    base = {"emotion": "desconocida", "intensity": 0, "problems": detect(t), "facts": [], "risk": "none"}
    if len(t) < 25 or not llm.available(ETL_ORDER): return base
    try:
        r, via = llm.generate(SYS, [{"role": "user", "content": t[:2500]}], max_tokens=300, temperature=0, order_=ETL_ORDER)
        j = json.loads(re.search(r"\{.*\}", r, re.S).group())
        em = str(j.get("emotion", "")).lower().replace("é", "e").replace("í", "i")
        base.update(emotion=em if em in EMO else "neutral", intensity=max(0, min(5, int(j.get("intensity") or 0))),
                    problems=[str(x)[:40].lower() for x in (j.get("problems") or [])][:5] or base["problems"],
                    facts=[str(x)[:200] for x in (j.get("facts") or [])][:5], risk=str(j.get("risk", "none")))
    except Exception as e: print("[etl-ia]", type(e).__name__, str(e)[:160], flush=True)
    return base
# ── Mejora de la IA: SOLO con datos de quien lo autorizó (casilla opcional) y seudonimizados (sin correo, teléfonos, enlaces ni números largos).
SCRUB = [(re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+"), "[correo]"), (re.compile(r"https?://\S+|www\.\S+"), "[enlace]"), (re.compile(r"\+?\d[\d\s().-]{6,}\d"), "[número]")]
def scrub(t):
    for rx, r in SCRUB: t = rx.sub(r, t)
    return t
_ai = {}
def ai_ok(u, cur):
    c = _ai.get(u)
    if c and c[0] > time.time(): return c[1]
    cur.execute("SELECT ai, terms FROM account_state WHERE eh=%s", (eh(u),)); r = cur.fetchone()
    ok = bool(r and r[0] and r[1] == TERMS_VERSION); _ai[u] = (time.time() + 30, ok); return ok
def improve(u, cur, source, text, c):
    if len(text) < 20 or not ai_ok(u, cur): return   # sin permiso (o retirado) NO entra en ningún conjunto de mejora
    mongo.improve_corpus.insert_one({"uid": eh(u), "ts": time.time(), "source": source, "text": scrub(text)[:2000], "emotion": c["emotion"], "problems": c["problems"]})
def learn(u, c, text, cur, source):  # guarda lo estructurado: PostgreSQL (emotion_log) + MongoDB (perfil del estudiante)
    cur.execute("INSERT INTO emotion_log(email,emotion,intensity,problems,source) VALUES(%s,%s,%s,%s,%s)", (u, c["emotion"], c["intensity"], json.dumps(c["problems"], ensure_ascii=False), source))
    inc = {f"emotions.{c['emotion']}": 1}; inc.update({f"topics.{t.replace('.', ' ').replace('$', '')}": 1 for t in set(c["problems"]) | set(detect(text))})
    upd = {"$inc": inc}
    if c["facts"]: upd["$addToSet"] = {"facts": {"$each": c["facts"]}}
    mongo.profiles.update_one({"email": u}, upd, upsert=True)
    improve(u, cur, source, text, c)
from datetime import datetime as _D, timezone as _TZ
def _evts(o): return _D.fromtimestamp(o["ts"], _TZ.utc).replace(tzinfo=None)   # hora real del evento (UTC)
def run(o, cur):
    k, u, d = o["kind"], o["user"], o["data"]
    if k == "user": cur.execute("INSERT INTO users(email) VALUES(%s) ON CONFLICT (email) DO NOTHING", (u,))
    elif k == "survey":
        if "answers" in d:   # encuesta nueva: el ETL calcula los puntajes por dimensión a partir de las respuestas crudas
            a = d["answers"]; sc = sv.score(d["kind"], a); r = lambda x, dflt=3: int(round(sc.get(x, dflt)))
            cur.execute("INSERT INTO surveys(email,kind,mood,stress,sleep,dropout,note,anxiety,support,habits,money,risk,answers,ts) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                        (u, d["kind"], r("mood"), r("stress"), r("sleep"), r("dropout", 1), a.get("open1", ""), sc.get("anxiety"), sc.get("support"), sc.get("habits"), sc.get("money"), sc["risk"], json.dumps(a, ensure_ascii=False), _evts(o)))
            ctx = {f"context.{x}": a[x] for x in ("sem", "vive", "trabaja", "mat") if x in a}
            if ctx: mongo.profiles.update_one({"email": u}, {"$set": ctx}, upsert=True)
            if sc["flags"]: mongo.profiles.update_one({"email": u}, {"$set": {"alertas": sc["flags"], "riesgo": sc["risk"], "seguridad": sc.get("seguridad", "bajo")}}, upsert=True)
            txt = " ".join(str(a.get(x, "")) for x in ("open1", "open2", "mat")).strip()
            if txt: learn(u, classify(txt), txt, cur, "encuesta")
        else:   # formato antiguo
            cur.execute("INSERT INTO surveys(email,kind,mood,stress,sleep,dropout,note) VALUES(%s,%s,%s,%s,%s,%s,%s)", (u, d["kind"], d["mood"], d["stress"], d["sleep"], d["dropout"], d.get("note", "")))
    elif k == "game":
        cur.execute("INSERT INTO game_plays(email,game,completed,secs) VALUES(%s,%s,%s,%s)", (u, d["game"], bool(d.get("completed", True)), int(d.get("secs") or 0)))
        rs = d.get("responses") or []
        if rs:   # lo que el estudiante escribió en el juego -> se estructura y alimenta su perfil (solo el suyo)
            txt = "\n".join(f"{x['ask']}: {x['text']}" for x in rs); c = classify(txt)
            mongo.game_responses.insert_one({"email": u, "ts": o["ts"], "game": d["game"], "name": d.get("name"), "responses": rs, "analysis": c})
            learn(u, c, txt, cur, "juego:" + d["game"])
    elif k == "pref": mongo.prefs.update_one({"email": u}, {"$set": d}, upsert=True)
    elif k == "knowledge": mongo.knowledge.replace_one({"id": d["id"]}, d, upsert=True)
    elif k == "decision": mongo.decisions.insert_one({"email": u, "ts": o["ts"], **d})
    elif k == "chat" and d["role"] == "user":
        c = classify(d["text"]); learn(u, c, d["text"], cur, "chat"); mongo.profiles.update_one({"email": u}, {"$inc": {"msgs": 1}}, upsert=True)
def keys(prefix):
    for pg_ in s3.get_paginator("list_objects_v2").paginate(Bucket=BUCKET, Prefix=prefix):
        for it in pg_.get("Contents", []): yield it["Key"]
def process(cur, done, deadline=None):
    """Transforma lo que haya nuevo en raw/. Devuelve cuántos objetos pasaron a processed/ y cuántos a failed/. raw/ es INMUTABLE (se conserva todo el dato crudo); processed/ y failed/ son las marcas de lo ya transformado."""
    ok = bad = 0
    for key in keys("raw/"):
        if deadline and time.time() > deadline: break
        name = key.split("/", 1)[1]
        if name in done: continue
        dest = "processed/"
        try: run(json.loads(s3.get_object(Bucket=BUCKET, Key=key)["Body"].read()), cur)
        except (psycopg2.OperationalError, PyMongoError): raise  # BD caída: reintenta luego, no descartes el objeto
        except Exception as ex: print("etl objeto con error ->failed/", key, ex, flush=True); dest = "failed/"
        s3.copy_object(Bucket=BUCKET, Key=dest + name, CopySource={"Bucket": BUCKET, "Key": key}); done.add(name)
        if dest == "failed/": bad += 1
        else: ok += 1
    return ok, bad
def inline(key, o):
    """Transforma UN objeto recién escrito (Vercel). Si falla no pasa nada: la pasada programada lo procesa."""
    c = pg()
    try:
        run(o, c.cursor()); s3.copy_object(Bucket=BUCKET, Key="processed/" + key.split("/", 1)[1], CopySource={"Bucket": BUCKET, "Key": key})
    finally: c.close()
def marks(): return {k.split("/", 1)[1] for z in ("processed/", "failed/") for k in keys(z)}
def run_pass(budget=200):
    """Una pasada completa (para Vercel: la dispara /api/cron/etl). Es idempotente: se puede llamar cuantas veces se quiera, y dos a la vez no duplican nada grave (las marcas se escriben al terminar cada objeto)."""
    t0 = time.time(); init(); out = {"seed": 0, "processed": 0, "failed": 0, "summaries": 0}
    try:
        import seed; out["seed"] = seed.ensure()
    except ImportError: pass
    c = pg(); cur = c.cursor()
    try: out["processed"], out["failed"] = process(cur, marks(), t0 + budget)
    finally: c.close()
    try:
        import memsum
        for u in memsum.due_users(5):
            if time.time() > t0 + budget: break
            memsum.summarize(u); out["summaries"] += 1
    except Exception as e: print("[etl] resúmenes:", type(e).__name__, str(e)[:120], flush=True)
    out["secs"] = round(time.time() - t0, 1); return out
if __name__ == "__main__":   # Docker: bucle continuo (importar el módulo en las pruebas no lo arranca)
    cur, done = None, None
    while True:
        try:
            if cur is None: init(); cur = pg().cursor()
            if done is None: done = marks()
            process(cur, done)
        except Exception as e: print("etl error", e, flush=True); cur = None
        time.sleep(3)
