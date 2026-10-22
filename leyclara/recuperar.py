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
