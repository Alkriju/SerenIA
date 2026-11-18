import os, json, time, uuid, hashlib, boto3, psycopg2
from botocore.config import Config
from pymongo import MongoClient
E = os.environ
# Datalake en cualquier almacenamiento compatible con S3: SeaweedFS (local/Docker), Cloudflare R2, Backblaze B2, Tigris… Solo cambian las variables S3_*.
BUCKET = E.get("S3_BUCKET", "lake")
s3 = boto3.client("s3", endpoint_url=E["S3_URL"], aws_access_key_id=E["S3_KEY"], aws_secret_access_key=E["S3_SECRET"], region_name=E.get("S3_REGION", "us-east-1"),
                  config=Config(signature_version="s3v4", request_checksum_calculation="when_required", response_checksum_validation="when_required", s3={"addressing_style": "path"}, retries={"max_attempts": 4, "mode": "standard"}, connect_timeout=8, read_timeout=30))
def offsite():
    """Almacenamiento EXTERNO para copias de seguridad (otra cuenta/proveedor que el datalake). None si no está configurado."""
    if not E.get("BACKUP_S3_URL"): return None
    c = boto3.client("s3", endpoint_url=E["BACKUP_S3_URL"], aws_access_key_id=E["BACKUP_S3_KEY"], aws_secret_access_key=E["BACKUP_S3_SECRET"], region_name=E.get("BACKUP_S3_REGION", "us-east-1"),
                     config=Config(signature_version="s3v4", request_checksum_calculation="when_required", response_checksum_validation="when_required", s3={"addressing_style": "path"}, connect_timeout=8, read_timeout=60))
    return c, E["BACKUP_S3_BUCKET"]
mongo = MongoClient(E["MONGO_URL"], maxPoolSize=int(E.get("MONGO_POOL", "5")), serverSelectionTimeoutMS=8000, connectTimeoutMS=8000, retryWrites=True).psico
SERVERLESS = bool(E.get("VERCEL")) or E.get("SERVERLESS") == "1"
def pg():
    c = psycopg2.connect(E["DATABASE_URL"], connect_timeout=10); c.autocommit = True; return c   # Neon: usa la URL "pooled" (con -pooler en el host)
SCHEMA_V = "2026-11-17-pg1"   # sube este valor cuando cambies el esquema: init() solo trabaja cuando la versión guardada es distinta
TABLES = ["CREATE TABLE IF NOT EXISTS users(email TEXT PRIMARY KEY, created TIMESTAMP DEFAULT now())",
      "CREATE TABLE IF NOT EXISTS credentials(email TEXT PRIMARY KEY, salt TEXT, pw_hash TEXT, verified BOOLEAN, code TEXT, code_exp DOUBLE PRECISION, tries INT DEFAULT 0, consent TEXT)",
      "CREATE TABLE IF NOT EXISTS account_state(eh TEXT PRIMARY KEY, sv INT NOT NULL DEFAULT 0, terms TEXT, ai BOOLEAN DEFAULT false, ts TIMESTAMP DEFAULT now())",
      "CREATE TABLE IF NOT EXISTS consent_log(id UUID PRIMARY KEY DEFAULT gen_random_uuid(), eh TEXT NOT NULL, email TEXT, doc TEXT NOT NULL, version TEXT NOT NULL, accepted BOOLEAN NOT NULL, ts TIMESTAMP DEFAULT now(), ip_h TEXT, ua TEXT, via TEXT)",
      "CREATE TABLE IF NOT EXISTS tombstones(eh TEXT PRIMARY KEY, ts TIMESTAMP DEFAULT now())",
      "CREATE TABLE IF NOT EXISTS surveys(id UUID PRIMARY KEY DEFAULT gen_random_uuid(), email TEXT, kind TEXT, mood INT, stress INT, sleep INT, dropout INT, note TEXT, ts TIMESTAMP DEFAULT now(), anxiety DOUBLE PRECISION, support DOUBLE PRECISION, habits DOUBLE PRECISION, money DOUBLE PRECISION, risk TEXT, answers TEXT)",
      "CREATE TABLE IF NOT EXISTS emotion_log(id UUID PRIMARY KEY DEFAULT gen_random_uuid(), email TEXT, emotion TEXT, intensity INT, problems TEXT, ts TIMESTAMP DEFAULT now(), source TEXT)",
      "CREATE TABLE IF NOT EXISTS game_plays(id UUID PRIMARY KEY DEFAULT gen_random_uuid(), email TEXT, game TEXT, ts TIMESTAMP DEFAULT now(), completed BOOLEAN, secs INT)",
      "CREATE TABLE IF NOT EXISTS schema_meta(k TEXT PRIMARY KEY, v TEXT)",
      "CREATE INDEX IF NOT EXISTS consent_eh ON consent_log(eh, ts DESC)", "CREATE INDEX IF NOT EXISTS surveys_email_ts ON surveys(email, ts DESC)",
      "CREATE INDEX IF NOT EXISTS emotion_email_ts ON emotion_log(email, ts DESC)", "CREATE INDEX IF NOT EXISTS games_email_ts ON game_plays(email, ts DESC)"]
_ready = False
def init(force=False):
    """Prepara bucket, índices de Mongo y tablas. Es idempotente y barata: si el esquema ya está en esta versión, solo hace 1 consulta."""
    global _ready
    if _ready and not force: return
    c = pg(); cur = c.cursor()
    try:
        try: cur.execute("SELECT v FROM schema_meta WHERE k='v'"); r = cur.fetchone()
        except Exception: r = None   # la tabla aún no existe
        if r and r[0] == SCHEMA_V and not force: _ready = True; return
        try: s3.create_bucket(Bucket=BUCKET)
        except Exception: pass   # ya existe (o el proveedor ya lo creó: en R2/B2 el bucket se crea en su panel)
        for col, keys_ in (("profiles", [("email", 1)]), ("prefs", [("email", 1)]), ("memory", [("email", 1)]), ("game_responses", [("email", 1), ("ts", -1)]), ("decisions", [("email", 1), ("ts", -1)]), ("chat", [("email", 1), ("ts", 1)])):
            try: mongo[col].create_index(keys_)   # toda lectura es por email: cada usuario solo toca lo suyo, y rápido aunque crezcan los datos
            except Exception: pass
        for col, ttl in (("rl", "exp"), ("pow_used", "exp"), ("lockouts", "exp")):
            try: mongo[col].create_index([(ttl, 1)], expireAfterSeconds=0)   # contadores de límites y captcha: se autoeliminan
            except Exception: pass
        for col in ("violations", "improve_corpus"):
            try: mongo[col].create_index([("email" if col == "violations" else "uid", 1)])
            except Exception: pass
        for q in TABLES: cur.execute(q)
        cur.execute("INSERT INTO schema_meta(k, v) VALUES('v', %s) ON CONFLICT (k) DO UPDATE SET v=EXCLUDED.v", (SCHEMA_V,)); _ready = True
    finally: c.close()
def raw(kind, user, data):  # TODO lo que pasa en la app cae primero al datalake (crudo), particionado por tipo y por usuario
    k = f"raw/{kind}/{hashlib.sha1(user.encode()).hexdigest()[:10]}/{int(time.time()*1000)}-{uuid.uuid4().hex[:6]}.json"
    o = {"kind": kind, "user": user, "ts": time.time(), "data": data}
    s3.put_object(Bucket=BUCKET, Key=k, Body=json.dumps(o).encode())
    if SERVERLESS and kind in INLINE:   # en Vercel el ETL programado puede tardar minutos: lo que la persona necesita ver YA (encuestas, juegos) se transforma al instante
        try:
            import etl; etl.inline(k, o)
        except Exception as e: print("[etl-inline] se deja para la pasada programada:", type(e).__name__, flush=True)
INLINE = {"survey", "game", "user"}
TOPICS = {"estudio": ["parcial", "examen", "nota", "materia", "estudiar", "perder", "cancelar"],
          "ansiedad": ["ansios", "nervios", "pánico", "panico", "angustia"],
          "tristeza": ["triste", "llorar", "solo", "sola", "vacío", "deprim"],
          "sueño": ["dormir", "insomnio", "cansad"], "familia": ["mamá", "papá", "familia", "casa"],
          "enojo": ["enojo", "rabia", "furios"], "soledad": ["soledad", "aislad"], "duelo": ["falleci", "duelo", "ruptura"], "autoexigencia": ["fracaso", "fracasé", "no soy suficiente", "inútil", "inutil", "no valgo"], "dinero": ["plata", "dinero", "pagar", "matrícula", "matricula"]}
def detect(t):
    t = t.lower(); return [k for k, ws in TOPICS.items() if any(w in t for w in ws)]
from security import *   # me, me_nc, new_app, rate, eh… (la seguridad vive en shared/security.py)
import security
security.startup_checks()
def boot():
    """Serverless (Vercel): se inicializa en el momento, una vez por instancia (no hay hilos en segundo plano). Docker: reintenta en un hilo sin bloquear el arranque."""
    if SERVERLESS:
        try: init()
        except Exception as e: print("[init] no se pudo inicializar ahora, se reintentará:", type(e).__name__, flush=True)
        return
    import threading
    def r():
        for _ in range(60):
            try: init(); return
            except Exception: time.sleep(2)
    threading.Thread(target=r, daemon=True).start()
