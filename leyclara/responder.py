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
import re
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
    }


def responder(cfg, pregunta, top_k=None):
    """Respuesta estructurada, auditable y con veredicto."""
    cands = recuperar.buscar(cfg, pregunta, top_k)

    if not cands:
        return {
            "pregunta": pregunta, "modo": "extractivo", "veredicto": "NO CONSTA",
            "afirmaciones": [], "fuentes": [], "plazos": [],
            "notas": ["No se ha localizado precepto aplicable en el corpus indexado. "
                      "Esto NO significa que no exista la norma: significa que no está "
                      "en las normas cargadas. Ver config.json → normas."],
        }

    max_citas = cfg["respuesta"].get("max_citas", 3)
    max_chars = cfg["respuesta"].get("max_caracteres_cita", 600)
    gate = Gate(cfg)
    try:
        afirmaciones = []
        for c in cands[:max_citas]:
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

    veredicto = "VERIFICADO" if valida else "REVISAR"
    return {
        "pregunta": pregunta, "modo": "extractivo", "veredicto": veredicto,
        "afirmaciones": res, "fuentes": [_fuente(c) for c in cands],
        "plazos": plazos, "notas": notas,
    }


# --------------------------------------------------------------------------
# Modo LLM (opcional). El modelo SOLO propone; el gate decide.
# --------------------------------------------------------------------------

PROMPT = """Eres un asistente jurídico. Responde ÚNICAMENTE con el CONTEXTO.
Devuelve JSON puro, sin explicaciones, con esta forma:
{"respuesta": [{"texto": "<afirmación breve>", "norma": "<BOE-A-...>",
                "bloque": "<id de bloque>", "cita": "<fragmento LITERAL del contexto>"}]}
Reglas: la cita debe copiarse carácter a carácter del contexto; si el dato no
consta, devuelve {"respuesta": []}. No reformules las citas.

CONTEXTO:
{contexto}

PREGUNTA: {pregunta}"""


def responder_llm(cfg, pregunta, top_k=None):
    """Modo asistido: borrador del modelo + gate obligatorio. GASTA TOKENS."""
    if not cfg.get("llm", {}).get("habilitado"):
        raise RuntimeError("Modo LLM deshabilitado en config.json (llm.habilitado=false).")
    cands = recuperar.buscar(cfg, pregunta, top_k)
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
                      "content": PROMPT.format(contexto=contexto, pregunta=pregunta)}],
    }
    req = urllib.request.Request(
        cfg["llm"]["endpoint"], data=json.dumps(cuerpo).encode(),
        headers={"Content-Type": "application/json",
                 "Authorization": f'Bearer {cfg["llm"].get("api_key", "local")}'})
    with urllib.request.urlopen(req, timeout=180) as r:
        salida = json.loads(r.read())["choices"][0]["message"]["content"]

    try:
        propuestas = json.loads(salida.strip().strip("`").removeprefix("json"))["respuesta"]
    except Exception:  # noqa: BLE001
        propuestas = []

    gate = Gate(cfg)
    try:
        valida, res = gate.verificar_todo(propuestas)
    finally:
        gate.cerrar()
    return {
        "pregunta": pregunta, "modo": "llm",
        "veredicto": "VERIFICADO" if (res and valida) else
                     ("NO CONSTA" if not propuestas else "REVISAR"),
        "afirmaciones": res, "fuentes": [_fuente(c) for c in cands],
        "plazos": [p for af in res for p in detectar_plazos(af.get("cita", ""))],
        "notas": ["Borrador generado por modelo local y filtrado por el gate."]
                 if res else ["El modelo no propuso nada verificable."],
    }
