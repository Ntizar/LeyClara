"""Servidor local del chat. Solo libreria estandar: http.server + ThreadingHTTPServer.

Por que local y no una web publica: el corpus legal es publico, pero en cuanto el
usuario suba SU documentacion, sacarla de su equipo deja de ser una decision
tecnica y pasa a ser secreto profesional. Aqui nada sale de la maquina salvo la
llamada al modelo si se activa el modo asistido.

Uso:  python -m leyclara servir [--puerto 8765]
"""

import json
import os
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from . import config as cfg_mod
from . import responder as resp_mod

WEB = os.path.join(cfg_mod.RAIZ, "web")


def _html():
    with open(os.path.join(WEB, "index.html"), encoding="utf-8") as f:
        return f.read()


class Handler(BaseHTTPRequestHandler):
    cfg = None

    def log_message(self, fmt, *args):  # silencio: no ensuciar la consola
        if os.environ.get("LEYCLARA_DEBUG"):
            sys.stderr.write("%s - %s\n" % (self.address_string(), fmt % args))

    def _enviar(self, codigo, cuerpo, tipo="application/json; charset=utf-8"):
        datos = cuerpo if isinstance(cuerpo, bytes) else cuerpo.encode("utf-8")
        self.send_response(codigo)
        self.send_header("Content-Type", tipo)
        self.send_header("Content-Length", str(len(datos)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(datos)

    def do_GET(self):
        if self.path in ("/", "/index.html"):
            return self._enviar(200, _html(), "text/html; charset=utf-8")
        if self.path in ("/grafo", "/grafo.html"):
            with open(os.path.join(WEB, "grafo.html"), encoding="utf-8") as f:
                return self._enviar(200, f.read(), "text/html; charset=utf-8")
        if self.path == "/api/grafo":
            from . import grafo
            return self._enviar(200, json.dumps(grafo.construir(self.cfg),
                                                ensure_ascii=False))
        if self.path == "/api/estado":
            import sqlite3
            from . import ingesta
            d = ingesta.estado(self.cfg)
            try:
                con = sqlite3.connect(cfg_mod.db(self.cfg))
                vec = con.execute("SELECT COUNT(*) FROM vectores").fetchone()[0]
                con.close()
            except Exception:  # noqa: BLE001
                vec = 0
            n = self.cfg["normas"]
            return self._enviar(200, json.dumps({
                "normas_cargadas": d.get("normas", 0),
                "normas_config": len(n),
                "articulos": d.get("articulos", 0),
                "vectores": vec,
                "hibrido": vec > 0 and self.cfg["recuperacion"].get("modo") == "hibrido",
                "modo": self.cfg["recuperacion"].get("modo"),
                "llm": self.cfg["llm"].get("modelo"),
            }, ensure_ascii=False))
        return self._enviar(404, json.dumps({"error": "no existe"}))

    def _leer_cuerpo(self):
        """JSON tolerante: en Windows el cuerpo puede llegar en cp1252 si el cliente
        no declara charset (un '¿' en cp1252 es 0xBF y revienta el decode utf-8)."""
        largo = int(self.headers.get("Content-Length", 0))
        crudo = self.rfile.read(largo) if largo else b"{}"
        for codificacion in ("utf-8", "utf-8-sig", "cp1252", "latin-1"):
            try:
                return json.loads(crudo.decode(codificacion))
            except (UnicodeDecodeError, json.JSONDecodeError):
                continue
        return {}

    def do_POST(self):
        if self.path != "/api/preguntar":
            return self._enviar(404, json.dumps({"error": "no existe"}))
        try:
            cuerpo = self._leer_cuerpo()
            pregunta = (cuerpo.get("pregunta") or "").strip()
            if not pregunta:
                return self._enviar(400, json.dumps({"error": "pregunta vacia"}))
            if cuerpo.get("modo") == "llm":
                r = resp_mod.responder_llm(self.cfg, pregunta)
            else:
                r = resp_mod.responder(self.cfg, pregunta)
            r["llm_modelo"] = self.cfg["llm"].get("modelo")
            return self._enviar(200, json.dumps(r, ensure_ascii=False))
        except Exception as e:  # noqa: BLE001
            return self._enviar(500, json.dumps({
                "error": str(e),
                "veredicto": "REVISAR",
                "afirmaciones": [], "fuentes": [], "grupos": [], "puentes": [],
                "plazos": [], "notas": ["Fallo interno. No se muestra nada sin verificar."],
            }, ensure_ascii=False))


def servir(puerto=8788, cfg=None):
    cfg = cfg or cfg_mod.cargar()
    Handler.cfg = cfg

    class Servidor(ThreadingHTTPServer):
        # En Windows, SO_REUSEADDR permite que DOS procesos se enganchen al mismo
        # puerto y las peticiones se reparten al azar (nos pasó: respondía otro
        # servidor en 8765). Aquí se desactiva a proposito para fallar claro.
        allow_reuse_address = False

    try:
        httpd = Servidor(("127.0.0.1", puerto), Handler)
    except OSError as e:
        print(f"Puerto {puerto} ocupado ({e}). Prueba otro: --puerto 8789")
        return
    print(f"LeyClara en http://127.0.0.1:{puerto}  (Ctrl+C para parar)")
    print(f"  corpus: {cfg_mod.db(cfg)}  ·  recuperación: {cfg['recuperacion'].get('modo')}")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nParado.")
    finally:
        httpd.server_close()
