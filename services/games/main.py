# Microservicio GAMES: catálogo (games.json), algoritmo que elige el juego según el estado del estudiante y registro de cada partida en el datalake
import json, os
from fastapi import FastAPI, Depends
from common import *
import moderation
app = new_app(max_body=65536); boot()
CAT = json.load(open(os.path.join(os.path.dirname(__file__), "games.json"), encoding="utf-8"))["games"]
BY = {g["id"]: g for g in CAT}
@app.get("/catalog")
def catalog(u=Depends(me)): return CAT
def category(topics, stress, mood, anxiety):
    t = set(topics)
    if t & {"ansiedad", "panico"} or stress >= 4 or anxiety >= 4: return "calma"
    if t & {"enojo", "duelo"}: return "desahogo"
    if "autoexigencia" in t: return "autoestima"
    if t & {"tristeza", "soledad"} or mood <= 2: return "animo"
    if "estudio" in t: return "estudio"
@app.post("/suggest")
def suggest(b: dict, u=Depends(me)): return pick(u, need_json_obj(b))
def pick(u, b):
    rate(f"sugg:{eh(u)}", 60, 60)
    num = lambda v, d: v if isinstance(v, (int, float)) and not isinstance(v, bool) else d
    topics = [t for t in (b.get("topics") if isinstance(b.get("topics"), list) else []) if isinstance(t, str)][:8]
    cat = category(topics, num(b.get("stress"), 0), num(b.get("mood"), 5), num(b.get("anxiety"), 0))
    if not cat: return {"games": []}
    c = pg(); cur = c.cursor()   # solo las partidas DE ESTE usuario: se ofrece primero lo que menos ha jugado y lo que sí completó
    cur.execute("SELECT game, count(*), sum(CASE WHEN completed THEN 1 ELSE 0 END) FROM game_plays WHERE email=%s GROUP BY game", (u,)); n = {g: (a, b_ or 0) for g, a, b_ in cur.fetchall()}; c.close()
    pool = [g for g in CAT if g["cat"] == cat]
    return {"games": sorted(pool, key=lambda g: (n.get(g["id"], (0, 0))[0], -n.get(g["id"], (0, 0))[1]))[:1]}
@app.post("/play")
def play(b: dict, u=Depends(me)):
    b = need_json_obj(b); rate(f"play:{eh(u)}", 120, 3600)
    g = BY.get(b.get("game")) if isinstance(b.get("game"), str) else None
    if not g: return {"ok": False}
    rs = b.get("responses") if isinstance(b.get("responses"), list) else []
    ans = [{"ask": security.text(a.get("ask"), 200), "text": security.text(a.get("text"), 1500)} for a in rs[:12] if isinstance(a, dict) and isinstance(a.get("text"), str) and a["text"].strip()]
    bad = [(a, moderation.check(a["text"])) for a in ans]; msg = next((m[1] for a, m in bad if m), "")
    for a, m in bad:
        if m: moderation.strike(u, m[0], a["text"], "game")
    ans = [a for a, m in bad if not m]   # lo no permitido nunca llega al datalake de aprendizaje
    raw("game", u, {"game": g["id"], "name": g["name"], "cat": g["cat"], "completed": bool(b.get("completed", True)), "secs": max(0, min(int(b["secs"]), 3600)) if isinstance(b.get("secs"), (int, float)) and not isinstance(b.get("secs"), bool) else 0, "responses": ans})
    return {"ok": True, "blocked": bool(msg), "msg": msg}
