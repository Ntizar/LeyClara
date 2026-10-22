"""Configuracion del proyecto: un unico fichero config.json, sin dependencias."""

import json
import os

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _ruta(p):
    return p if os.path.isabs(p) else os.path.join(RAIZ, p)


def cargar(path=None):
    path = path or os.path.join(RAIZ, "config.json")
    with open(path, encoding="utf-8") as f:
        cfg = json.load(f)
    cfg["_raiz"] = os.path.dirname(os.path.abspath(path))
    return cfg


def ruta(cfg, clave):
    """Resuelve rutas relativas del config contra la raiz del proyecto."""
    return _ruta(cfg[clave]) if isinstance(cfg[clave], str) else None


def db(cfg):
    return _ruta(cfg["corpus"]["db"])


def normas(cfg, nucleo=True):
    return [n for n in cfg["normas"] if n.get("nucleo")] if nucleo else cfg["normas"]


def norma_por_id(cfg, nid):
    for n in cfg["normas"]:
        if n["id"] == nid:
            return n
    return None
