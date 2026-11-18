"""Revisa que los textos legales estén listos para publicar.  python tools/check_legal.py [--prod]
 - versión de términos igual en legal.json y en el backend; datos de la empresa completos; aviso de borrador apagado (con --prod)."""
import json, os, re, sys
R = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
L = json.load(open(os.path.join(R, "frontend/legal/legal.json"), encoding="utf-8")); prod = "--prod" in sys.argv; errs = []
m = re.search(r'TERMS_VERSION", "([^"]+)"', open(os.path.join(R, "shared/security.py"), encoding="utf-8").read())
if not m or m.group(1) != L["version"]: errs.append(f"versión distinta: legal.json={L['version']} backend={m and m.group(1)}")
empty = [k for k, v in L["company"].items() if not str(v).strip() and not k.startswith("dpo_")]
if empty: errs.append("faltan datos de la empresa en frontend/legal/legal.json → company: " + ", ".join(empty))
for p in L["providers"]:
    if p.get("active") and "[COMPLETAR" in json.dumps(p, ensure_ascii=False): errs.append("proveedor sin completar: " + p["name"])
if prod and L.get("draft"): errs.append('"draft": true → pon false cuando un asesor legal haya revisado los documentos')
for f in sorted(os.listdir(os.path.join(R, "frontend/legal"))):   # [COMPLETAR] que NO se rellena solo desde legal.json (plazos, jurisdicción…): hay que editarlos en el HTML (o en tools del generador)
    if not f.endswith(".html"): continue
    t = re.sub(r'<[^>]*data-f=[^>]*>\s*<mark class="todo">[^<]*</mark>', "", open(os.path.join(R, "frontend/legal", f), encoding="utf-8").read())
    for x in sorted(set(re.findall(r"\[COMPLETAR[^\]]*\]", t))):
        if prod: errs.append(f"{f}: texto pendiente {x}")
print("\n".join("✗ " + e for e in errs) if errs else "Textos legales listos ✔"); sys.exit(1 if errs and prod else 0)
