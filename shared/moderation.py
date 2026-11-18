"""Filtro de contenido de SerenIA, basado en las categorías de las normas comunitarias de las redes sociales:
explotación de menores, contenido sexual con animales, violencia sexual, amenazas, armas/explosivos, drogas, odio, acoso, fraude y desnudez/sexo explícito.
Bloquea lo que PROMUEVE, SOLICITA o ATACA. Una víctima que cuenta lo que vivió NO se bloquea: ahí SerenIA acompaña."""
import re, time, unicodedata
from common import raw, mongo
def norm(t): return re.sub(r"\s+", " ", "".join(c for c in unicodedata.normalize("NFD", t.lower()) if unicodedata.category(c) != "Mn"))
W = r"(?:\w+\W+){0,4}"
def R(p): return re.compile(p)
SAFE_CTX = R(r"\b(?:me|nos)\s+(?:tocaron|toco|violaron|violo|abusaron|abuso|acosaron|acoso|manosearon|manoseo|forzaron|obligaron)\b|\bfui\s+(?:abusad|violad|acosad|manosead)|\babus(?:o|aron)\s+de\s+mi\b|\b(?:denunci\w+|reportar|sospech\w+|me preocupa)\b")
NINO = r"(?:ninos?|ninas?|menores?|infantes?|bebes?|criaturas?|adolescentes?|colegiales?|chiquit\w+)"
RULES = [
 ("menores", R(r"(?:sexo|sexual\w*|porn\w*|desnud\w*|erotic\w*|violar|violacion|abusar|abuso sexual|manosear|fotos? intim\w*|nudes?)\W+" + W + NINO + r"\b|\b" + NINO + r"\W+" + W + r"(?:desnud\w*|porn\w*|sexo|sexual\w*|erotic\w*)\b"),
  "No puedo aceptar contenido que sexualice a menores: está prohibido en SerenIA. Si sabes de un menor en peligro, llama a la Línea 141 (ICBF) o al 123.", True),
 ("zoofilia", R(r"zoofil\w*|bestialism\w*|sexo con (?:un |una |mi |el |la )?(?:animal\w*|perr\w*|gat\w*|caball\w*|mascota\w*|vaca\w*|cabra\w*|yegua\w*)|(?:violar|follar|penetrar|tener sexo)\W+" + W + r"(?:perr\w*|gat\w*|caball\w*|animal\w*|mascota\w*|vaca\w*|cabra\w*|yegua\w*)"),
  "El contenido sexual con animales no está permitido en SerenIA. Si quieres hablar de algo que te pasa, aquí estoy.", False),
 ("violencia_sexual", R(r"(?:quiero|voy a|vamos a|como|ayudame a|ensename a|tips para|trucos para|ganas de|me gustaria)\W+" + W + r"(?:violar(?! (?:la |las |el |los |mi |tu |su )?(?:ley|leyes|norma|normas|regla|reglas|privacidad|derechos?|contrato|protocolo|acuerdo))|abusar sexualmente|drogar a (?:una|un|mi)|forzar a (?:una|un|mi)|acosar sexualmente)|(?:las|los) (?:mujeres|ninas|ninos)\W+(?:se )?(?:merecen|piden|buscan)\W+(?:ser )?(?:violad\w+|abusad\w+)|violar a (?:mi|una|un|esa|ese|la|el|las|los)\b"),
  "No puedo ayudarte con eso: promover o facilitar violencia sexual está prohibido en SerenIA. Si viviste algo así o conoces a alguien que sí, puedo escucharte y orientarte.", True),
 ("violencia", R(r"(?:voy a|vamos a|quiero|te voy a|ojala|deberian|hay que)\W+" + W + r"(?:matar(?!me\b|nos\b|\W+(?:el |al )?tiempo|\W+(?:las )?ganas|\W+el aburrimiento)|asesinar|apunalar|degollar|torturar|quemar vivo|disparar a|pegarle un tiro)\w*"),
  "No se permiten amenazas ni incitación a la violencia. Si estás muy enojado/a, puedo ayudarte a calmarte o a decir lo que sientes de otra forma.", False),
 ("peligro", R(r"(?:como|ayudame a|quiero|ensename a|pasos para|instrucciones para)\W+" + W + r"(?:hacer|fabricar|construir|armar|preparar|conseguir)\W+" + W + r"(?:bomba\W+(?:casera|explosiva|molotov|de tiempo|atomica|nuclear)|explosiv\w+|molotov|arma\w* (?:casera|de fuego)|veneno\w*|napalm|ricina|sarin)"),
  "No puedo dar instrucciones para fabricar armas, explosivos o sustancias peligrosas.", False),
 ("drogas", R(r"(?:fabricar|cocinar|producir|sintetizar|vender|comercializar|traficar|distribuir|montar un negocio de|conseguir proveedor de)\W+" + W + r"(?:droga\w*|cocaina|marihuana|perico|basuco|bazuco|metanfetamina|crack|heroina|lsd|extasis|fentanilo|armas?|municion\w*|popper|tusi)"),
  "No puedo ayudarte con la fabricación, venta o tráfico de drogas o armas: va contra las normas de la comunidad de SerenIA. Si el consumo te preocupa, puedo orientarte.", False),
 ("odio", R(r"\b(?:sudaca|negrata|nigg\w+|marimach\w*|travelo|mongolic\w*|gitanada|trolo|indio (?:de mierda|patarrajada|sucio)|negro (?:de mierda|sucio|hijueputa)|judio (?:de mierda|sucio|asqueroso)|moro (?:de mierda|sucio)|gay (?:de mierda|asqueroso)|maricon (?:de mierda|asqueroso)|venecos? (?:de mierda|hijueputas?|asquerosos?))\b|(?:los|las|todos los|todas las)\s+(?:negros|indios|indigenas|gays|homosexuales|lesbianas|trans|transexuales|venezolanos|migrantes|inmigrantes|judios|musulmanes|gitanos|discapacitados|mujeres|haitianos|afros)\W+(?:son|deberian|merecen)\W+" + W + r"(?:basura|animales|plaga|escoria|inferiores|parasit\w+|enfermos|morir\w*|exterminad\w*|expulsad\w*|ratas|cucarachas|una mierda)"),
  "Este mensaje ataca a personas por su origen, género, orientación, religión o discapacidad. El discurso de odio no está permitido en SerenIA.", False),
 ("acoso", R(r"\b(?:matate|suicidate|muerete|ojala\s+(?:te|se)\s+mu(?:eras?|era|eran)|deberias\s+(?:morirte|matarte))\b"),
  "No se permite acosar ni desearle mal a otras personas. Si algo te enoja, cuéntamelo con otras palabras.", False),
 ("fraude", R(r"(?:como|ayudame a|quiero|ensename a)\W+" + W + r"(?:estafar|hackear|clonar (?:una )?tarjeta\w*|suplantar identidad|phishing|robar (?:una )?cuenta|falsificar (?:un |una |mi )?(?:titulo|diploma|firma|certificado|cedula|nota\w*))"),
  "No puedo ayudar con estafas, hackeo, suplantación o falsificación.", False),
 ("sexual_explicito", R(r"(?:vendo|compro|vender|comprar|pasame|envia(?:me)?|intercambio|cambio)\W+" + W + r"(?:nudes?|fotos? (?:intimas|desnud\w+|sin ropa)|packs?|videos? porno)|(?:escribe|dame|cuentame|describeme|quiero|hazme)\W+" + W + r"(?:porno\w*|pornograf\w*|escena sexual|relato erotico|sexting|historia erotica)"),
  "No se permite compartir ni pedir contenido sexual explícito en SerenIA.", False)]
HEAD = "Este mensaje no cumple las normas de la comunidad de SerenIA. "
import os
STRIKES = int(os.environ.get("MOD_STRIKES", "3"))      # mensajes no permitidos que activan la pausa (0 = nunca pausar, útil para pruebas)
WINDOW = int(os.environ.get("MOD_WINDOW", "900"))      # ventana para contarlos (15 min)
PAUSE = int(os.environ.get("MOD_PAUSE", "300"))        # duración de la pausa desde el último (5 min)
def pausa(left): return f"Hemos recibido varios mensajes que no cumplen las normas de la comunidad, así que pausamos el chat unos minutos (faltan unos {max(1, round(left / 60))} min). Cuando vuelvas, aquí estaré para escucharte con respeto."
def check(text):
    """-> None si está bien, o (categoría, mensaje para el usuario)."""
    t = norm(str(text or ""))
    if not t: return None
    for cat, rx, msg, victim_ok in RULES:
        if rx.search(t):
            if victim_ok and SAFE_CTX.search(t): continue   # víctima o persona que denuncia: se le acompaña, no se bloquea
            return cat, HEAD + msg
    return None
def strike(u, cat, text, src):
    mongo.violations.insert_one({"email": u, "ts": time.time(), "cat": cat, "src": src})
    raw("moderation", u, {"cat": cat, "src": src, "text": str(text)[:200]})   # queda en el datalake para revisión
def pause_left(u):
    """Segundos que faltan de pausa (0 = sin pausa). Mientras dura, los intentos NO suman más: la pausa termina PAUSE segundos después del último mensaje no permitido."""
    if STRIKES <= 0: return 0
    rows = list(mongo.violations.find({"email": u, "ts": {"$gt": time.time() - WINDOW}}, {"ts": 1}).sort("ts", -1).limit(STRIKES))
    return max(0, int(rows[0]["ts"] + PAUSE - time.time())) if len(rows) >= STRIKES else 0
