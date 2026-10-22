"""CLI de LeyClara: init · ingesta · estado · pregunta · banco · evaluar."""

import argparse
import json
import os
import sqlite3
import sys

from . import config as cfg_mod
from . import ingesta as ing_mod
from . import informe as inf_mod
from . import responder as resp_mod

ICONO = {"VERIFICADO": "✅", "NO CONSTA": "❔", "REVISAR": "⚠️"}


def _cfg(args):
    return cfg_mod.cargar(getattr(args, "config", None))


def cmd_init(args):
    cfg = _cfg(args)
    ruta = cfg_mod.db(cfg)
    os.makedirs(os.path.dirname(ruta), exist_ok=True)
    con = sqlite3.connect(ruta)
    ing_mod.crear(con)
    con.close()
    print(f"✅ Corpus inicializado en {ruta}")
    print("   Siguiente paso:  python -m leyclara ingesta           (10 normas del núcleo)")
    print("                    python -m leyclara ingesta --norma BOE-A-1978-31229")


def cmd_ingesta(args):
    cfg = _cfg(args)
    st = ing_mod.ingestar(cfg, ids=args.norma or None)
    print(f"\n== {st['normas']} normas · {st['articulos']} artículos · "
          f"{st['cambios']} cambios · {st['remisiones']} remisiones")
    if args.exportar:
        ruta, n = ing_mod.exportar_jsonl(cfg)
        print(f"   exportado {n} artículos a {ruta}")
    for e in st["errores"]:
        print(f"   !! {e}", file=sys.stderr)


def cmd_estado(args):
    cfg = _cfg(args)
    d = ing_mod.estado(cfg)
    if not d["existe"]:
        print("Sin corpus. Ejecuta: python -m leyclara init && python -m leyclara ingesta")
        return
    print(f"Normas:      {d['normas']}")
    print(f"Artículos:   {d['articulos']}  (de ellos, {d['modificados']} con redacción modificada)")
    print(f"Cambios:     {d['cambios']}")
    print(f"Remisiones:  {d['remisiones']}")
    print(f"Tamaño:      {d['mb']} MB")
    print("\nDetalle:")
    for nid, tit, n in d["detalle"]:
        print(f"  {nid:>18}  {n:>5} arts  {tit[:60]}")


def cmd_vectorial(args):
    cfg = _cfg(args)
    from . import vectorial
    st = vectorial.construir(cfg, limite=args.limite)
    print(f"\n== {st['embebidos']} artículos embebidos · {st['tokens']:,} tokens")


def cmd_pregunta(args):
    cfg = _cfg(args)
    if args.lexico:
        cfg["recuperacion"]["modo"] = "lexico"
    if args.llm:
        r = resp_mod.responder_llm(cfg, args.texto, args.top)
    else:
        r = resp_mod.responder(cfg, args.texto, args.top)

    if args.json:
        print(json.dumps(r, ensure_ascii=False, indent=2))
        return

    print(f"\n{ICONO.get(r['veredicto'],'')}  {r['veredicto']}  —  «{args.texto}»")
    print(f"   modo: {r['modo']} · recuperación: {cfg['recuperacion'].get('modo')}")
    if r.get("normas_nombradas"):
        print(f"   normas nombradas en la pregunta: {', '.join(r['normas_nombradas'])}")
    print()
    for a in r["afirmaciones"]:
        marca = "✅" if a["ok"] else f"🚫 {a['motivo']}"
        print(f"  {marca}  {a['norma']} · {a['bloque']} · {a['texto']}")
        print(f'     «{a["cita"][:300]}{"…" if len(a["cita"])>300 else ""}»')
        print()
    if r.get("puentes"):
        print("  🔗 puentes entre normas (leídos del texto oficial):")
        for p in r["puentes"]:
            print(f"     {p['desde']} art.{p['desde_art']} → {p['hacia_nombre']} ({p['hacia']})")
            print(f"       «{p['evidencia'][:180]}»")
        print()
    if r["plazos"]:
        print("  Plazos citados: " + ", ".join(f"{p['cantidad']} {p['unidad']}" for p in r["plazos"]))
    vistos = set()
    for f in r["fuentes"]:
        ancla = f"#{f['bloque']}" if __import__("re").fullmatch(r"(?:a|art)\d+", f["bloque"] or "") else ""
        url = f"{f['url']}{ancla}"
        if url in vistos:
            continue
        vistos.add(url)
        print(f"  📎 {url}")
        if len(vistos) >= (args.top or 5):
            break
    for n in r["notas"]:
        print(f"  · {n}")


def cmd_banco(args):
    """Valida el banco contra el corpus: sin esto, el banco tambien miente."""
    cfg = _cfg(args)
    entradas = inf_mod.leer_banco(args.banco)
    con = sqlite3.connect(cfg_mod.db(cfg))
    ok = fallos = 0
    for e in entradas:
        esp = e.get("esperado")
        if esp is None:
            print(f"  OK      {e['id']}  (negativa: debe abstenerse)")
            ok += 1
            continue
        existe = con.execute(
            "SELECT 1 FROM articulos WHERE norma_id=? AND bloque_id=?",
            (esp["norma"], esp["bloque"])).fetchone()
        if existe:
            print(f"  OK      {e['id']}  {esp['norma']} · {esp['bloque']}")
            ok += 1
        else:
            fallos += 1
            print(f"  FALTA   {e['id']}  {esp['norma']} · {esp['bloque']}")
            pista = con.execute(
                "SELECT bloque_id, titulo_bloque FROM articulos "
                "WHERE norma_id=? AND titulo_bloque LIKE ? LIMIT 4",
                (esp["norma"], f"%{esp['bloque'].lstrip('a').split('bis')[0]}%")).fetchall()
            for p in pista:
                print(f"            ¿querías {p[0]} ({p[1]})?")
    con.close()
    print(f"\n{ok} entradas válidas, {fallos} con referencia inexistente")
    sys.exit(1 if fallos else 0)


def cmd_evaluar(args):
    cfg = _cfg(args)
    print(f"Evaluando {args.banco} …")
    resultado = inf_mod.evaluar(cfg, args.banco, args.top)
    ruta = inf_mod.escribir_informe(cfg, resultado)
    m = resultado["metricas"]
    print(f"\n== Acierto {m['acierto']}/{m['positivas']} (recall {m['recall_respuesta']}) · "
          f"falsos negativos {m['falso_negativo_omision'] + m['falso_negativo_recuperacion']} · "
          f"falsos positivos {m['falso_positivo']} · "
          f"abstención {m['abstencion_correcta']}/{m['negativas']}")
    print(f"   informe: {ruta}")


def main(argv=None):
    p = argparse.ArgumentParser(prog="leyclara", description="Hablar con el BOE sin alucinaciones.")
    p.add_argument("--config", help="ruta alternativa a config.json")
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("init", help="crea el corpus vacío").set_defaults(func=cmd_init)

    pi = sub.add_parser("ingesta", help="descarga del BOE y trocea por artículo")
    pi.add_argument("--norma", action="append", help="BOE-A-... (repetible)")
    pi.add_argument("--exportar", action="store_true", help="volcar articulos.jsonl")
    pi.set_defaults(func=cmd_ingesta)

    ps = sub.add_parser("estado", help="qué hay cargado")
    ps.set_defaults(func=cmd_estado)

    pv = sub.add_parser("vectorial", help="construye el índice de embeddings (capa semántica)")
    pv.add_argument("--limite", type=int, help="embeber solo los N primeros (pruebas)")
    pv.set_defaults(func=cmd_vectorial)

    pp = sub.add_parser("pregunta", help="responde una pregunta con citas verificadas")
    pp.add_argument("texto")
    pp.add_argument("--top", type=int)
    pp.add_argument("--json", action="store_true")
    pp.add_argument("--llm", action="store_true", help="modo asistido (gasta tokens)")
    pp.add_argument("--lexico", action="store_true", help="forzar solo BM25")
    pp.set_defaults(func=cmd_pregunta)

    pb = sub.add_parser("banco", help="valida el banco de evaluación contra el corpus")
    pb.add_argument("--banco", default=os.path.join("banco", "preguntas.jsonl"))
    pb.set_defaults(func=cmd_banco)

    pe = sub.add_parser("evaluar", help="corre el banco y escribe el informe")
    pe.add_argument("--banco", default=os.path.join("banco", "preguntas.jsonl"))
    pe.add_argument("--top", type=int)
    pe.set_defaults(func=cmd_evaluar)

    args = p.parse_args(argv)
    if getattr(args, "banco", None) and not os.path.isabs(args.banco):
        args.banco = os.path.join(cfg_mod.RAIZ, args.banco)
    args.func(args)


if __name__ == "__main__":
    main()
