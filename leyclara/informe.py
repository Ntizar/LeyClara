"""Harness de evaluacion e informe final.

Clasifica cada pregunta del banco en UNA de estas cinco categorias, porque no
todos los fallos son iguales:

  acierto                  el precepto esperado se cita y se verifica
  falso_negativo_omision   esta en el top-k, pero no llego a la respuesta
  falso_negativo_recuperacion  ni siquiera se recupero (LA LEY NO SE REVISO)
  abstencion_correcta      no habia respuesta y dijo "no consta"
  falso_positivo           no habia respuesta y respondio igualmente

Los dos `falso_negativo_*` son el fallo silencioso: no avisa, simplemente no
mira donde deberia. El `falso_positivo` es el que da miedo.
"""

import datetime
import json
import os

from . import config as cfg_mod
from . import responder as responder_mod

NO_ASESORAMIENTO = (
    "LeyClara no presta asesoramiento jurídico. Los textos son textos consolidados "
    "del BOE de carácter meramente informativo: únicamente tienen carácter oficial y "
    "auténtico los publicados en la edición electrónica del BOE. Verifique siempre el "
    "enlace oficial antes de actuar."
)


def leer_banco(ruta):
    entradas = []
    with open(ruta, encoding="utf-8") as f:
        for i, linea in enumerate(f, 1):
            linea = linea.strip()
            if not linea or linea.startswith("#"):
                continue
            e = json.loads(linea)
            e.setdefault("id", f"q{i:02d}")
            entradas.append(e)
    return entradas


def evaluar(cfg, ruta_banco, top_k=None):
    entradas = leer_banco(ruta_banco)
    filas = []
    for e in entradas:
        r = responder_mod.responder(cfg, e["pregunta"], top_k)
        citados = {(a["norma"], a["bloque"]) for a in r["afirmaciones"] if a.get("ok")}
        recuperados = {(f["norma"], f["bloque"]) for f in r["fuentes"]}
        bloqueados = [a for a in r["afirmaciones"] if not a.get("ok")]
        esp = e.get("esperado")

        if esp is None:
            clase = "abstencion_correcta" if r["veredicto"] == "NO CONSTA" else "falso_positivo"
        else:
            clave = (esp["norma"], esp["bloque"])
            if clave in citados:
                clase = "acierto"
            elif clave in recuperados:
                clase = "falso_negativo_omision"
            else:
                clase = "falso_negativo_recuperacion"

        filas.append({
            "id": e["id"], "pregunta": e["pregunta"], "tipo": e.get("tipo", ""),
            "esperado": esp, "clase": clase, "veredicto": r["veredicto"],
            "citados": sorted(citados), "recuperados": sorted(recuperados),
            "bloqueados": bloqueados, "plazos": r["plazos"], "notas": r["notas"],
            "fuentes": r["fuentes"], "grupos": r.get("grupos", []),
            "puentes": r.get("puentes", []), "afirmaciones": r.get("afirmaciones", []),
            "candidatas": r.get("candidatas", []),
        })

    def n(clase):
        return sum(1 for f in filas if f["clase"] == clase)

    positivas = sum(1 for f in filas if f["esperado"] is not None)
    negativas = len(filas) - positivas
    metricas = {
        "total": len(filas),
        "positivas": positivas,
        "negativas": negativas,
        "acierto": n("acierto"),
        "falso_negativo_omision": n("falso_negativo_omision"),
        "falso_negativo_recuperacion": n("falso_negativo_recuperacion"),
        "abstencion_correcta": n("abstencion_correcta"),
        "falso_positivo": n("falso_positivo"),
        "gate_bloqueados": sum(len(f["bloqueados"]) for f in filas),
        "recall_respuesta": round(n("acierto") / positivas, 3) if positivas else None,
        "tasa_abstencion": round(n("abstencion_correcta") / negativas, 3) if negativas else None,
    }
    return {"fecha": datetime.date.today().isoformat(), "metricas": metricas, "filas": filas}


def _tabla_metricas(m):
    return "\n".join([
        "| Métrica | Valor | Qué significa si falla |",
        "|---|---|---|",
        f"| Preguntas evaluadas | {m['total']} ({m['positivas']} con respuesta + {m['negativas']} sin respuesta) | — |",
        f"| **Acierto** | **{m['acierto']}/{m['positivas']}** (recall {m['recall_respuesta']}) | no llega al precepto correcto |",
        f"| Falso negativo — omisión | {m['falso_negativo_omision']} | estaba en el top-k y no se citó |",
        f"| **Falso negativo — recuperación** | **{m['falso_negativo_recuperacion']}** | **la ley aplicable no se revisó** |",
        f"| Abstención correcta | {m['abstencion_correcta']}/{m['negativas']} (tasa {m['tasa_abstencion']}) | responde cuando no hay dato |",
        f"| **Falso positivo** | **{m['falso_positivo']}** | respondió sin respaldo (lo peor) |",
        f"| Afirmaciones bloqueadas por el gate | {m['gate_bloqueados']} | 0 esperado en modo extractivo |",
    ])


def _enlace(src, incluir_ancla=True):
    """Enlace oficial al precepto.

    Verificado 2026-10-22: la pagina consolidada del BOE usa id="a245" y su propio
    indice enlaza a #a245, asi que el ancla funciona para articulos numericos.
    Los preceptos con letra (bis/ter) usan anclas distintas (#a2-15 para el 245 bis),
    asi que para esos se devuelve la pagina sin ancla en vez de un enlace que no salta.
    """
    import re as _re
    url = src.get("url", "")
    blq = src.get("bloque", "")
    # Los ids del BOE son "a245" (LEC, CP...) o "art1902" (Codigo Civil): ambos valen
    # como ancla en la pagina consolidada. Los bis/ter usan otra numeracion.
    if incluir_ancla and _re.fullmatch(r"(?:a|art)\d+", blq or ""):
        return f"{url}#{blq}"
    return url


def escribir_informe(cfg, resultado, ruta=None):
    m = resultado["metricas"]
    dir_inf = os.path.join(cfg["_raiz"], cfg.get("informe", {}).get("dir", "informes"))
    os.makedirs(dir_inf, exist_ok=True)
    ruta = ruta or os.path.join(dir_inf, f"informe-{resultado['fecha']}.md")

    L = []
    L.append(f"# Informe LeyClara — {resultado['fecha']}\n")
    L.append(f"> {NO_ASESORAMIENTO}\n")
    L.append("## 1. Resumen\n")
    veredicto_global = (
        "✅ **Sin falsos positivos** en el banco." if m["falso_positivo"] == 0
        else f"⛔ **{m['falso_positivo']} falsos positivos** — revisar antes de usar.")
    L.append(veredicto_global)
    L.append("")
    L.append(_tabla_metricas(m))
    L.append("")

    huecos = [f for f in resultado["filas"] if f["clase"].startswith("falso_negativo")]
    L.append("## 2. Huecos detectados (ley aplicable no revisada)\n")
    if not huecos:
        L.append("Ninguno en este banco.\n")
    else:
        L.append("| Pregunta | Esperado | Clase | Por qué |")
        L.append("|---|---|---|---|")
        for f in huecos:
            esp = f["esperado"]
            razon = ("estaba entre los candidatos pero fuera de las citas mostradas"
                     if f["clase"] == "falso_negativo_omision"
                     else "no apareció en la recuperación")
            L.append(f"| {f['pregunta']} | {esp['norma']} · {esp['bloque']} | {f['clase']} | {razon} |")
        L.append("")

    L.append("## 3. Detalle pregunta a pregunta\n")
    for f in resultado["filas"]:
        icono = {"acierto": "✅", "abstencion_correcta": "✅", "falso_negativo_omision": "⚠️",
                 "falso_negativo_recuperacion": "⛔", "falso_positivo": "⛔"}[f["clase"]]
        L.append(f"### {icono} {f['id']} — {f['pregunta']}\n")
        L.append(f"- **Veredicto:** `{f['veredicto']}` · **Clase:** `{f['clase']}`")
        if f["esperado"]:
            L.append(f"- **Esperado:** {f['esperado']['norma']} · bloque `{f['esperado']['bloque']}`")
        if f["plazos"]:
            L.append("- **Plazos citados:** " + ", ".join(
                f"{p['cantidad']} {p['unidad']}" for p in f["plazos"]))
        L.append("")
        for a in f["bloqueados"]:
            L.append(f"> 🚫 **BLOQUEADO por el gate** (`{a['motivo']}`): {a['texto']}")
            L.append(f"> {a.get('detalle','')}")
            L.append("")
        if f.get("grupos"):
            L.append("- **Preceptos por norma:**")
            for g in f["grupos"]:
                arts = ", ".join(a["titulo_bloque"] or a["bloque"] for a in g["articulos"])
                L.append(f"  - {g['titulo_norma']} → {arts}")
            L.append("")
        verificado = [a for a in f.get("afirmaciones", []) if a.get("ok")]
        if verificado:
            L.append("- **Citas verificadas** (toda ley nombrada, enlazada):")
            for a in verificado:
                url = a.get("url") or _enlace({"url": f"https://www.boe.es/buscar/act.php?id={a['norma']}",
                                               "bloque": a.get("bloque", "")},
                                              cfg.get("informe", {}).get("incluir_enlace_oficial", True))
                L.append(f"  - [{a['texto']} · {a['norma']}]({url})")
            L.append("")
        if f.get("puentes"):
            L.append("- 🔗 **Puentes entre normas** (leídos del texto oficial):")
            for p in f["puentes"]:
                L.append(f"  - `{p['desde']}` art. {p['desde_art']} → **{p['hacia_nombre']}**")
                L.append(f"    «{p['evidencia'][:200]}»")
            L.append("")
        citadas = [a for a in f.get("afirmaciones", []) if a.get("ok")]
        vistos_url = set()
        for src in f["fuentes"]:
            enlace = _enlace(src, cfg.get("informe", {}).get("incluir_enlace_oficial", True))
            if enlace in vistos_url:
                continue
            vistos_url.add(enlace)
            L.append(f"- 📎 *{src['titulo_bloque'] or src['bloque']}* — {src['titulo_norma']}")
            L.append(f"  Fuente oficial: {enlace}")
        L.append("")
        for nota in f["notas"]:
            L.append(f"- {nota}")
        L.append("")

    L.append("## 4. Cómo reproducir este informe\n")
    L.append("```bash")
    L.append("python -m leyclara ingesta          # corpus desde la API del BOE")
    L.append("python -m leyclara evaluar          # corre el banco y escribe este informe")
    L.append("```")
    L.append("")
    L.append("## 5. Fuente y condiciones de reutilización\n")
    L.append("Basado en datos de la Agencia Estatal Boletín Oficial del Estado "
             "(https://www.boe.es). Los textos consolidados no tienen carácter oficial.\n")

    with open(ruta, "w", encoding="utf-8") as fh:
        fh.write("\n".join(L))
    return ruta
