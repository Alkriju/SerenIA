# Cuestionarios (shared/questions.json) y puntajes. Fuente única para el servicio survey (formulario) y el ETL (puntajes).
# Convención 1-5 por dimensión: mood/sleep/habits/support = 5 es BUENO; anxiety/stress/dropout/money = 5 es ALTO.
import json, os
QS = json.load(open(os.path.join(os.path.dirname(__file__), "questions.json"), encoding="utf-8"))
def flat(kind): return [q for s in QS["kinds"][kind]["sections"] for q in s["questions"]]
def clean(kind, answers):  # valida contra el cuestionario: descarta ids desconocidos y valores fuera de rango, recorta textos
    out = {}
    for q in flat(kind):
        v = (answers or {}).get(q["id"])
        if v is None or v == "": continue
        if q["type"] == "scale" and isinstance(v, (int, float)) and 1 <= v <= 5: out[q["id"]] = int(v)
        elif q["type"] == "choice" and v in q["options"]: out[q["id"]] = v
        elif q["type"] == "text" and isinstance(v, str): out[q["id"]] = v.strip()[:600]
    return out
def alertas(sc):  # indicadores en zona de cuidado (los mismos para el puntaje y para el historial)
    f = []
    if sc.get("mood", 3) <= 2: f.append("ánimo bajo")
    if sc.get("anxiety", 1) >= 3.5: f.append("ansiedad alta")
    if sc.get("stress", 1) >= 3.5: f.append("estrés académico alto")
    if sc.get("sleep", 5) <= 2: f.append("mal sueño")
    if sc.get("support", 5) <= 2: f.append("poco apoyo social")
    if sc.get("dropout", 1) >= 3.5: f.append("riesgo de deserción")
    if sc.get("money", 1) >= 4: f.append("preocupación económica")
    return f
def seguridad(v):  # SOLO la pregunta de seguridad decide si se muestra el aviso de crisis (123 / Línea 106)
    return "alto" if v in ("Varias veces", "Ahora mismo") else "medio" if v == "Alguna vez" else "bajo"
def nivel(n, seg="bajo"):  # NIVEL DE ATENCIÓN: 0-1 indicadores = bajo, 2-3 = medio, 4 o más = alto. La seguridad puede subirlo, nunca bajarlo.
    lvl = "alto" if n >= 4 else "medio" if n >= 2 else "bajo"
    return "alto" if seg == "alto" else ("medio" if seg == "medio" and lvl == "bajo" else lvl)
def score(kind, answers):
    """-> {dim: 1..5, 'risk': nivel de atención alto|medio|bajo, 'seguridad': alto|medio|bajo, 'flags': [...]}"""
    acc = {}
    for q in flat(kind):
        if q["type"] == "scale" and q["id"] in answers:
            v = answers[q["id"]]; acc.setdefault(q["dim"], []).append(6 - v if q.get("rev") else v)
    sc = {d: round(sum(v) / len(v), 1) for d, v in acc.items()}
    flags = alertas(sc); seg = seguridad(answers.get("seguridad")); n = len(flags)
    if seg == "alto": flags.insert(0, "pensamientos de hacerse daño")
    sc["seguridad"] = seg; sc["risk"] = nivel(n, seg); sc["flags"] = flags; return sc
