"""Catalogo de EXISTENCIAS: las ~12.300 normas del BOE, sin descargar su texto.

Para que sirve, exactamente una cosa: cuando el buscador no encuentra nada, hoy
responde "no consta" y el usuario no sabe si es que no existe o es que no la
tenemos. Eso es un falso negativo ciego, el peor tipo de fallo.

Con este catalogo la respuesta pasa a ser: "no consta en lo indexado, pero existe
una norma que probablemente aplica: Ley X (BOE-A-...), no cargada".

Coste: cero tokens (solo metadatos) y una descarga de ~13 MB una vez.
"""

import json
import os
import re
import sqlite3
import unicodedata

from . import boe as boe_mod
from . import config as cfg_mod

STOP = {"de", "la", "el", "los", "las", "un", "una", "y", "o", "en", "que", "por",
        "para", "con", "del", "al", "se", "su", "es", "como", "si", "no", "mas",
        "los", "sus", "cual", "cuanto", "cuando", "donde", "quien", "hay"}


def _plano(s):
    s = unicodedata.normalize("NFKD", (s or "").lower())
    return "".join(c for c in s if not unicodedata.combining(c))


def _terminos(pregunta):
    return [w for w in re.findall(r"\w+", _plano(pregunta))
            if len(w) > 3 and w not in STOP]


def crear(con):
    con.executescript("""
    CREATE TABLE IF NOT EXISTS existencias(
        identificador TEXT PRIMARY KEY, titulo TEXT, rango TEXT,
        fecha_publicacion TEXT, indexada INTEGER DEFAULT 0);
    CREATE INDEX IF NOT EXISTS idx_ex_titulo ON existencias(titulo);
    """)


def construir(cfg, verbose=True):
    """Descarga el indice completo de legislacion consolidada (solo metadatos)."""
    ruta = cfg_mod.db(cfg)
    os.makedirs(os.path.dirname(ruta), exist_ok=True)
    con = sqlite3.connect(ruta)
    crear(con)
    cliente = boe_mod.BOE(cfg)

    offset, total = 0, 0
    while True:
        lote = cliente.indice(limit=500, offset=offset)
        if not lote:
            break
        filas = []
        for n in lote:
            filas.append((
                n["identificador"],
                n.get("titulo", ""),
                (n.get("rango") or {}).get("texto", ""),
                n.get("fecha_publicacion", ""),
            ))
        con.executemany(
            "INSERT OR IGNORE INTO existencias(identificador,titulo,rango,fecha_publicacion)"
            " VALUES(?,?,?,?)", filas)
        con.commit()
        total += len(filas)
        offset += len(lote)
        if verbose:
            print(f"  {total} normas catalogadas…")
        if len(lote) < 500:
            break

    # marcar cuales estan ya ingeridas (texto disponible)
    con.execute("""UPDATE existencias SET indexada = 1 WHERE identificador IN
                   (SELECT identificador FROM normas)""")
    con.commit()
    n_tot = con.execute("SELECT COUNT(*) FROM existencias").fetchone()[0]
    n_idx = con.execute("SELECT COUNT(*) FROM existencias WHERE indexada=1").fetchone()[0]
    con.close()
    if verbose:
        print(f"Existencias: {n_tot} normas en el BOE, {n_idx} con texto indexado "
              f"({n_idx/n_tot*100:.1f} %)")
    return {"total": n_tot, "indexadas": n_idx}


def _cargadas(cfg):
    ruta = cfg_mod.db(cfg)
    if not os.path.exists(ruta):
        return set()
    con = sqlite3.connect(ruta)
    try:
        return {r[0] for r in con.execute("SELECT identificador FROM normas")}
    except sqlite3.OperationalError:
        return set()
    finally:
        con.close()


def buscar_en_boe(cfg, pregunta, top=4):
    """Ultimo recurso: preguntar al buscador del BOE (todo el corpus es buscable
    aunque no lo tengamos descargado).

    Devuelve normas candidatas SIN texto: sirve para decir "esto existe, no lo
    tengo", nunca para responder. Cuesta una peticion HTTP y cero tokens.
    """
    ts = _terminos(pregunta)[:8]
    if not ts:
        return []
    # Solo TITULO, no fulltext: un OR de todos los terminos contra el texto completo
    # devuelve basura ordenada al azar (comprobado: la pregunta sobre la factura de la
    # luz devolvia Reales Decretos de titulos academicos). Si el titulo no comparte
    # vocabulario con la pregunta, es mejor no sugerir nada que sugerir mal.
    expr = f"titulo:({' OR '.join(ts)})"
    from . import boe as _boe
    import urllib.parse
    cliente = _boe.BOE(cfg)
    q = urllib.parse.quote(json.dumps(
        {"query": {"query_string": {"query": expr}}}, ensure_ascii=False))
    try:
        datos = json.loads(cliente._get(
            f"{cliente.base}?query={q}&limit=12",
            accept="application/json"))["data"]
    except Exception:  # noqa: BLE001
        return []
    if isinstance(datos, dict):
        datos = [datos]

    cargadas = _cargadas(cfg)
    out = []
    for n in datos or []:
        nid = n.get("identificador")
        if not nid or nid in cargadas:
            continue
        out.append({
            "identificador": nid,
            "titulo": n.get("titulo", ""),
            "rango": (n.get("rango") or {}).get("texto", ""),
            "fecha_publicacion": n.get("fecha_publicacion", ""),
            "url": f"https://www.boe.es/buscar/act.php?id={nid}",
            "origen": "buscador BOE",
        })
        if len(out) >= top:
            break
    return out


def sugerir_amplio(cfg, pregunta, top=4):
    """Combina catalogo local por titulo + buscador del BOE. Deduplica por id."""
    vistos, out = set(), []
    for c in sugerir(cfg, pregunta, top=top):
        c["origen"] = "catalogo local"
        vistos.add(c["identificador"])
        out.append(c)
    for c in buscar_en_boe(cfg, pregunta, top=top):
        if c["identificador"] not in vistos:
            vistos.add(c["identificador"])
            out.append(c)
    return out[:top]


def sugerir(cfg, pregunta, top=4, min_coincidencias=2):
    """Normas del BOE que probablemente aplican y NO estan cargadas.

    Es un aviso de cobertura, no una respuesta: dice que existe, no lo que dice.
    """
    ruta = cfg_mod.db(cfg)
    if not os.path.exists(ruta):
        return []
    con = sqlite3.connect(ruta)
    try:
        filas = con.execute(
            "SELECT identificador, titulo, rango, fecha_publicacion, indexada"
            " FROM existencias").fetchall()
    except sqlite3.OperationalError:
        con.close()
        return []
    con.close()

    cargadas = _cargadas(cfg)
    ts = _terminos(pregunta)
    if not ts or not filas:
        return []

    puntuados = []
    for nid, titulo, rango, fecha, indexada in filas:
        if nid in cargadas:
            continue
        t = _plano(titulo)
        coincide = sum(1 for w in ts if w[:6] in t)
        if coincide < min(min_coincidencias, len(ts)):
            continue
        puntuados.append({
            "identificador": nid, "titulo": titulo, "rango": rango,
            "fecha_publicacion": fecha, "coincide": coincide,
            "cobertura": round(coincide / len(ts), 2),
            "url": f"https://www.boe.es/buscar/act.php?id={nid}",
        })
    puntuados.sort(key=lambda x: (-x["coincide"], len(x["titulo"])))
    return puntuados[:top]
