"""Grafo de relaciones entre normas.

Tres tipos de arista, todas leidas de datos oficiales (nada inferido):

  1. `modifica` / `deroga` / `dicta_conformidad` ...  -> del /analisis del BOE
     (tabla `cambios`): quien toca a quien, con el articulo afectado.
  2. `remite`  -> del texto del articulo ("conforme al articulo 23"), dentro de la
     misma norma (tabla `remisiones`). Sirve para ver que preceptos son nodos.
  3. `menciona` -> una norma nombra a otra del corpus en su texto (barrido de alias).

Salidas: JSON (para la web) y DOT (Graphviz / draw.io).
"""

import json
import os
import re
import sqlite3
import unicodedata

from . import config as cfg_mod

TIPOS = {
    "modifica": "#c2410c", "deroga": "#b91c1c", "se dicta de conformidad": "#0f766e",
    "remite": "#64748b", "menciona": "#1d4ed8",
}


def _plano(s):
    s = unicodedata.normalize("NFKD", (s or "").lower())
    return "".join(c for c in s if not unicodedata.combining(c))


def _clase_relacion(texto):
    t = _plano(texto)
    if "deroga" in t:
        return "deroga"
    if "dicta de conformidad" in t:
        return "se dicta de conformidad"
    if "modifica" in t or "anade" in t or "añade" in t:
        return "modifica"
    return None


def construir(cfg):
    """Devuelve {nodos, aristas, metricas} listo para pintar."""
    ruta = cfg_mod.db(cfg)
    con = sqlite3.connect(ruta)
    try:
        normas = con.execute(
            "SELECT n.identificador, n.titulo, n.rango, COUNT(a.bloque_id) "
            "FROM normas n LEFT JOIN articulos a ON a.norma_id = n.identificador "
            "GROUP BY n.identificador").fetchall()
        cargadas = {n[0] for n in normas}
        cambios = con.execute(
            "SELECT norma, relacion, norma_relacionada, detalle FROM cambios").fetchall()
        textos = con.execute("SELECT norma_id, texto FROM articulos").fetchall()
    finally:
        con.close()

    nodos = {nid: {"id": nid, "titulo": tit, "rango": rango, "articulos": arts,
                   "url": f"https://www.boe.es/buscar/act.php?id={nid}"}
             for nid, tit, rango, arts in normas}

    aristas, vistos = [], set()

    def anade(a, b, tipo, detalle="", articulos=""):
        if not a or not b or a == b:
            return
        clave = (a, b, tipo)
        if clave in vistos:
            return
        vistos.add(clave)
        aristas.append({"desde": a, "hacia": b, "tipo": tipo,
                        "detalle": detalle[:180], "articulos": articulos})

    # 1. relaciones de vigencia (solo entre normas que tenemos: si no, el nodo no existe)
    for norma, relacion, otra, detalle in cambios:
        tipo = _clase_relacion(relacion)
        if tipo and otra in cargadas:
            anade(norma, otra, tipo, detalle or relacion, "")
        elif tipo and otra and otra not in cargadas:
            # arista hacia fuera del corpus: se anota como externa
            aristas.append({"desde": norma, "hacia": otra, "tipo": tipo,
                            "detalle": (detalle or relacion)[:180], "externo": True})

    # 2. menciones cruzadas por alias (norma que nombra a otra en su texto)
    alias = []
    for n in cfg["normas"]:
        for a in n.get("alias", []):
            al = _plano(a)
            if len(al) >= 4:
                alias.append((n["id"], al))
    for norma_id, texto in textos:
        t = _plano(texto)
        for otro_id, al in alias:
            if otro_id == norma_id:
                continue
            if re.search(rf"(?<![a-z0-9]){re.escape(al)}(?![a-z0-9])", t):
                anade(norma_id, otro_id, "menciona", al, "")
                if len(aristas) > 4000:      # tope de seguridad para el dibujo
                    break

    por_tipo = {}
    for a in aristas:
        por_tipo[a["tipo"]] = por_tipo.get(a["tipo"], 0) + 1

    return {
        "nodos": list(nodos.values()),
        "aristas": aristas,
        "metricas": {
            "normas": len(nodos),
            "aristas": len(aristas),
            "por_tipo": por_tipo,
            "externas": sum(1 for a in aristas if a.get("externo")),
        },
        "leyenda": TIPOS,
    }


def exportar_dot(cfg, ruta=None):
    g = construir(cfg)
    ruta = ruta or os.path.join(cfg["_raiz"], "informes", "grafo-normas.dot")
    os.makedirs(os.path.dirname(ruta), exist_ok=True)
    L = ["digraph LeyClara {", '  graph [rankdir=LR, bgcolor="white"];',
         '  node [shape=box, style="rounded,filled", fillcolor="#f8fafc", fontname="Helvetica"];']
    for n in g["nodos"]:
        etiqueta = n["titulo"][:48].replace('"', "'")
        L.append(f'  "{n["id"]}" [label="{etiqueta}\\n{n["articulos"]} arts"];')
    for a in g["aristas"]:
        color = TIPOS.get(a["tipo"], "#64748b")
        dash = ' style=dashed' if a.get("externo") else ""
        L.append(f'  "{a["desde"]}" -> "{a["hacia"]}" '
                 f'[label="{a["tipo"]}", color="{color}", fontsize=9{dash}];')
    L.append("}")
    with open(ruta, "w", encoding="utf-8") as f:
        f.write("\n".join(L))
    return ruta, g["metricas"]
