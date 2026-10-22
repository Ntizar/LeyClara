"""Cliente de la API de legislacion consolidada del BOE.

Trampas verificadas en vivo (2026-10-22) y por que este codigo es asi:

  * `/id/{id}` y `/id/{id}/texto` SOLO responden XML. Con `Accept: application/json`
    devuelven 400. No es un fallo nuestro.
  * `?limit=-1` NO devuelve todo: corta en 10.000 y no avisa. Hay que paginar
    con `offset`.
  * Sin `User-Agent` propio la API devuelve 403.
  * La busqueda por titulo NO ordena por relevancia (devuelve normas que
    *modifican* la buscada, o codigos autonomicos homonimos), asi que las normas
    del nucleo van con identificador curado en config.json, no buscadas.
"""

import json
import time
import urllib.parse
import urllib.request


class BOE:
    def __init__(self, cfg):
        b = cfg["boe"]
        self.base = b["base"]
        self.ua = b["user_agent"]
        self.reintentos = b.get("reintentos", 3)
        self.timeout = b.get("timeout_s", 120)
        self.pausa = b.get("pausa_ms", 400) / 1000.0

    def _get(self, url, accept="application/xml"):
        ultimo = None
        for intento in range(self.reintentos):
            req = urllib.request.Request(url, headers={"Accept": accept, "User-Agent": self.ua})
            try:
                with urllib.request.urlopen(req, timeout=self.timeout) as r:
                    return r.read()
            except Exception as e:  # noqa: BLE001
                ultimo = e
                time.sleep(1.5 * (intento + 1))
        raise RuntimeError(f"BOE no responde: {url} ({ultimo})")

    # ---- endpoints ----
    def indice(self, limit=500, offset=0):
        url = f"{self.base}?limit={limit}&offset={offset}"
        data = json.loads(self._get(url, accept="application/json"))["data"]
        if isinstance(data, dict):
            data = [data]
        return data or []

    def metadatos(self, nid):
        import html as _html
        import re
        raw = self._get(f"{self.base}/id/{nid}/metadatos").decode("utf-8", "replace")

        def tag(t):
            m = re.search(rf"<{t}\b[^>]*>(.*?)</{t}>", raw, re.S)
            return _html.unescape(m.group(1).strip()) if m else ""

        time.sleep(self.pausa)
        return {
            "identificador": tag("identificador") or nid,
            "titulo": tag("titulo"),
            "rango": tag("rango"),
            "departamento": tag("departamento"),
            "fecha_publicacion": tag("fecha_publicacion"),
            "fecha_actualizacion": tag("fecha_actualizacion"),
            "vigencia_agotada": tag("vigencia_agotada"),
            "url_html": f"https://www.boe.es/buscar/act.php?id={nid}",
        }

    def texto(self, nid):
        raw = self._get(f"{self.base}/id/{nid}/texto").decode("utf-8", "replace")
        time.sleep(self.pausa)
        return raw

    def analisis(self, nid):
        raw = self._get(f"{self.base}/id/{nid}/analisis").decode("utf-8", "replace")
        time.sleep(self.pausa)
        return raw
