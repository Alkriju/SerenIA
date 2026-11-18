"""Servidor de prueba de punta a punta: el frontend REAL + los servicios REALES (auth, chat, survey, games) con bases en memoria.
   python tests/e2e_server.py 8113   y luego un navegador (Playwright) contra http://127.0.0.1:8113"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import conftest   # prepara variables de entorno y bases falsas
import uvicorn
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from test_flows import load
import common, security
auth, chat, survey, games = (load(x) for x in ("auth", "chat", "survey", "games"))
chat.llm.generate = lambda system, msgs, max_tokens=500: ("Aquí estoy contigo. Cuéntame más.", "stub#1")
chat.summarize = lambda u: None
CODES = {}
auth.send_code = lambda to, code: CODES.__setitem__(to, code)
root = FastAPI(docs_url=None, openapi_url=None)
@root.get("/__code")
def code(email: str): return {"code": CODES.get(email)}
@root.get("/__state")
def st():
    cur = common.pg().cursor(); cur.execute("SELECT count(*) FROM credentials"); n = cur.fetchone()[0]
    cur.execute("SELECT doc, accepted FROM consent_log ORDER BY ts"); cl = cur.fetchall()
    return {"credentials": n, "chat": common.mongo.chat.count_documents({}), "consent": cl, "lake": len([k for k in common.s3.o if not k.startswith("meta/")])}
for p, a in (("/api/auth", auth.app), ("/api/chat", chat.app), ("/api/survey", survey.app), ("/api/games", games.app)): root.mount(p, a)
root.mount("/", StaticFiles(directory=os.path.join(conftest.R, "frontend"), html=True))
uvicorn.run(root, host="127.0.0.1", port=int(sys.argv[1]) if len(sys.argv) > 1 else 8113, log_level="warning")
