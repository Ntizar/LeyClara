"""Respuesta: componer SIEMPRE con texto literal del BOE.

Dos modos:

  * `extractivo` (por defecto, 0 tokens): no hay generacion. Se recuperan
    preceptos y se citan literalmente. La alucinacion es imposible por
    construccion, no por confianza en el modelo.
  * `llm` (opcional, gasta tokens): el modelo redacta un borrador con
    afirmaciones estructuradas y el GATE decide si pasa o se rechaza.

En los dos modos la regla es la misma: lo que el usuario lee es texto del BOE
verificado, o el gate lo bloquea.
"""

import json
import os
import re
import sys
import urllib.request

from . import config as cfg_mod
from . import recuperar
from .verificar import Gate

NUM_PALABRA = {
    "un": 1, "uno": 1, "una": 1, "dos": 2, "tres": 3, "cuatro": 4, "cinco": 5,
    "seis": 6, "siete": 7, "ocho": 8, "nueve": 9, "diez": 10, "once": 11, "doce": 12,
    "trece": 13, "catorce": 14, "quince": 15, "dieciseis": 16, "dieciséis": 16,
    "diecisiete": 17, "dieciocho": 18, "diecinueve": 19, "veinte": 20,
    "veintiuno": 21, "veintidos": 22, "veintidós": 22, "veintitres": 23,
    "veintitrés": 23, "veinticuatro": 24, "veinticinco": 25, "veintiseis": 26,
    "veintiséis": 26, "veintisiete": 27, "veintiocho": 28, "veintinueve": 29,
    "treinta": 30, "cuarenta": 40, "cincuenta": 50, "sesenta": 60, "noventa": 90,
    "ciento": 100,
}
# Los plazos legales se escriben tanto con cifra ("20 días") como con letra
# ("cinco días"): en la LEC el art. 246 dice "cinco días" y no "5 días". Un detector
# que solo mire cifras se pierde justo los plazos procesales.
RE_PLAZO = re.compile(
    r"\b(\d{1,3}|" + "|".join(sorted(NUM_PALABRA, key=len, reverse=True)) + r")\s*"
    r"(días?|dias?|meses?|años?|anos?|horas?|semanas?)\b", re.I)

NOTA_PLAZO = ("⏱ plazo detectado: el cómputo (día inicial, días hábiles o naturales, "
              "suspensiones) NO lo calcula LeyClara. Debe verificarse en el precepto.")

# --- Coincidencia de TIPO DE DATO -------------------------------------------
# Una pregunta pide un dato de un tipo (importe, plazo, porcentaje). Si el precepto
# citado no contiene ese tipo de dato, NO responde a lo que se pregunta: es un falso
# positivo con cita literal. Caso real que lo motivó: "importe de la tasa del DNI"
# devolvía el art. 648 de la LEC (subasta electrónica) porque "tasa" casaba.
RE_IMPORTE = re.compile(r"\d[\d.,]*\s*(?:euros?|€|eur\b)", re.I)
RE_PORCENTAJE = re.compile(r"\d[\d.,]*\s*(?:%|por ?ciento|por ciento)", re.I)


def _plano(s):
    """Minúsculas sin tildes. OJO: solo para COMPARAR, nunca para citar."""
    import unicodedata
    s = unicodedata.normalize("NFKD", (s or "").lower())
    return "".join(c for c in s if not unicodedata.combining(c))


def tipo_dato(pregunta):
    """Qué tipos de dato pide la pregunta. Vacío = no pide un dato concreto."""
    p = " " + _plano(pregunta) + " "
    tipos = set()
    if re.search(r"\b(importe|cuanto cuesta|cuanto vale|precio|cuantia|tarifa|tasa)\b", p):
        tipos.add("importe")
    if re.search(r"\b(plazo|caducidad|prescripcion|cuantos dias|cuanto tiempo|"
                 r"en que plazo|desde cuando)\b", p):
        tipos.add("plazo")
    if re.search(r"\b(porcentaje|tipo de interes|recargo|interes legal)\b", p):
        tipos.add("porcentaje")
    return tipos


def contiene_dato(tipos, texto):
    """¿El precepto contiene realmente el tipo de dato pedido?"""
    if not tipos:
        return True
    t = texto or ""
    if "importe" in tipos and RE_IMPORTE.search(t):
        return True
    if "porcentaje" in tipos and RE_PORCENTAJE.search(t):
        return True
    if "plazo" in tipos and RE_PLAZO.search(t):
        return True
    return False


def url_precepto(norma, bloque=""):
    """URL oficial de una norma (y de su articulo si el ancla es numerica).

    Una sola fuente para todas las superficies: CLI, API, chat e informe. Se ancla
    solo cuando el id de bloque es `a245` o `art1902`; los bis/ter usan otra
    numeracion de ancla y un enlace roto es peor que un enlace a la norma.
    """
    base = f"https://www.boe.es/buscar/act.php?id={norma}"
    return f"{base}#{bloque}" if re.fullmatch(r"(?:a|art)\d+", bloque or "") else base


def _con_url(afirmaciones):
    """Anade `url` a cada afirmacion: la ley citada SIEMPRE va enlazada."""
    for a in afirmaciones:
        a["url"] = url_precepto(a.get("norma", ""), a.get("bloque", ""))
    return afirmaciones


def extraer_cita(texto, max_chars=600):
    """Corta el texto en frontera de frase para que la cita sea legible y LITERAL.

    Importante: no se añade «…» ni ningún carácter. Cualquier añadido dejaría de
    ser una subcadena del precepto y el gate la bloquearía con razón (pasó: 2 citas
    bloqueadas por el propio recorte). Los puntos suspensivos son de presentación,
    no de la cita.
    """
    t = texto.strip()
    if len(t) <= max_chars:
        return t
    corte = t[:max_chars]
    ultimo = max(corte.rfind(". "), corte.rfind(";\n"), corte.rfind(".\n"))
    if ultimo > max_chars * 0.5:
        return corte[: ultimo + 1].strip()
    return corte.rsplit(" ", 1)[0].strip()


def detectar_plazos(texto):
    vistos, out = set(), []
    for crudo, unidad in RE_PLAZO.findall(texto):
        crudo = crudo.lower()
        n = int(crudo) if crudo.isdigit() else NUM_PALABRA.get(crudo)
        if n is None:
            continue
        clave = f"{n} {unidad.lower().rstrip('s')}"
        if clave not in vistos:
            vistos.add(clave)
            out.append({"cantidad": n, "unidad": unidad.lower().rstrip("s"),
                        "literal": f"{crudo} {unidad}"})
    return out


def _fuente(c):
    return {
        "norma": c["norma"], "titulo_norma": c["titulo_norma"], "rango": c["rango"],
        "bloque": c["bloque"], "titulo_bloque": c["titulo_bloque"],
        "url": c["url"], "score": c["score"],
        "n_versiones": c["n_versiones"], "fecha_vigencia": c["fecha_vigencia"],
        "rrf": c.get("rrf"), "nombrada": c.get("nombrada", False),
    }


def grupos_por_norma(fuentes):
    """Agrupa los preceptos por norma: la respuesta juridica se lee por cuerpos legales."""
    orden, acc = [], {}
    for f in fuentes:
        if f["norma"] not in acc:
            acc[f["norma"]] = {"norma": f["norma"], "titulo_norma": f["titulo_norma"],
                               "url": f["url"], "articulos": []}
            orden.append(f["norma"])
        acc[f["norma"]]["articulos"].append(
            {"bloque": f["bloque"], "titulo_bloque": f["titulo_bloque"]})
    return [acc[n] for n in orden]


def puentes(cfg, cands):
    """Puentes entre normas: cuando el texto citado de una norma nombra otra.

    Esto es lo que hace util el salto entre cuerpos legales, y es DETERMINISTA:
    no lo deduce el modelo, se lee del texto oficial. Ej.: el art. X de la Ley de
    Costas dice "de conformidad con el Codigo Civil" -> puente Costas -> CC.
    """
    import unicodedata as _u

    def plano(s):
        s = _u.normalize("NFKD", (s or "").lower())
        return "".join(c for c in s if not _u.combining(c))

    salida = []
    for c in cands:
        texto = plano(c["texto"])
        for n in cfg["normas"]:
            if n["id"] == c["norma"]:
                continue
            for a in n.get("alias", []):
                al = plano(a)
                if len(al) < 3:
                    continue
                # Limites de palabra OBLIGATORIOS: sin esto "CC" casa dentro de
                # "accion" y se inventan puentes que no existen.
                m = re.search(rf"(?<![a-z0-9]){re.escape(al)}(?![a-z0-9])", texto)
                if m:
                    ini = max(0, m.start() - 90)
                    salida.append({
                        "desde": c["norma"], "desde_art": c["bloque"],
                        "hacia": n["id"], "hacia_nombre": n["nombre"],
                        "evidencia": "…" + texto[ini: m.end() + 120].strip(),
                    })
                    break
    vistos, out = set(), []
    for p in salida:
        k = (p["desde"], p["desde_art"], p["hacia"])
        if k not in vistos:
            vistos.add(k)
            out.append(p)
    return out


def seleccionar(cands, nombradas, max_citas):
    """Elige que preceptos se muestran, garantizando cuota si la pregunta nombra varias normas.

    Preguntar "como aplica X de la Ley de Costas en el Codigo Civil" y recibir tres
    articulos de Costas es una respuesta incompleta: el usuario pide el ENLACE. Si hay
    N normas nombradas, cada una aporta al menos un precepto antes de rellenar.
    """
    if len(nombradas) < 2:
        return cands[:max_citas]
    cupo = max(1, max_citas // len(nombradas))
    elegidos, vistos = [], set()
    for nid in nombradas:
        n = 0
        for c in cands:
            if c["norma"] == nid and (c["norma"], c["bloque"]) not in vistos and n < cupo:
                elegidos.append(c)
                vistos.add((c["norma"], c["bloque"]))
                n += 1
    for c in cands:
        if len(elegidos) >= max_citas:
            break
        if (c["norma"], c["bloque"]) not in vistos:
            elegidos.append(c)
            vistos.add((c["norma"], c["bloque"]))
    return elegidos[:max_citas]


def _no_consta(cfg, pregunta, nombradas, notas_extra=None):
    """Abstención INFORMADA: no solo dice que no consta, dice qué falta y qué
    norma del BOE podría aplicarlo. Un "no consta" ciego es un falso negativo
    disfrazado: el usuario no sabe si el dato no existe o si no lo tenemos."""
    try:
        from . import existencias
        candidatas = existencias.sugerir_amplio(cfg, pregunta)
    except Exception:  # noqa: BLE001
        candidatas = []
    notas = list(notas_extra or [])
    notas.append("No se ha localizado precepto aplicable en el corpus indexado. "
                 "Esto NO significa que no exista la norma: significa que no está "
                 "en las normas cargadas. Ver config.json → normas.")
    if candidatas:
        notas.insert(0, "Existen en el BOE normas que podrían aplicarse y NO están "
                        "indexadas (ver «candidatas»). Sin su texto no se puede citar "
                        "nada: hay que cargarlas para responder.")
    return {
        "pregunta": pregunta, "modo": "extractivo", "veredicto": "NO CONSTA",
        "afirmaciones": [], "fuentes": [], "grupos": [], "puentes": [],
        "plazos": [], "normas_nombradas": nombradas, "candidatas": candidatas,
        "notas": notas,
    }


def responder(cfg, pregunta, top_k=None):
    """Respuesta estructurada, auditable y con veredicto."""
    nombradas = recuperar.detectar_normas(cfg, pregunta)
    base = top_k or cfg["recuperacion"].get("top_k", 5)
    pedir = max(base, 3 * len(nombradas)) if len(nombradas) > 1 else base

    # Guarda 1: sin terminos con contenido no hay busqueda posible. Evita que una
    # sola palabra ("el", "coche") devuelva un precepto con insignia verde.
    ts = recuperar.terminos(pregunta)
    if len(ts) < 2:
        return _no_consta(cfg, pregunta, nombradas,
                          ["La pregunta no tiene terminos suficientes para buscar en el "
                           "articulado: se necesitan al menos dos palabras con contenido."])

    cands = recuperar.buscar_auto(cfg, pregunta, pedir)

    # Guarda 2: el precepto citado debe contener el TIPO de dato que se pregunta.
    # Preguntar un importe y citar un articulo sin euros es un falso positivo con
    # cita literal: se abstiene y se dice por que.
    tipos = tipo_dato(pregunta)
    if tipos and cands:
        cands = [c for c in cands if contiene_dato(tipos, c["texto"])]
        if not cands:
            return _no_consta(cfg, pregunta, nombradas,
                              [f"Los preceptos recuperados no contienen el dato pedido "
                               f"({' / '.join(sorted(tipos))}). No se responde para no "
                               f"dar una cifra sin respaldo literal."])

    if not cands:
        return _no_consta(cfg, pregunta, nombradas)

    max_citas = cfg["respuesta"].get("max_citas", 3)
    max_chars = cfg["respuesta"].get("max_caracteres_cita", 600)
    elegidos = seleccionar(cands, nombradas, max_citas)
    gate = Gate(cfg)
    try:
        afirmaciones = []
        for c in elegidos:
            cita = extraer_cita(c["texto"], max_chars)
            afirmaciones.append({
                "texto": (c["titulo_bloque"] or f'bloque {c["bloque"]}'),
                "norma": c["norma"], "bloque": c["bloque"], "cita": cita,
            })
        valida, res = gate.verificar_todo(afirmaciones)
    finally:
        gate.cerrar()

    plazos, notas = [], []
    for af in res:
        for p in detectar_plazos(af["cita"]):
            if p not in plazos:
                plazos.append(p)
    if plazos:
        notas.append(NOTA_PLAZO)
    modificados = [f for f in cands[:max_citas] if (f["n_versiones"] or 0) > 1]
    if modificados:
        notas.append("Artículos con redacción modificada: "
                     + ", ".join(f"{f['titulo_bloque'] or f['bloque']} "
                                 f"({f['n_versiones']} versiones)" for f in modificados)
                     + ". Se muestra la última versión consolidada del BOE.")

    # Sin afirmaciones verificadas NO hay veredicto verde: una insignia "VERIFICADO"
    # con cero citas es la peor salida posible (afirma sin respaldo).
    veredicto = "VERIFICADO" if (res and valida) else ("NO CONSTA" if not res else "REVISAR")
    res = _con_url(res)
    fuentes = [_fuente(c) for c in cands]
    return {
        "pregunta": pregunta, "modo": "extractivo", "veredicto": veredicto,
        "afirmaciones": res, "fuentes": fuentes,
        "grupos": grupos_por_norma(fuentes),
        "puentes": puentes(cfg, [c for c in cands
                                 if (c["norma"], c["bloque"]) in
                                 {(a["norma"], a["bloque"]) for a in res}]),
        "plazos": plazos, "notas": notas, "normas_nombradas": nombradas,
    }


# --------------------------------------------------------------------------
# Modo LLM (opcional). El modelo SOLO propone; el gate decide.
# --------------------------------------------------------------------------

PROMPT = """Eres un asistente jurídico que trabaja SOLO con el CONTEXTO aportado.

Puedes combinar preceptos de VARIAS normas si el contexto las contiene: si la
pregunta pide cómo se aplica una figura de una ley en otro cuerpo legal, enlaza
los preceptos y di expresamente qué artículo de qué norma sostiene cada parte.

Devuelve JSON puro, sin explicaciones, con esta forma:
{"respuesta": [{"texto": "<afirmación breve>", "norma": "<BOE-A-...>",
                "bloque": "<id de bloque>", "cita": "<fragmento LITERAL del contexto>"}]}

Reglas estrictas:
- La cita debe copiarse carácter a carácter del contexto. No reformules ni resumas.
- Una afirmación = un precepto. Para enlazar dos normas, dos afirmaciones.
- Si un dato no consta en el contexto, NO lo escribas: devuelve solo lo que consta.
- Nunca añadas cifras, plazos ni artículos que no estén en el contexto.

CONTEXTO:
{contexto}

PREGUNTA: {pregunta}"""


def responder_llm(cfg, pregunta, top_k=None):
    """Modo asistido: borrador del modelo + gate obligatorio. GASTA TOKENS."""
    if not cfg.get("llm", {}).get("habilitado"):
        raise RuntimeError("Modo LLM deshabilitado en config.json (llm.habilitado=false).")
    cands = recuperar.buscar_auto(cfg, pregunta, top_k)
    if not cands:
        return responder(cfg, pregunta, top_k)

    contexto = "\n\n".join(
        f'[{c["norma"]} | bloque {c["bloque"]}]\n{c["texto"]}'
        for c in cands[: cfg["respuesta"].get("max_citas", 3)])
    cuerpo = {
        "model": cfg["llm"].get("modelo", "local"),
        "temperature": cfg["llm"].get("temperatura", 0),
        "max_tokens": cfg["llm"].get("max_tokens", 700),
        "messages": [{"role": "user",
                      "content": PROMPT.replace("{contexto}", contexto)
                                        .replace("{pregunta}", pregunta)}],
    }
    import os as _os
    clave = _os.environ.get(cfg["llm"].get("api_key_env", ""), "") or \
        cfg["llm"].get("api_key", "local")
    req = urllib.request.Request(
        cfg["llm"]["endpoint"], data=json.dumps(cuerpo).encode(),
        headers={"Content-Type": "application/json",
                 "Authorization": f"Bearer {clave}"})
    with urllib.request.urlopen(req, timeout=180) as r:
        salida = json.loads(r.read())["choices"][0]["message"]["content"]

    # El modelo puede envolver el JSON en ```json ... ``` o añadir prosa alrededor.
    # Se extrae el primer objeto {...} equilibrado en vez de fiarse del strip().
    bloque = re.search(r"\{.*\}", salida, re.S)
    try:
        propuestas = json.loads(bloque.group(0))["respuesta"] if bloque else []
    except Exception:  # noqa: BLE001
        propuestas = []
    if not propuestas and os.environ.get("LEYCLARA_DEBUG"):
        print("--- salida cruda del modelo ---\n" + salida[:800], file=sys.stderr)

    gate = Gate(cfg)
    try:
        valida, res = gate.verificar_todo(propuestas)
    finally:
        gate.cerrar()
    fuentes = [_fuente(c) for c in cands]
    res = _con_url(res)
    return {
        "pregunta": pregunta, "modo": "llm",
        "veredicto": "VERIFICADO" if (res and valida) else
                     ("NO CONSTA" if not propuestas else "REVISAR"),
        "afirmaciones": res, "fuentes": fuentes,
        "grupos": grupos_por_norma(fuentes),
        "puentes": puentes(cfg, [c for c in cands
                                 if (c["norma"], c["bloque"]) in
                                 {(a["norma"], a["bloque"]) for a in res}]),
        "plazos": [p for af in res for p in detectar_plazos(af.get("cita", ""))],
        "normas_nombradas": recuperar.detectar_normas(cfg, pregunta),
        "notas": ([f"Borrador generado por {cfg['llm'].get('modelo')} y filtrado por el gate."]
                  if res else ["El modelo no propuso nada verificable."]),
    }
