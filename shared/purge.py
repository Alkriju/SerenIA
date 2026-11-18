"""Derechos del titular: borrar TODA la cuenta de TODOS los almacenes y exportar sus datos."""
import json, time, datetime as dt, hashlib
from bson import json_util
from common import s3, mongo, pg, eh, forget, TERMS_VERSION, BUCKET, offsite

# Colecciones de MongoDB que NO son datos de una persona (se conservan)
SHARED_COLS = {"knowledge", "rl", "pow_used", "lockouts"}
PG_TABLES = ("surveys", "emotion_log", "game_plays", "users", "credentials")   # todas llevan la columna email

def _lake_objects(email):
    """Objetos del datalake de esta persona (raw/, processed/ y failed/). El prefijo usa un hash corto: se confirma el dueño leyendo el objeto antes de borrar."""
    h = hashlib.sha1(email.encode()).hexdigest()[:10]
    for top in ("raw/", "processed/", "failed/"):
        kinds = []
        for pg_ in s3.get_paginator("list_objects_v2").paginate(Bucket=BUCKET, Prefix=top, Delimiter="/"):
            kinds += [c["Prefix"] for c in pg_.get("CommonPrefixes", [])]
        for kp in kinds:
            for pg_ in s3.get_paginator("list_objects_v2").paginate(Bucket=BUCKET, Prefix=f"{kp}{h}/"):
                for it in pg_.get("Contents", []): yield it["Key"]
def _owned(key, email):
    try: return json.loads(s3.get_object(Bucket=BUCKET, Key=key)["Body"].read()).get("user") == email
    except Exception: return False

def delete_account(email: str) -> dict:
    """Borra todo lo de la persona. Devuelve un resumen de lo borrado. Debe ser idempotente: si algo falla a medias, se puede repetir."""
    email = email.strip().lower(); k = eh(email); out = {"lake": 0, "mongo": 0, "sql": 0}
    # 1) invalida las sesiones YA (todos los servicios rechazan la cookie en ≤5 s) y deja la marca de borrado (solo el hash, nunca el correo)
    c = pg(); cur = c.cursor()
    cur.execute("INSERT INTO account_state(eh, sv, terms, ai, ts) VALUES (%s, 1, NULL, false, now()) ON CONFLICT (eh) DO UPDATE SET sv = account_state.sv + 1, terms = NULL, ai = false, ts = now()", (k,))
    cur.execute("INSERT INTO tombstones(eh, ts) VALUES (%s, now()) ON CONFLICT (eh) DO UPDATE SET ts = now()", (k,))
    forget(email)
    # 2) PostgreSQL
    for t in PG_TABLES:
        cur.execute(f"DELETE FROM {t} WHERE email=%s", (email,)); out["sql"] += max(cur.rowcount, 0)   # nombres de tabla fijos (constante), valores parametrizados
    cur.execute("UPDATE consent_log SET email=NULL, ua=NULL WHERE eh=%s", (k,))   # se conserva la PRUEBA de aceptación (seudonimizada), no el correo
    c.close()
    # 3) MongoDB: todas las colecciones de personas, por correo y por id seudonimizado
    for col in mongo.list_collection_names():
        if col in SHARED_COLS or col.startswith("system."): continue
        out["mongo"] += mongo[col].delete_many({"email": email}).deleted_count
        out["mongo"] += mongo[col].delete_many({"uid": k}).deleted_count
    # 4) Datalake (S3)
    for key in list(_lake_objects(email)):
        if _owned(key, email): s3.delete_object(Bucket=BUCKET, Key=key); out["lake"] += 1
    s3.put_object(Bucket=BUCKET, Key=f"meta/tombstones/{k}.json", Body=json.dumps({"eh": k, "ts": time.time()}).encode())   # lo lee el servicio de copias para re-aplicar borrados al restaurar
    try:   # y una segunda marca FUERA del datalake: si algún día se restaura una copia vieja, los borrados posteriores se re-aplican
        o = offsite()
        if o: o[0].put_object(Bucket=o[1], Key=f"tombstones/{k}.json", Body=json.dumps({"eh": k, "ts": time.time()}).encode())
    except Exception as e: print("[purge] marca externa:", type(e).__name__, flush=True)
    return out

def export_account(email: str) -> dict:
    email = email.strip().lower(); k = eh(email); d = {"exportado": dt.datetime.utcnow().isoformat() + "Z", "cuenta": {"correo": email}, "version_terminos": TERMS_VERSION}
    c = pg(); cur = c.cursor()
    def rows(q):
        cur.execute(q, (email,)); cols = [x[0] for x in cur.description]; return [dict(zip(cols, [v.isoformat() if hasattr(v, "isoformat") else (str(v) if v is not None and not isinstance(v, (int, float, bool)) else v) for v in r])) for r in cur.fetchall()]
    d["encuestas"] = rows("SELECT kind, mood, stress, sleep, dropout, anxiety, support, habits, money, risk, answers, ts FROM surveys WHERE email=%s ORDER BY ts")
    d["emociones"] = rows("SELECT emotion, intensity, problems, source, ts FROM emotion_log WHERE email=%s ORDER BY ts")
    d["juegos"] = rows("SELECT game, completed, secs, ts FROM game_plays WHERE email=%s ORDER BY ts")
    cur.execute("SELECT doc, version, accepted, ts, via FROM consent_log WHERE eh=%s ORDER BY ts", (k,)); d["consentimientos"] = [{"documento": a, "version": b, "aceptado": bool(x), "fecha": t.isoformat() if hasattr(t, "isoformat") else str(t), "via": v} for a, b, x, t, v in cur.fetchall()]
    c.close()
    for name, col, proj in (("chat", "chat", {"_id": 0, "role": 1, "text": 1, "ts": 1, "mode": 1}), ("perfil", "profiles", {"_id": 0, "email": 0}), ("preferencias", "prefs", {"_id": 0, "email": 0}),
                            ("memoria", "memory", {"_id": 0, "email": 0}), ("respuestas_juegos", "game_responses", {"_id": 0, "email": 0}), ("avisos_moderacion", "violations", {"_id": 0, "email": 0})):
        d[name] = json.loads(json_util.dumps(list(mongo[col].find({"email": email}, proj))))
    return d
