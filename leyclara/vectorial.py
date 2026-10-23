"""Capa vectorial: embeddings para la busqueda semantica.

Resuelve el fallo que la busqueda lexica no puede: la pregunta que no usa las
palabras del precepto. "pena por homicidio" no aparece literalmente en el art. 138
del Codigo Penal, que dice "castigado con la pena de prision de diez a quince anos";
BM25 no lo ve, un embedding si.

Almacenamiento: vector como BLOB float32 en SQLite (sin FAISS, sin cromadb).
8651 articulos x 4096 dims = ~140 MB, que entran en RAM sin drama.

El indice es OPCIONAL: si no existe, `recuperar.buscar_hibrido` sigue funcionando
en modo lexico. Nunca se rompe por no haber construido el indice.
"""

import json
import os
import sqlite3
import struct
import time
import urllib.request

from . import config as cfg_mod


def _api_key(cfg):
    env = cfg.get("vectorial", {}).get("api_key_env", "")
    clave = os.environ.get(env, "") if env else ""
    if not clave:
        raise RuntimeError(
            f"Falta la clave de embeddings: define la variable de entorno {env}.")
    return clave


def _embed(cfg, textos):
    v = cfg["vectorial"]
    cuerpo = json.dumps({"model": v["modelo"], "input": textos}).encode()
    req = urllib.request.Request(
        v["endpoint"], data=cuerpo,
        headers={"Content-Type": "application/json",
                 "Authorization": f"Bearer {_api_key(cfg)}"})
    with urllib.request.urlopen(req, timeout=180) as r:
        d = json.loads(r.read())
    return [x["embedding"] for x in d["data"]], d.get("usage", {})


def _blob(vec):
    return struct.pack(f"<{len(vec)}f", *vec)


def _unblob(b, dim):
    return struct.unpack(f"<{dim}f", b)


def crear_tabla(con):
    con.executescript("""
    CREATE TABLE IF NOT EXISTS vectores(
        norma_id TEXT, bloque_id TEXT, dim INTEGER, modelo TEXT, vec BLOB,
        PRIMARY KEY (norma_id, bloque_id));
    """)


def construir(cfg, verbose=True, limite=None):
    """Embebe todos los articulos del corpus. Idempotente: re-embebe si cambio el modelo."""
    ruta = cfg_mod.db(cfg)
    con = sqlite3.connect(ruta)
    crear_tabla(con)
    v = cfg["vectorial"]
    max_chars = v.get("max_caracteres", 1200)
    modelo = v["modelo"]

    filas = con.execute(
        "SELECT norma_id, bloque_id, titulo_bloque, texto FROM articulos").fetchall()
    if limite:
        filas = filas[:limite]
    ya = {(r[0], r[1]) for r in con.execute(
        "SELECT norma_id, bloque_id FROM vectores WHERE modelo=?", (modelo,))}
    pendientes = [f for f in filas if (f[0], f[1]) not in ya]

    if verbose:
        print(f"Vectorial: {len(filas)} articulos, {len(pendientes)} por embeber "
              f"(modelo {modelo}, max {max_chars} chars)")
    if not pendientes:
        print("Nada que hacer: el indice ya esta completo.")
        con.close()
        return {"embebidos": 0, "tokens": 0}

    lote = v.get("lote", 32)
    embebidos, tokens = 0, 0
    t0 = time.time()
    for i in range(0, len(pendientes), lote):
        trozo = pendientes[i:i + lote]
        textos = [f"{f[2] or ''}. {f[3][:max_chars]}".strip() for f in trozo]
        try:
            vecs, usage = _embed(cfg, textos)
        except Exception as e:  # noqa: BLE001
            print(f"  !! lote {i//lote}: {e}")
            time.sleep(2)
            continue
        tokens += usage.get("total_tokens", 0) or 0
        for (nid, bid, _, _), vec in zip(trozo, vecs):
            con.execute("INSERT OR REPLACE INTO vectores VALUES(?,?,?,?,?)",
                        (nid, bid, len(vec), modelo, _blob(vec)))
        con.commit()
        embebidos += len(trozo)
        if verbose and (i // lote) % 10 == 0:
            vel = embebidos / max(time.time() - t0, 0.1)
            print(f"  {embebidos}/{len(pendientes)}  ({vel:.0f} arts/s)  "
                  f"tokens {tokens:,}")
    con.close()
    print(f"Vectorial listo: {embebidos} articulos, {tokens:,} tokens, "
          f"{time.time()-t0:.0f}s")
    return {"embebidos": embebidos, "tokens": tokens}


class IndiceVectorial:
    """Indice en memoria (numpy). Se carga una vez por proceso."""

    def __init__(self, cfg):
        import numpy as np
        self.np = np
        self.ruta = cfg_mod.db(cfg)
        self.modelo = cfg["vectorial"]["modelo"]
        self.claves, trozos, dim = [], [], None
        con = sqlite3.connect(self.ruta)
        try:
            filas = con.execute(
                "SELECT norma_id, bloque_id, dim, vec FROM vectores WHERE modelo=?",
                (self.modelo,)).fetchall()
        except sqlite3.OperationalError:
            filas = []
        con.close()
        if not filas:
            raise FileNotFoundError(
                "Sin indice vectorial. Ejecuta: python -m leyclara vectorial")
        dim = filas[0][2]
        self.claves = [(f[0], f[1]) for f in filas]
        self.matriz = np.array([_unblob(f[3], f[2]) for f in filas], dtype="float32")
        # normalizar: producto escalar == coseno
        normas = np.linalg.norm(self.matriz, axis=1, keepdims=True)
        normas[normas == 0] = 1.0
        self.matriz /= normas
        self.dim = dim

    def sims(self, cfg, pregunta, claves):
        """Similitud coseno de la consulta contra un conjunto concreto de articulos.

        Sirve para RERANKEAR: recuperar 50 por BM25/RRF y reordenar con el vectorial,
        que es lo que evita perder el precepto bueno cuando queda en la cola (medido:
        a k=50 estaba, a k=5 no).
        """
        if not claves:
            return {}
        vecs, _ = _embed(cfg, [pregunta])
        q = self.np.array(vecs[0], dtype="float32")
        q /= (self.np.linalg.norm(q) or 1.0)
        indice = {c: i for i, c in enumerate(self.claves)}
        out = {}
        for clave in claves:
            i = indice.get(tuple(clave))
            if i is not None:
                out[tuple(clave)] = float(self.matriz[i] @ q)
        return out

    def buscar(self, cfg, pregunta, top_k=20, norma=None, min_sim=None):
        vecs, _ = _embed(cfg, [pregunta])
        q = self.np.array(vecs[0], dtype="float32")
        q /= (self.np.linalg.norm(q) or 1.0)
        sims = self.matriz @ q
        orden = self.np.argsort(-sims)
        out = []
        for idx in orden:
            nid, bid = self.claves[int(idx)]
            if norma and nid != norma:
                continue
            s = float(sims[int(idx)])
            if min_sim is not None and s < min_sim:
                break            # ordenado: a partir de aqui todo es peor
            out.append((nid, bid, s))
            if len(out) >= top_k:
                break
        return out
