"""Ingesta: de la API del BOE a SQLite, troceado por ARTICULO.

Un articulo = una fila = una unidad citables. Nunca se trocea por caracteres
porque la cita juridica util es el precepto, no un fragmento de 500 tokens.
"""

import html as _html
import json
import os
import re
import sqlite3

from . import boe as boe_mod
from . import config as cfg_mod

RE_BLOQUE = re.compile(r"<bloque\b([^>]*)>(.*?)</bloque>", re.S)
RE_VERSION = re.compile(r"<version\b([^>]*)>(.*?)</version>", re.S)
RE_ATTR = re.compile(r'(\w+)="([^"]*)"')

# Remisiones: primera referencia de cada mencion. Precision > exhaustividad.
# (Una primera version capturaba "Articulo 2. 1 El que..." como dos remisiones.)
RE_REMISION = re.compile(
    r"\b(?:art[íi]culos?|arts?\.)\s+(\d+(?:\s*(?:bis|ter|quáter|quinquies))?)", re.I)
RE_ENCABEZADO = re.compile(r"^\s*art[íi]culo\s+[\w\s\.\)]{0,40}?\.\s*", re.I)


def _base(num):
    m = re.match(r"\d+", num or "")
    return int(m.group(0)) if m else None


def crear(con):
    con.executescript("""
    PRAGMA journal_mode=WAL;
    CREATE TABLE IF NOT EXISTS normas(
        identificador TEXT PRIMARY KEY, titulo TEXT, rango TEXT, departamento TEXT,
        fecha_publicacion TEXT, fecha_actualizacion TEXT, vigencia TEXT, url_html TEXT);
    CREATE TABLE IF NOT EXISTS articulos(
        norma_id TEXT, bloque_id TEXT, tipo TEXT, titulo_bloque TEXT, texto TEXT,
        n_versiones INTEGER, fecha_vigencia TEXT,
        PRIMARY KEY (norma_id, bloque_id));
    CREATE TABLE IF NOT EXISTS cambios(
        norma TEXT, sentido TEXT, relacion TEXT, detalle TEXT,
        norma_relacionada TEXT, articulos TEXT);
    CREATE TABLE IF NOT EXISTS remisiones(
        norma TEXT, origen TEXT, destino TEXT, evidencia TEXT);
    CREATE VIRTUAL TABLE IF NOT EXISTS articulos_fts USING fts5(
        norma_id UNINDEXED, bloque_id UNINDEXED, titulo_bloque, texto,
        tokenize='unicode61 remove_diacritics 2');
    """)


def _texto_version(cuerpo, min_chars=15):
    cuerpo = re.sub(r"<table\b.*?</table>", " [TABLA] ", cuerpo, flags=re.S)
    cuerpo = re.sub(r"<t[dh]\b[^>]*>", " | ", cuerpo)
    cuerpo = re.sub(r"</(p|tr|td|th)>", "\n", cuerpo)
    cuerpo = re.sub(r"<[^>]+>", " ", cuerpo)
    txt = _html.unescape(cuerpo)
    txt = re.sub(r"[ \t\u00a0]+", " ", txt)
    txt = re.sub(r"\n\s*\n+", "\n", txt).strip()
    return txt if len(txt) >= min_chars else ""


def bloques(xml, min_chars=15):
    """Devuelve los preceptos de una norma, con la ULTIMA version (vigente)."""
    out = []
    for attrs, cuerpo in RE_BLOQUE.findall(xml):
        a = dict(RE_ATTR.findall(attrs))
        versiones = RE_VERSION.findall(cuerpo)
        if versiones:
            va = dict(RE_ATTR.findall(versiones[-1][0]))
            cuerpo_v = versiones[-1][1]
        else:
            va, cuerpo_v = {}, cuerpo
        texto = _texto_version(cuerpo_v, min_chars)
        if not texto:
            continue
        out.append({
            "bloque_id": a.get("id", ""),
            "tipo": a.get("tipo", ""),
            "titulo_bloque": _html.unescape(a.get("titulo", "")),
            "texto": texto,
            "n_versiones": len(versiones),
            "fecha_vigencia": va.get("fecha_vigencia", ""),
        })
    return out


def cambios(xml):
    """Relaciones de vigencia oficiales: quien modifica/deroga esta norma."""
    out = []
    for sentido, bloque in (("posterior", "posteriores"), ("anterior", "anteriores")):
        for ent in re.findall(rf"<{sentido}>(.*?)</{sentido}>", xml, re.S):
            idn = re.search(r"<id_norma>(.*?)</id_norma>", ent, re.S)
            rel = re.search(r"<relacion[^>]*>(.*?)</relacion>", ent, re.S)
            txt = re.search(r"<texto>(.*?)</texto>", ent, re.S)
            txt_t = _html.unescape(txt.group(1).strip()) if txt else ""
            afectados = []
            for a in re.findall(r"arts?\.\s*([\d.,\sy bis ter]+)", txt_t):
                afectados += re.findall(r"\d+\s*(?:bis|ter)?", a)
            out.append({
                "sentido": sentido,
                "relacion": _html.unescape(rel.group(1).strip()) if rel else "",
                "detalle": txt_t[:300],
                "norma_relacionada": idn.group(1).strip() if idn else "",
                "articulos": ",".join(x.strip() for x in afectados),
            })
    return out


def remisiones(con):
    """Grafo articulo -> articulo dentro del corpus (regex sobre texto oficial)."""
    con.execute("DELETE FROM remisiones")
    filas = con.execute(
        "SELECT norma_id, bloque_id, texto FROM articulos").fetchall()
    aristas = []
    for norma_id, bloque_id, texto in filas:
        origen = re.sub(r"[^\d]", "", bloque_id) or bloque_id
        base_origen = _base(origen)
        cuerpo = RE_ENCABEZADO.sub("", texto, count=1)
        for m in RE_REMISION.finditer(cuerpo):
            destino = re.sub(r"\s+", "", m.group(1)).lower()
            if _base(destino) is not None and _base(destino) == base_origen:
                continue
            ini = max(0, cuerpo.rfind(".", 0, m.start()) + 1)
            fin = cuerpo.find(".", m.end())
            ev = cuerpo[ini: fin if fin > 0 else m.end() + 60].strip()[:240]
            aristas.append((norma_id, origen, destino, ev))
    con.executemany("INSERT INTO remisiones VALUES(?,?,?,?)", aristas)
    con.commit()
    return len(aristas)


def ingestar(cfg, ids=None, verbose=True):
    """Ingesta (o re-ingesta) las normas indicadas. Resumible: por norma."""
    ruta_db = cfg_mod.db(cfg)
    os.makedirs(os.path.dirname(ruta_db), exist_ok=True)
    con = sqlite3.connect(ruta_db)
    crear(con)

    cliente = boe_mod.BOE(cfg)
    objetivo = ids or [n["id"] for n in cfg_mod.normas(cfg)]
    min_chars = cfg["recuperacion"].get("min_caracteres_articulo", 15)
    stats = {"normas": 0, "articulos": 0, "cambios": 0, "errores": []}

    for nid in objetivo:
        try:
            meta = cliente.metadatos(nid)
            xml = cliente.texto(nid)
            arts = bloques(xml, min_chars)
            if not arts:
                stats["errores"].append(f"{nid}: 0 articulos")
                continue

            con.execute("DELETE FROM articulos WHERE norma_id=?", (nid,))
            con.execute("DELETE FROM articulos_fts WHERE norma_id=?", (nid,))
            con.execute("DELETE FROM cambios WHERE norma=?", (nid,))
            con.execute(
                "INSERT OR REPLACE INTO normas VALUES(?,?,?,?,?,?,?,?)",
                (nid, meta["titulo"], meta["rango"], meta["departamento"],
                 meta["fecha_publicacion"], meta["fecha_actualizacion"],
                 meta["vigencia_agotada"], meta["url_html"]))
            for a in arts:
                con.execute(
                    "INSERT OR REPLACE INTO articulos VALUES(?,?,?,?,?,?,?)",
                    (nid, a["bloque_id"], a["tipo"], a["titulo_bloque"], a["texto"],
                     a["n_versiones"], a["fecha_vigencia"]))
                con.execute(
                    "INSERT INTO articulos_fts(norma_id, bloque_id, titulo_bloque, texto)"
                    " VALUES(?,?,?,?)",
                    (nid, a["bloque_id"], a["titulo_bloque"], a["texto"]))

            try:
                cs = cambios(cliente.analisis(nid))
            except Exception:  # noqa: BLE001
                cs = []
                stats["errores"].append(f"{nid}: sin /analisis")
            for c in cs:
                con.execute("INSERT INTO cambios VALUES(?,?,?,?,?,?)",
                            (nid, c["sentido"], c["relacion"], c["detalle"],
                             c["norma_relacionada"], c["articulos"]))
            con.commit()

            stats["normas"] += 1
            stats["articulos"] += len(arts)
            stats["cambios"] += len(cs)
            if verbose:
                print(f"  [{stats['normas']:>2}] {nid} {len(arts):>5} arts · {len(cs):>4} cambios · {meta['titulo'][:48]}")
        except Exception as e:  # noqa: BLE001
            stats["errores"].append(f"{nid}: {e}")
            if verbose:
                print(f"  !!  {nid}: {e}")

    stats["remisiones"] = remisiones(con)
    con.close()
    return stats


def estado(cfg):
    ruta_db = cfg_mod.db(cfg)
    if not os.path.exists(ruta_db):
        return {"existe": False}
    con = sqlite3.connect(ruta_db)
    d = {
        "existe": True,
        "normas": con.execute("SELECT COUNT(*) FROM normas").fetchone()[0],
        "articulos": con.execute("SELECT COUNT(*) FROM articulos").fetchone()[0],
        "cambios": con.execute("SELECT COUNT(*) FROM cambios").fetchone()[0],
        "remisiones": con.execute("SELECT COUNT(*) FROM remisiones").fetchone()[0],
        "modificados": con.execute(
            "SELECT COUNT(*) FROM articulos WHERE n_versiones>1").fetchone()[0],
        "mb": round(os.path.getsize(ruta_db) / 1e6, 1),
        "detalle": con.execute(
            "SELECT n.identificador, n.titulo, COUNT(a.bloque_id) FROM normas n "
            "LEFT JOIN articulos a ON a.norma_id=n.identificador "
            "GROUP BY n.identificador ORDER BY n.fecha_publicacion").fetchall(),
    }
    con.close()
    return d


def exportar_jsonl(cfg):
    """Volcado linea a linea de los articulos (para embeddings o auditoria)."""
    ruta = cfg_mod.corpus_jsonl = cfg.get("corpus", {}).get("jsonl", "corpus/articulos.jsonl")
    ruta = os.path.join(cfg["_raiz"], ruta) if not os.path.isabs(ruta) else ruta
    con = sqlite3.connect(cfg_mod.db(cfg))
    n = 0
    with open(ruta, "w", encoding="utf-8") as f:
        for r in con.execute(
                "SELECT n.identificador, n.titulo, n.rango, n.fecha_publicacion, "
                "a.bloque_id, a.titulo_bloque, a.texto, a.n_versiones, a.fecha_vigencia "
                "FROM articulos a JOIN normas n ON n.identificador=a.norma_id"):
            f.write(json.dumps({
                "norma": r[0], "titulo_norma": r[1], "rango": r[2],
                "fecha_publicacion": r[3], "bloque": r[4], "titulo_bloque": r[5],
                "texto": r[6], "n_versiones": r[7], "fecha_vigencia": r[8]},
                ensure_ascii=False) + "\n")
            n += 1
    con.close()
    return ruta, n
