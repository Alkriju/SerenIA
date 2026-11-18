# SERVICIO BACKUP: copia automática cada BACKUP_INTERVAL_HOURS (24 h) de PostgreSQL + MongoDB + datalake, cifrada, verificada y con retención.
# Además sincroniza cada pocos minutos la lista de cuentas borradas (solo hashes) para re-aplicar los borrados si algún día se restaura una copia vieja.
import os, glob, json, time, hashlib, tempfile, datetime as dt
import bk
from common import s3, mongo, pg, BUCKET, offsite as ext_store
DIR = os.environ.get("BACKUP_DIR", "/backups"); EVERY = float(os.environ.get("BACKUP_INTERVAL_HOURS", "24")) * 3600; KEEP = float(os.environ.get("BACKUP_KEEP_DAYS", "14")) * 86400
def last():
    f = sorted(glob.glob(f"{DIR}/serenia-*.tar.gz.enc")); return os.path.getmtime(f[-1]) if f else 0
def sync_tombstones():
    p = f"{DIR}/tombstones.jsonl"; have = set()
    if os.path.exists(p): have = {json.loads(l)["eh"] for l in open(p) if l.strip()}
    c = pg(); cur = c.cursor(); cur.execute("SELECT eh FROM tombstones"); new = [r[0] for r in cur.fetchall() if r[0] not in have]; c.close()
    if new:
        with open(p, "a") as f:
            for e in new: f.write(json.dumps({"eh": e, "ts": time.time()}) + "\n")
def offsite(path):
    if not os.environ.get("BACKUP_S3_URL"): return
    import boto3
    c = boto3.client("s3", endpoint_url=os.environ["BACKUP_S3_URL"], aws_access_key_id=os.environ["BACKUP_S3_KEY"], aws_secret_access_key=os.environ["BACKUP_S3_SECRET"])
    c.upload_file(path, os.environ["BACKUP_S3_BUCKET"], os.path.basename(path)); print("copia subida a almacenamiento externo", flush=True)
def run_once(k):
    stamp = dt.datetime.utcnow().strftime("%Y%m%dT%H%M%SZ"); out = f"{DIR}/serenia-{stamp}.tar.gz.enc"
    with tempfile.NamedTemporaryFile(suffix=".tar.gz", delete=True) as tmp:
        cnt = bk.dump(tmp.name, pg, mongo, s3); bk.encrypt(tmp.name, out + ".part", k)
    n = bk.verify(out + ".part", k); os.replace(out + ".part", out); os.chmod(out, 0o600)   # solo existe como copia válida si se pudo releer
    open(out + ".sha256", "w").write(hashlib.sha256(open(out, "rb").read()).hexdigest() + "  " + os.path.basename(out) + "\n")
    for f in glob.glob(f"{DIR}/serenia-*.tar.gz.enc*"):    # retención
        if time.time() - os.path.getmtime(f) > KEEP: os.remove(f)
    json.dump({"ok": True, "file": os.path.basename(out), "ts": time.time(), "counts": cnt, "entries": n}, open(f"{DIR}/last_status.json", "w"))
    offsite(out); print("copia lista:", os.path.basename(out), cnt, flush=True)
def cloud_backup(k=None):
    """Copia para Vercel (no hay disco permanente): vuelca, cifra, VERIFICA y sube a un bucket. Si hay BACKUP_S3_* va a OTRO proveedor (lo recomendado);
    si no, va a backups/ del mismo bucket del datalake (protege de errores de la app, no de perder la cuenta del proveedor). Aplica la retención."""
    k = k or bk.key(); stamp = dt.datetime.utcnow().strftime("%Y%m%dT%H%M%SZ"); name = f"serenia-{stamp}.tar.gz.enc"
    o = ext_store(); cli, bucket, pre = (o[0], o[1], "") if o else (s3, BUCKET, "backups/")
    with tempfile.TemporaryDirectory() as d:
        tar, enc = f"{d}/b.tar.gz", f"{d}/{name}"
        cnt = bk.dump(tar, pg, mongo, s3); bk.encrypt(tar, enc, k); os.remove(tar)
        n = bk.verify(enc, k)   # solo se sube si se pudo releer
        digest = hashlib.sha256(open(enc, "rb").read()).hexdigest()
        cli.upload_file(enc, bucket, pre + name)
    cli.put_object(Bucket=bucket, Key=pre + name + ".sha256", Body=(digest + "  " + name + "\n").encode())
    old = dt.datetime.utcnow() - dt.timedelta(seconds=KEEP); gone = 0
    for page in cli.get_paginator("list_objects_v2").paginate(Bucket=bucket, Prefix=pre + "serenia-"):
        for it in page.get("Contents", []):
            if it["LastModified"].replace(tzinfo=None) < old: cli.delete_object(Bucket=bucket, Key=it["Key"]); gone += 1
    st = {"ok": True, "file": name, "ts": time.time(), "counts": cnt, "entries": n, "where": "externo" if o else "mismo bucket", "deleted_old": gone}
    s3.put_object(Bucket=BUCKET, Key="meta/backup_status.json", Body=json.dumps(st).encode()); return st
if __name__ == "__main__":
    try: k = bk.key()
    except SystemExit as e:    # sin llave NO se hacen copias (nunca sin cifrar); se avisa y se espera en vez de reiniciarse sin parar
        while True: print("[backup] COPIAS DESACTIVADAS:", e, flush=True); time.sleep(3600)
    os.makedirs(DIR, exist_ok=True); retry = 0
    while True:
        try:
            sync_tombstones()
            if time.time() - last() >= EVERY and time.time() >= retry: run_once(k)
        except Exception as e:
            print("[backup] error:", type(e).__name__, str(e)[:200], flush=True); retry = time.time() + 900
            try: json.dump({"ok": False, "ts": time.time(), "error": type(e).__name__}, open(f"{DIR}/last_status.json", "w"))
            except Exception: pass
        time.sleep(300)
