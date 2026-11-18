# Microservicio SURVEY: encuesta diagnóstica inicial, encuesta de semanas de parciales y check-ins. Cuestionarios en shared/questions.json
import datetime as dt
from fastapi import FastAPI, Depends, HTTPException
from common import *
import survey as sv
import moderation
app = new_app(max_body=65536); boot()
def exam_window():  # EXAM_WEEKS="2026-11-16/2026-11-22,2027-03-08/2027-03-14"; se pregunta desde EXAM_LEAD_DAYS días antes hasta que termina el periodo
    t, lead = dt.date.today(), int(E.get("EXAM_LEAD_DAYS", "7"))
    for p in E.get("EXAM_WEEKS", "").split(","):
        if "/" in p:
            a, b = [dt.date.fromisoformat(x.strip()) for x in p.split("/")]
            if a - dt.timedelta(days=lead) <= t <= b: return a - dt.timedelta(days=lead), a, b
@app.get("/pending")
def pending(u=Depends(me)):
    c = pg(); cur = c.cursor(); cur.execute("SELECT kind, ts FROM surveys WHERE email=%s", (u,)); rows = cur.fetchall(); c.close()
    try: done_raw = bool(s3.list_objects_v2(Bucket=BUCKET, Prefix=f"raw/survey/{hashlib.sha1(u.encode()).hexdigest()[:10]}/", MaxKeys=1).get("KeyCount"))
    except Exception: done_raw = False   # encuesta enviada pero que el ETL aún no carga: no la vuelvas a pedir
    w = exam_window()
    if not rows: return {"pending": None if done_raw else "inicial", "exam_week": bool(w)}
    recent = any((dt.datetime.now() - t).days < 3 for _, t in rows)   # si acaba de responder cualquier encuesta, no se le pide otra enseguida
    if w and not recent and not any(k == "parciales" and t.date() >= w[0] for k, t in rows): return {"pending": "parciales", "exam_week": True}
    return {"pending": None, "exam_week": bool(w)}
@app.get("/form")
def form(kind: str = "seguimiento", u=Depends(me)):
    if kind not in sv.QS["kinds"]: raise ApiError(404, "No encontrado", "not_found")
    return {"kind": kind, "nota": sv.QS["nota"], **sv.QS["kinds"][kind]}
@app.post("/")
def survey(b: dict, u=Depends(me)):
    b = need_json_obj(b); rate(f"survey:{eh(u)}", 10, 3600, "Ya enviaste varias encuestas. Inténtalo más tarde.")
    kind = b.get("kind") if b.get("kind") in sv.QS["kinds"] else "seguimiento"
    ans = sv.clean(kind, b.get("answers") if isinstance(b.get("answers"), dict) else {})
    if not ans: raise ApiError(400, "Respuestas vacías", "bad_input")
    for q in sv.flat(kind):
        m = moderation.check(ans.get(q["id"])) if q["type"] == "text" else None
        if m: moderation.strike(u, m[0], ans[q["id"]], "survey"); raise ApiError(422, m[1], "moderation")
    sc = sv.score(kind, ans); raw("survey", u, {"kind": kind, "answers": ans, "v": sv.QS["version"]})
    return {"ok": True, "scores": sc}   # el ETL repite el cálculo al cargar a PostgreSQL; aquí solo se devuelve para mostrarlo ya
@app.get("/history")
def history(u=Depends(me)):  # solo las encuestas DE ESTE usuario
    c = pg(); cur = c.cursor()
    cur.execute("SELECT id,kind,mood,stress,sleep,dropout,anxiety,support,risk,note,answers,ts,money FROM surveys WHERE email=%s ORDER BY ts DESC LIMIT 30", (u,)); rows = cur.fetchall(); c.close(); out = []
    for i, k, m, st, sl, d, a, su, ri, note, ans, t, mo in rows:
        txt = []; A = {}
        try:
            A = json.loads(ans) if ans else {}
            if k in sv.QS["kinds"]: txt = [{"p": q["text"], "r": A[q["id"]]} for q in sv.flat(k) if q["type"] == "text" and str(A.get(q["id"], "")).strip()]
        except Exception: pass
        if not txt and note and note.strip(): txt = [{"p": "Lo que contaste", "r": note.strip()}]
        seg = sv.seguridad(A.get("seguridad")) if isinstance(A, dict) else "bajo"   # mismas reglas para filas viejas y nuevas
        dims = {x: v for x, v in (("mood", m), ("stress", st), ("sleep", sl), ("dropout", d), ("anxiety", a), ("support", su), ("money", mo)) if v is not None}
        out.append({"id": str(i), "kind": k, "mood": m, "stress": st, "sleep": sl, "dropout": d, "anxiety": a, "support": su, "risk": sv.nivel(len(sv.alertas(dims)), seg), "seguridad": seg,
                    "ts": t.isoformat() + ("" if t.tzinfo else "Z"), "textos": txt})   # la BD guarda UTC: con "Z" el navegador lo pasa a tu hora local
    return out
@app.get("/schedule")
def schedule(u=Depends(dbg)):  # verificación: periodos de parciales configurados
    w = exam_window(); return {"EXAM_WEEKS": E.get("EXAM_WEEKS", ""), "dias_antes": int(E.get("EXAM_LEAD_DAYS", "7")), "hoy_en_ventana": bool(w), "ventana": [str(x) for x in w] if w else None}
