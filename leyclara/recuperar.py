"""Recuperacion: BM25 sobre SQLite FTS5 (sin dependencias, sin API, sin tokens).

Estrategia: primero se intenta AND de los terminos (precision) y si no hay
resultados se relaja a OR (recall). Devuelve siempre la lista completa de
candidatos para que el harness pueda medir recall@k por separado del acierto.
"""

import os
import re
import sqlite3
import unicodedata

from . import config as cfg_mod

STOP = {"de", "la", "el", "los", "las", "un", "una", "unos", "unas", "y", "o", "u",
        "en", "que", "por", "para", "con", "del", "al", "se", "su", "sus", "es",
        "como", "si", "no", "mas", "más", "muy", "me", "mi", "lo", "le", "les",
        "cual", "cuales", "cuando", "cuanto", "cuanta", "cuantos", "cuantas",
        "donde", "quien", "quienes", "hay", "ser", "son", "esta", "este", "esto",
        "tiene", "tengo", "hace", "hacer", "puedo", "puede", "debe", "debo", "es"}

_SQL = """
SELECT n.identificador, n.titulo, n.rango, n.fecha_publicacion, n.url_html,
       a.bloque_id, a.titulo_bloque, a.texto, a.n_versiones, a.fecha_vigencia,
       bm25(articulos_fts, 0.0, 0.0, 2.0, 1.0) AS score
FROM articulos_fts
JOIN articulos a ON a.norma_id = articulos_fts.norma_id
                AND a.bloque_id = articulos_fts.bloque_id
JOIN normas   n ON n.identificador = a.norma_id
WHERE articulos_fts MATCH ? {filtro}
ORDER BY score
LIMIT ?
"""


def terminos(pregunta):
    t = unicodedata.normalize("NFKD", pregunta.lower())
    t = "".join(c for c in t if not unicodedata.combining(c))
    palabras = re.findall(r"\w+", t)
    return [w for w in palabras if len(w) > 2 and w not in STOP]


def raiz(t):
    """Raiz aproximada por prefijo: 'prescribir' y 'prescripcion' -> 'prescr'.

    No es un stemmer: es el minimo comun que hace que FTS5 encuentre variantes
    morfologicas en castellano sin meter dependencias. Se usa igual para el
    filtro de cobertura, para que consulta e indice midan lo mismo.
    """
    return t[: max(4, min(6, len(t)))]


def cobertura(ts, texto):
    """Fraccion de terminos de la consulta presentes en el articulo."""
    if not ts:
        return 0.0
    doc = unicodedata.normalize("NFKD", (texto or "").lower())
    doc = "".join(c for c in doc if not unicodedata.combining(c))
    return sum(1 for t in ts if raiz(t) in doc) / len(ts)


def buscar(cfg, pregunta, top_k=None):
    """Devuelve candidatos ordenados. Lista vacia = no hay nada que responder.

    Dos filtros independientes, y el segundo es el que evita el falso positivo:
      1. relevancia BM25 (ranking)
      2. COBERTURA lexica minima: si el articulo no comparte suficiente
         vocabulario con la pregunta, no se muestra. Sin esto, la relajacion a OR
         devuelve cualquier cosa y el sistema "responde" a lo que no sabe.
    """
    ruta = cfg_mod.db(cfg)
    if not os.path.exists(ruta):
        raise FileNotFoundError(f"Falta el corpus ({ruta}). Ejecuta: python -m leyclara ingesta")
    rec = cfg["recuperacion"]
    top_k = top_k or rec.get("top_k", 5)
    min_cob = rec.get("min_cobertura", 0.6)
    min_terms = rec.get("min_terminos", 2)
    ts = terminos(pregunta)
    if not ts:
        return []

    filtro = " AND n.vigencia = 'N'" if rec.get("solo_vigentes") else ""
    con = sqlite3.connect(ruta)
    try:
        # Una sola pasada OR (recall) + filtro de cobertura (precision).
        # Un "AND primero" parece mas limpio pero es peor: si un articulo casa con
        # TODOS los terminos y el correcto solo con casi todos, el AND devuelve solo
        # aquel y el precepto esperado nunca se llega a ver (fallo real detectado
        # con el banco: art. 246 tapaba al 245).
        expr = " OR ".join(f'"{raiz(t)}"*' for t in ts)
        filas = con.execute(_SQL.format(filtro=filtro),
                            (expr, max(top_k * 10, 80))).fetchall()
        out = []
        for f in filas:
            c = _fila(f)
            cob = cobertura(ts, f[7])
            docn = unicodedata.normalize(
                "NFKD", f"{c['texto']} {c['titulo_bloque'] or ''}".lower())
            docn = "".join(ch for ch in docn if not unicodedata.combining(ch))
            coincide = sum(1 for t in ts if raiz(t) in docn)
            if cob >= min_cob and coincide >= min(min_terms, len(ts)):
                c["cobertura"] = round(cob, 2)
                out.append(c)
        # Orden: BM25 puro. Se probó a ordenar por cobertura y empeora (5/12 frente
        # a 6/12): la cobertura sirve para FILTRAR, no para ordenar.
        out.sort(key=lambda x: x["score"])
        return out[:top_k]
    finally:
        con.close()


def _fila(f):
    return {
        "norma": f[0], "titulo_norma": f[1], "rango": f[2], "fecha_publicacion": f[3],
        "url": f[4], "bloque": f[5], "titulo_bloque": f[6], "texto": f[7],
        "n_versiones": f[8], "fecha_vigencia": f[9], "score": f[10],
    }


# ---------------------------------------------------------------------------
# Hibrido: lexico + vectorial, fusionado con RRF (Reciprocal Rank Fusion)
# ---------------------------------------------------------------------------

_CACHE_INDICE = {}


def _indice(cfg):
    """Carga perezosa del indice vectorial (una vez por proceso)."""
    from . import vectorial
    clave = cfg_mod.db(cfg)
    if clave not in _CACHE_INDICE:
        _CACHE_INDICE[clave] = vectorial.IndiceVectorial(cfg)
    return _CACHE_INDICE[clave]


def detectar_normas(cfg, pregunta):
    """Normas nombradas en la pregunta, por alias. Base del salto entre normas."""
    p = " " + unicodedata.normalize("NFKD", pregunta.lower())
    p = "".join(c for c in p if not unicodedata.combining(c)) + " "
    fuera = []
    for n in cfg["normas"]:
        for a in n.get("alias", []):
            al = unicodedata.normalize("NFKD", a.lower())
            al = "".join(c for c in al if not unicodedata.combining(c))
            if re.search(rf"(?<![a-z0-9]){re.escape(al)}(?![a-z0-9])", p):
                fuera.append(n["id"])
                break
    return fuera


def hidratar(cfg, claves):
    """(norma_id, bloque_id) -> fila completa, conservando el orden recibido."""
    if not claves:
        return []
    con = sqlite3.connect(cfg_mod.db(cfg))
    salida = {}
    try:
        for nid, bid in claves:
            f = con.execute(_SQL_SIMPLE, (nid, bid)).fetchone()
            if f:
                salida[(nid, bid)] = _fila(f)
    finally:
        con.close()
    return [salida[c] for c in claves if c in salida]


_SQL_SIMPLE = """
SELECT n.identificador, n.titulo, n.rango, n.fecha_publicacion, n.url_html,
       a.bloque_id, a.titulo_bloque, a.texto, a.n_versiones, a.fecha_vigencia, 0.0
FROM articulos a JOIN normas n ON n.identificador = a.norma_id
WHERE a.norma_id = ? AND a.bloque_id = ?
"""


def buscar_hibrido(cfg, pregunta, top_k=None):
    """Fusiona tres listas con RRF: lexica, vectorial y vectorial por norma nombrada.

    Por que RRF y no sumar puntuaciones: BM25 y coseno viven en escalas distintas
    y no son comparables. RRF solo mira POSICIONES, asi que no hay que calibrar nada.
    """
    rec = cfg["recuperacion"]
    top_k = top_k or rec.get("top_k", 5)
    k = rec.get("rrf_k", 60)
    nombradas = detectar_normas(cfg, pregunta)
    listas, origen = [], {}

    lex = buscar(cfg, pregunta, max(top_k * 4, 20))
    if lex:
        listas.append([(c["norma"], c["bloque"]) for c in lex])
        origen["lexico"] = len(lex)

    # El vectorial necesita UMBRAL: siempre devuelve "lo mas parecido", y sin corte
    # el sistema responde a preguntas cuya respuesta no esta en el corpus (falso
    # positivo). Con min_similitud=0 se recupera el comportamiento sin filtro.
    min_sim = rec.get("min_similitud", 0.5)
    try:
        idx = _indice(cfg)
        vec = [(n, b) for n, b, _ in idx.buscar(
            cfg, pregunta, max(top_k * 4, 20), min_sim=min_sim)]
        if vec:
            listas.append(vec)
            origen["vectorial"] = len(vec)
    except (FileNotFoundError, RuntimeError):
        pass

    for nid in nombradas:
        try:
            v = [(n, b) for n, b, _ in _indice(cfg).buscar(
                cfg, pregunta, 4, norma=nid, min_sim=min_sim)]
            if v:
                listas.append(v)
                origen[f"norma:{nid}"] = len(v)
        except (FileNotFoundError, RuntimeError):
            pass

    if not listas:
        return []

    puntos = {}
    for lista in listas:
        for r, clave in enumerate(lista):
            puntos[clave] = puntos.get(clave, 0.0) + 1.0 / (k + r + 1)
    orden = sorted(puntos, key=lambda c: -puntos[c])
    candidatos = orden[: max(top_k * 2, 10)]

    # Si la pregunta nombra varias normas, cada una debe tener representacion aunque
    # su RRF global sea bajo: si no, el "salto entre normas" nunca ocurre porque la
    # norma mas lexica ocupa todo el top. Verificado: costas tapaba al Codigo Civil.
    for nid in nombradas:
        extra = [c for c in orden if c[0] == nid][:2]
        for c in extra:
            if c not in candidatos:
                candidatos.append(c)

    filas = hidratar(cfg, candidatos)

    # Las normas nombradas en la pregunta suben: si preguntas por el Codigo Civil
    # es porque quieres el Codigo Civil, aunque otro lexico puntue mas.
    for f in filas:
        f["rrf"] = round(puntos[(f["norma"], f["bloque"])], 4)
        f["nombrada"] = f["norma"] in nombradas
    filas.sort(key=lambda f: (not f["nombrada"], -f["rrf"]))

    # --- RERANK denso -------------------------------------------------------
    # Se recupera ancho (top_k=50) y se reordena con la similitud vectorial. Es lo que
    # rescata el precepto que queda en la cola: medido en el banco, recall@50 = 12/12
    # frente a recall@5 = 11/12. Sin este paso, subir el top_k solo mete ruido.
    if rec.get("rerank", True) and top_k > 0 and filas:
        try:
            idx = _indice(cfg)
            sims = idx.sims(cfg, pregunta, [(f["norma"], f["bloque"]) for f in filas])
            for f in filas:
                f["sim"] = round(sims.get((f["norma"], f["bloque"]), 0.0), 4)
            filas.sort(key=lambda f: (not f["nombrada"], -f["sim"], -f["rrf"]))
        except (FileNotFoundError, RuntimeError):
            pass

    return filas[:top_k]


def buscar_auto(cfg, pregunta, top_k=None):
    """Punto de entrada unico: usa el modo configurado."""
    if cfg["recuperacion"].get("modo", "lexico") == "hibrido":
        return buscar_hibrido(cfg, pregunta, top_k)
    return buscar(cfg, pregunta, top_k)
