# RESTAURAR:  docker compose run --rm backup python restore.py /backups/serenia-XXXX.tar.gz.enc
# Descifra, recarga PostgreSQL + MongoDB + datalake y RE-APLICA los borrados de cuentas hechos después de esa copia.
import sys, os, json, tarfile, tempfile
from bson import json_util
import bk
from common import s3, mongo, pg, init, eh, BUCKET, offsite
PK = {"users": "email", "credentials": "email", "account_state": "eh", "tombstones": "eh", "consent_log": "id", "surveys": "id", "emotion_log": "id", "game_plays": "id", "schema_meta": "k"}
def upsert(t, cols):
    """INSERT ... ON CONFLICT (clave primaria) DO UPDATE: restaurar dos veces no duplica nada. Los nombres de tabla/columna vienen de la copia propia, se comprueban contra la lista."""
    if t not in PK or PK[t] not in cols or not all(c.replace("_", "").isalnum() for c in cols): raise SystemExit(f"tabla o columnas no reconocidas en la copia: {t}")
    q = lambda x: '"' + x + '"'; sets = ", ".join(f"{q(c)}=EXCLUDED.{q(c)}" for c in cols if c != PK[t]) or f"{q(PK[t])}=EXCLUDED.{q(PK[t])}"
    return f'INSERT INTO {q(t)}({",".join(q(c) for c in cols)}) VALUES ({",".join(["%s"] * len(cols))}) ON CONFLICT ({q(PK[t])}) DO UPDATE SET {sets}'
def main(path):
    k = bk.key(); init()
    with tempfile.NamedTemporaryFile(delete=True) as tmp:
        bk.decrypt(path, tmp.name, k); c = pg(); cur = c.cursor(); n = {"sql": 0, "mongo": 0, "lake": 0}
        with tarfile.open(tmp.name, "r:gz") as tf:
            for m in tf:
                if not m.isfile(): continue
                data = tf.extractfile(m).read()
                if m.name.startswith("sql/"):
                    t = m.name[4:-6]; lines = data.decode().splitlines(); cols = json.loads(lines[0])["columns"]
                    for l in lines[1:]:
                        cur.execute(upsert(t, cols), json.loads(l)); n["sql"] += 1
                elif m.name.startswith("mongo/"):
                    col = m.name[6:-6]
                    for l in data.decode().splitlines():
                        d = json_util.loads(l); mongo[col].replace_one({"_id": d["_id"]}, d, upsert=True); n["mongo"] += 1
                elif m.name.startswith("lake/"): s3.put_object(Bucket=BUCKET, Key=m.name[5:], Body=data); n["lake"] += 1
    # re-aplicar borrados: cuentas que pidieron borrarse DESPUÉS de esta copia no deben "resucitar"
    gone = set()
    tp = os.environ.get("BACKUP_DIR", "/backups") + "/tombstones.jsonl"
    if os.path.exists(tp): gone |= {json.loads(l)["eh"] for l in open(tp) if l.strip()}
    o = offsite()   # marcas guardadas FUERA del datalake (las que se hicieron después de la copia)
    if o:
        for pg_ in o[0].get_paginator("list_objects_v2").paginate(Bucket=o[1], Prefix="tombstones/"): gone |= {it["Key"].split("/")[-1][:-5] for it in pg_.get("Contents", [])}
    cur.execute("SELECT eh FROM tombstones"); gone |= {r[0] for r in cur.fetchall()}
    emails = set()
    for t in ("users", "credentials", "surveys"):
        cur.execute(f"SELECT DISTINCT email FROM {t}"); emails |= {r[0] for r in cur.fetchall() if r[0]}
    for col in ("chat", "profiles", "prefs", "memory"): emails |= set(mongo[col].distinct("email"))
    c.close(); import purge; purged = 0
    for e in emails:
        if eh(e) in gone: purge.delete_account(e); purged += 1
    print("restaurado:", n, "| cuentas borradas re-aplicadas:", purged)
if __name__ == "__main__":
    if len(sys.argv) < 2: raise SystemExit("uso: python restore.py <archivo.tar.gz.enc>")
    main(sys.argv[1])
