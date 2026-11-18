"""Copia de seguridad cifrada (AES-256-GCM por bloques) de PostgreSQL + MongoDB + datalake. Se importa desde backup.py y restore.py."""
import os, io, json, time, tarfile, struct, hashlib, base64, tempfile, datetime as dt
from bson import json_util
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
BUCKET = os.environ.get("S3_BUCKET", "lake")
MAGIC, CH = b"SRNBK1\n", 1 << 20
SKIP_MONGO = {"rl", "pow_used", "lockouts"}          # contadores temporales: no se respaldan
def key():
    k = os.environ.get("BACKUP_KEY", "")
    try: b = base64.b64decode(k, validate=True)
    except Exception: b = b""
    if len(b) != 32: raise SystemExit("BACKUP_KEY debe ser 32 bytes en base64:  openssl rand -base64 32   (guárdala APARTE: sin ella no se pueden restaurar las copias)")
    return b
def encrypt(src, dst, k):
    a, pre = AESGCM(k), os.urandom(8)
    with open(src, "rb") as f, open(dst, "wb") as o:
        o.write(MAGIC + pre); n = 0; buf = f.read(CH)
        while True:
            nxt = f.read(CH); last = not nxt
            ct = a.encrypt(pre + struct.pack(">I", n), buf, struct.pack(">IB", n, last))   # el contador y la marca de "último" van autenticados: no se pueden reordenar ni truncar
            o.write(struct.pack(">I", len(ct)) + ct); n += 1
            if last: break
            buf = nxt
def decrypt(src, dst, k):
    a = AESGCM(k)
    with open(src, "rb") as f, open(dst, "wb") as o:
        if f.read(len(MAGIC)) != MAGIC: raise ValueError("no es una copia de SerenIA")
        pre, n, seen_last = f.read(8), 0, False
        while True:
            h = f.read(4)
            if not h: break
            if seen_last: raise ValueError("datos tras el último bloque")
            ln = struct.unpack(">I", h)[0]; ct = f.read(ln)
            if len(ct) != ln: raise ValueError("copia truncada")
            nxt_peek = f.read(1); last = not nxt_peek
            if nxt_peek: f.seek(-1, 1)
            o.write(a.decrypt(pre + struct.pack(">I", n), ct, struct.pack(">IB", n, last))); n += 1; seen_last = last
        if not seen_last: raise ValueError("copia truncada")
def _add(tf, name, data: bytes):
    ti = tarfile.TarInfo(name); ti.size = len(data); ti.mtime = int(time.time()); tf.addfile(ti, io.BytesIO(data))
def tables(cur):
    cur.execute("SELECT table_name FROM information_schema.tables WHERE table_schema='public' ORDER BY 1"); return [r[0] for r in cur.fetchall()]
def dump(tar_path, pg, mongo, s3):
    cnt = {"sql": {}, "mongo": {}, "lake": 0}
    with tarfile.open(tar_path, "w:gz") as tf:
        c = pg(); cur = c.cursor()
        for t in tables(cur):
            cur.execute(f'SELECT * FROM "{t}"'); cols = [d[0] for d in cur.description]; rows = cur.fetchall()
            _add(tf, f"sql/{t}.jsonl", ("\n".join([json.dumps({"columns": cols})] + [json.dumps(list(r), default=str) for r in rows]) + "\n").encode()); cnt["sql"][t] = len(rows)
        c.close()
        for col in mongo.list_collection_names():
            if col in SKIP_MONGO or col.startswith("system."): continue
            docs = list(mongo[col].find({})); _add(tf, f"mongo/{col}.jsonl", "".join(json_util.dumps(d) + "\n" for d in docs).encode()); cnt["mongo"][col] = len(docs)
        for top in ("raw/", "meta/"):    # processed/ y failed/ son marcas derivadas: el ETL las regenera desde raw/
            for pg_ in s3.get_paginator("list_objects_v2").paginate(Bucket=BUCKET, Prefix=top):
                for it in pg_.get("Contents", []): _add(tf, "lake/" + it["Key"], s3.get_object(Bucket=BUCKET, Key=it["Key"])["Body"].read()); cnt["lake"] += 1
        _add(tf, "manifest.json", json.dumps({"app": "serenia", "created": dt.datetime.utcnow().isoformat() + "Z", "counts": cnt}).encode())
    return cnt
def verify(path, k):
    """Descifra y recorre toda la copia: comprueba que se puede leer (si no, la copia no sirve)."""
    with tempfile.NamedTemporaryFile(delete=True) as tmp:
        decrypt(path, tmp.name, k)
        with tarfile.open(tmp.name, "r:gz") as tf: names = tf.getnames()
    if "manifest.json" not in names: raise ValueError("copia sin manifiesto")
    return len(names)
