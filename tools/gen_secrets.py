"""Genera los secretos de producción. Uso:  python tools/gen_secrets.py   y copia los valores a tu .env (NUNCA al código ni a git)."""
import secrets, base64
print("JWT_SECRET=" + secrets.token_hex(32))
print("PSEUDO_KEY=" + secrets.token_hex(32))
print("BACKUP_KEY=" + base64.b64encode(secrets.token_bytes(32)).decode() + "   # guárdala TAMBIÉN en un gestor de contraseñas, fuera del servidor")
print("S3_SECRET=" + secrets.token_urlsafe(32))
print("PG_PASS=" + secrets.token_urlsafe(24))
print("CRON_SECRET=" + secrets.token_urlsafe(32))
print("MONGO_ROOT_PASS=" + secrets.token_urlsafe(24))
