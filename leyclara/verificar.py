"""GATE — la puerta por la que pasa (o no) toda afirmacion juridica.

El "0 fallos" no lo da el modelo: lo da esto. Tres asserts deterministas:

  1. la norma existe en el corpus
  2. el bloque (articulo) existe dentro de esa norma
  3. la cita aparece TEXTUALMENTE en ese articulo

Si falla cualquier assert, la afirmacion se rechaza y la respuesta degrada a
"No consta". El gate NO reescribe, NO corrige, NO adivina: solo rechaza.

Dos motivos de rechazo que importan en derecho:
  * `parafrasis_no_literal` — el texto existe pero reformulado. En derecho,
    parafrasear un precepto ya es un fallo aunque "suene bien".
  * `cita_no_literal` — hay contenido que no esta en el precepto (se invento).
"""

import os
import re
import sqlite3
import unicodedata

from . import config as cfg_mod


def canon(s):
    """Normaliza para comparar. NO quita tildes: en derecho una tilde cambia el sentido."""
    s = unicodedata.normalize("NFC", s or "")
    for a, b in (("«", '"'), ("»", '"'), ("“", '"'), ("”", '"'), ("’", "'")):
        s = s.replace(a, b)
    s = s.replace("\u00a0", " ")
    s = re.sub(r"\s+", " ", s)
    return s.strip().lower()


class Gate:
    def __init__(self, cfg, con=None):
        self.con = con
        if self.con is None:
            ruta = cfg_mod.db(cfg)
            if not os.path.exists(ruta):
                raise FileNotFoundError(f"Falta el corpus ({ruta}).")
            self.con = sqlite3.connect(ruta)
            self._propia = True
        else:
            self._propia = False

    def cerrar(self):
        if self._propia:
            self.con.close()

    def norma(self, nid):
        return self.con.execute(
            "SELECT titulo, url_html FROM normas WHERE identificador=?", (nid,)).fetchone()

    def bloque(self, nid, bloque_id):
        return self.con.execute(
            "SELECT texto FROM articulos WHERE norma_id=? AND bloque_id=?",
            (nid, bloque_id)).fetchone()

    def verificar(self, af):
        """(ok, motivo, detalle) para una afirmacion {norma, bloque, cita}."""
        nid, blq, cita = af.get("norma", ""), af.get("bloque", ""), af.get("cita", "")

        n = self.norma(nid)
        if not n:
            return False, "norma_inexistente", f"{nid} no esta en el corpus"
        b = self.bloque(nid, blq)
        if not b:
            return False, "articulo_inexistente", f"{nid} no tiene el bloque {blq}"
        if not canon(cita):
            return False, "sin_cita_literal", "la afirmacion no aporta texto literal"
        if canon(cita) not in canon(b[0]):
            palabras = [w for w in canon(cita).split() if len(w) > 4]
            faltan = [w for w in palabras if w not in canon(b[0])][:6]
            if not faltan:
                return False, "parafrasis_no_literal", \
                    "las palabras existen pero no en ese orden: es reformulacion, no cita"
            return False, "cita_no_literal", f"contenido ausente del precepto; sobra: {faltan}"
        return True, "ok", n[0]

    def verificar_todo(self, afirmaciones):
        res = []
        for af in afirmaciones:
            ok, motivo, detalle = self.verificar(af)
            res.append({**af, "ok": ok, "motivo": motivo, "detalle": detalle})
        valida = bool(res) and all(r["ok"] for r in res)
        return valida, res
