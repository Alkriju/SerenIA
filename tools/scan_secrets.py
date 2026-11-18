"""Busca claves escondidas en el código (todo menos .env*, node_modules y tests). Sale con código 1 si encuentra algo: úsalo antes de cada commit/despliegue.  python tools/scan_secrets.py"""
import os, re, sys
R = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PATS = {"Google/Gemini API key": r"AIza[0-9A-Za-z_\-]{30,}", "OpenAI/DeepSeek/Qwen key (sk-…)": r"\bsk-[A-Za-z0-9_\-]{20,}", "Groq key": r"\bgsk_[A-Za-z0-9]{20,}", "GitHub token": r"\bgh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{30,}",
        "Anthropic key": r"sk-ant-[A-Za-z0-9_\-]{20,}", "AWS access key": r"\bAKIA[0-9A-Z]{16}\b", "Clave privada": r"-----BEGIN (RSA |EC |OPENSSH )?PRIVATE KEY-----", "Slack token": r"xox[abprs]-[A-Za-z0-9\-]{10,}",
        "Asignación sospechosa": r"(?i)\b(password|passwd|secret|api[_-]?key|token)\b\s*[:=]\s*['\"][^'\"\s]{12,}['\"]"}
SKIP_DIRS = {".git", "node_modules", "__pycache__", "tests", "fonts", ".pytest_cache"}
OK_HINT = re.compile(r"(?i)(example|ejemplo|changeme|cambia|xxxx|<|\$\{|environ|E\[|E\.get|test)")
bad = 0
for d, ds, fs in os.walk(R):
    ds[:] = [x for x in ds if x not in SKIP_DIRS]
    for f in fs:
        if f.startswith(".env") and not f.endswith(".example"): continue
        if f.endswith((".woff2", ".png", ".jpg", ".zip", ".pyc", ".enc")): continue
        p = os.path.join(d, f)
        try: t = open(p, encoding="utf-8").read()
        except Exception: continue
        for n, rx in PATS.items():
            for m in re.finditer(rx, t):
                line = t[t.rfind("\n", 0, m.start()) + 1: t.find("\n", m.end())]
                if OK_HINT.search(line) and n == "Asignación sospechosa": continue
                bad += 1; print(f"[{n}] {os.path.relpath(p, R)}: {line.strip()[:90]}")
# los .env reales no deben estar versionados
gi = open(os.path.join(R, ".gitignore")).read() if os.path.exists(os.path.join(R, ".gitignore")) else ""
for need in (".env", ".env.chat", ".env.etl"):
    if need not in gi.split(): bad += 1; print(f"[.gitignore] falta la línea '{need}'")
print("Sin secretos en el código ✔" if not bad else f"{bad} hallazgo(s)"); sys.exit(1 if bad else 0)
