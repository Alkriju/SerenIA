# SEED: carga la base de conocimiento psicológico al DATALAKE (raw/knowledge). El ETL la pasa a MongoDB.
# Idempotente: ensure() solo escribe si el contenido cambió (lo marca en meta/seed.json). Lo usa el arranque en Docker y el ETL en la nube.
from common import *
import glob, json, os
def load_kb(): return [json.load(open(f, encoding="utf-8")) for f in sorted(glob.glob(os.path.join(os.path.dirname(__file__), "knowledge", "*.json")))]   # cada tema es un archivo .json real
def ensure(kb=None):
    kb = load_kb() if kb is None else kb
    sig = hashlib.sha1(json.dumps(kb, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    try:
        if json.loads(s3.get_object(Bucket=BUCKET, Key="meta/seed.json")["Body"].read()).get("sig") == sig: return 0
    except Exception: pass
    for k in kb:  # clave determinista: si el contenido no cambió, no se duplica en el datalake
        h = hashlib.sha1(json.dumps(k, sort_keys=True).encode()).hexdigest()[:8]
        s3.put_object(Bucket=BUCKET, Key=f"raw/knowledge/system/{k['id']}-{h}.json", Body=json.dumps({"kind": "knowledge", "user": "system", "ts": time.time(), "data": k}, ensure_ascii=False).encode())
    s3.put_object(Bucket=BUCKET, Key="meta/seed.json", Body=json.dumps({"sig": sig, "n": len(kb), "ts": time.time()}).encode()); return len(kb)
if __name__ == "__main__":
    for i in range(90):  # espera a que el almacenamiento S3 y PostgreSQL estén realmente listos
        try: s3.list_buckets(); init(); break
        except Exception as e:
            if i % 10 == 0: print("esperando al almacenamiento S3 / PostgreSQL…", type(e).__name__, flush=True)
            time.sleep(2)
    else: raise SystemExit("S3/PostgreSQL no respondieron a tiempo")
    print("conocimiento enviado al datalake:", ensure())
