"""Memoria a largo plazo: cada ~14 mensajes nuevos se actualiza un resumen. En Docker lo dispara el chat; en Vercel lo hace el ETL programado."""
import time
from common import *
import llm
def summarize(u):  # el resumen viaja siempre en el contexto del chat
    if u in busy: return
    busy.add(u)
    try:
        doc = mongo.memory.find_one({"email": u}) or {}
        new = list(mongo.chat.find({"email": u, "ts": {"$gt": doc.get("upto", 0)}}, {"_id": 0}).sort("ts", 1))
        if len(new) < 14: return
        chunk = new[:-6][:80]
        txt = "\n".join(f"{'Estudiante' if m['role'] == 'user' else 'SerenIA'}: {m['text'][:400]}" for m in chunk)
        out, via = llm.generate("Mantienes la memoria a largo plazo de una acompañante de apoyo emocional universitaria. Escribes resúmenes fieles, sin inventar.",
            [{"role": "user", "content": f"RESUMEN ACTUAL:\n{doc.get('summary') or '(vacío)'}\n\nNUEVOS MENSAJES:\n{txt}\n\nDevuelve el resumen actualizado en español (máx. 1500 caracteres): datos personales y académicos (carrera, materias, semestre), personas importantes, problemas recurrentes, qué le ha ayudado y qué no, compromisos o pendientes, y cómo ha evolucionado su ánimo."}],
            max_tokens=700, temperature=0.2, order_=[p for p in E.get("MEMORY_LLM_ORDER", "github,cohere,gemini,anthropic").split(",") if p in llm.LIMIT])
        d = {"summary": out.strip(), "upto": chunk[-1]["ts"], "ts": time.time()}
        mongo.memory.update_one({"email": u}, {"$set": d}, upsert=True); raw("memory", u, {**d, "via": via})
    except Exception as e: print("[memory]", type(e).__name__, e, flush=True)
    finally: busy.discard(u)
busy = set()


def due_users(limit=20):
    """Estudiantes con 14+ mensajes sin resumir (para el ETL programado). Solo cuenta mensajes, no lee su contenido."""
    out = []
    for e in mongo.chat.distinct("email"):
        up = (mongo.memory.find_one({"email": e}, {"upto": 1}) or {}).get("upto", 0)
        if mongo.chat.count_documents({"email": e, "ts": {"$gt": up}}) >= 14: out.append(e)
        if len(out) >= limit: break
    return out
