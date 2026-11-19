"""Punto de entrada para VERCEL: una sola función que monta los 4 servicios (auth, chat, survey, games) con las mismas rutas /api/<servicio>/… que usa el frontend,
más las tareas programadas /api/cron/etl y /api/cron/backup (protegidas con CRON_SECRET). En Docker NO se usa este archivo: allí cada servicio corre aparte."""
import os, sys, secrets, threading, importlib.util, datetime as dt
R = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for p in ("shared", "services/etl", "services/seed", "services/backup"): sys.path.insert(0, os.path.join(R, p))
os.environ.setdefault("SERVERLESS", "1")
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from common import *   # (importa y valida la configuración de seguridad: en producción no arranca si es insegura)

def _load(svc):   # cada servicio se llama main.py: se carga por ruta para no mezclarlos
    sp = importlib.util.spec_from_file_location("serenia_" + svc, os.path.join(R, "services", svc, "main.py")); m = importlib.util.module_from_spec(sp); sys.modules[sp.name] = m; sp.loader.exec_module(m); return m
auth, chat, survey, games = (_load(x) for x in ("auth", "chat", "survey", "games"))
chat.SUGGEST = games.pick   # el chat pide el juego sugerido en el mismo proceso

app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
class _Slash:
    """Vercel puede entregar /api/chat o /api/survey sin la barra final; los servicios montados escuchan en '/'. Aquí se unifica para que ambas formas lleguen."""
    def __init__(self, a): self.a = a
    async def __call__(self, scope, receive, send):
        if scope["type"] == "http" and scope["path"] in ("/api/chat", "/api/survey"):
            scope = dict(scope, path=scope["path"] + "/", raw_path=(scope.get("raw_path") or scope["path"].encode()).rstrip(b"/") + b"/")
        await self.a(scope, receive, send)
app.add_middleware(_Slash)
for prefix, sub in (("/api/auth", auth.app), ("/api/chat", chat.app), ("/api/survey", survey.app), ("/api/games", games.app)): app.mount(prefix, sub)

def _cron_ok(req: Request) -> bool:
    s = E.get("CRON_SECRET", "")
    if len(s) < 24: return False   # sin secreto fuerte las tareas quedan apagadas
    return secrets.compare_digest(req.headers.get("authorization", ""), "Bearer " + s)
def _lock(name: str, secs: int) -> bool:
    """Que dos disparos a la vez no hagan el mismo trabajo (por ejemplo el cron de GitHub y el de Vercel)."""
    now = dt.datetime.utcnow()
    try:
        mongo.locks.update_one({"_id": name}, {"$setOnInsert": {"exp": dt.datetime(1970, 1, 1)}}, upsert=True)
        r = mongo.locks.update_one({"_id": name, "exp": {"$lt": now}}, {"$set": {"exp": now + dt.timedelta(seconds=secs)}})
        return r.modified_count == 1
    except Exception: return False
def _job(name, secs, fn):
    def go(req: Request):
        if not _cron_ok(req): return JSONResponse({"detail": "No autorizado"}, 401, headers={"Cache-Control": "no-store"})
        if not _lock(name, secs): return JSONResponse({"ok": True, "skipped": "ya hay otra ejecución en curso"}, headers={"Cache-Control": "no-store"})
        try: res = fn()
        except Exception as e:
            print(f"[cron:{name}] ERROR", type(e).__name__, str(e)[:200], flush=True); return JSONResponse({"ok": False, "error": type(e).__name__}, 500, headers={"Cache-Control": "no-store"})
        finally: mongo.locks.update_one({"_id": name}, {"$set": {"exp": dt.datetime.utcnow() - dt.timedelta(seconds=1)}})
        return JSONResponse({"ok": True, **(res or {})}, headers={"Cache-Control": "no-store"})
    return go
def _etl():
    import etl; return etl.run_pass(budget=int(E.get("ETL_BUDGET_SECS", "90")))
def _backup():
    import backup; r = backup.cloud_backup(); return {"file": r["file"], "where": r["where"], "entries": r["entries"]}
app.get("/api/cron/etl", include_in_schema=False)(_job("etl", 150, _etl))
app.get("/api/cron/backup", include_in_schema=False)(_job("backup", 280, _backup))
@app.get("/api/health", include_in_schema=False)
def health(): return JSONResponse({"ok": True}, headers={"Cache-Control": "no-store"})
