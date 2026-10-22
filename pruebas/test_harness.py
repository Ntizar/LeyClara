"""Pruebas del harness. Sin red, sin corpus real: se construye una BD de juguete.

Ejecutar:  python -m unittest discover -s pruebas -v
"""

import os
import sqlite3
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from leyclara.responder import detectar_plazos, extraer_cita  # noqa: E402
from leyclara.verificar import Gate, canon  # noqa: E402

TEXTO = ("La tasación de costas podrá ser impugnada dentro del plazo a que se refiere "
         "el apartado 1 del artículo anterior. La impugnación podrá basarse en que se "
         "han incluido en la tasación partidas no devengadas.")


def bd_juguete():
    con = sqlite3.connect(":memory:")
    con.executescript("""
    CREATE TABLE normas(identificador TEXT PRIMARY KEY, titulo TEXT, url_html TEXT);
    CREATE TABLE articulos(norma_id TEXT, bloque_id TEXT, texto TEXT);
    """)
    con.execute("INSERT INTO normas VALUES('BOE-A-2000-323','Ley de Enjuiciamiento Civil','https://www.boe.es/x')")
    con.execute("INSERT INTO articulos VALUES('BOE-A-2000-323','a245',?)", (TEXTO,))
    con.commit()
    return con


class TestCanon(unittest.TestCase):
    def test_conserva_tildes(self):
        # En derecho una tilde cambia el sentido: NO se normalizan los acentos.
        self.assertNotEqual(canon("el deposito"), canon("el depósito"))

    def test_ignora_comillas_tipograficas_y_espacios(self):
        self.assertEqual(canon('«La  Ley»'), canon('"la ley"'))


class TestGate(unittest.TestCase):
    def setUp(self):
        self.gate = Gate({}, con=bd_juguete())

    def test_cita_literal_pasa(self):
        ok, motivo, _ = self.gate.verificar({
            "norma": "BOE-A-2000-323", "bloque": "a245",
            "cita": "La tasación de costas podrá ser impugnada dentro del plazo"})
        self.assertTrue(ok, motivo)

    def test_norma_inventada_se_bloquea(self):
        ok, motivo, _ = self.gate.verificar({
            "norma": "BOE-A-2024-99999", "bloque": "a1", "cita": "texto"})
        self.assertFalse(ok)
        self.assertEqual(motivo, "norma_inexistente")

    def test_articulo_inventado_se_bloquea(self):
        ok, motivo, _ = self.gate.verificar({
            "norma": "BOE-A-2000-323", "bloque": "a9999", "cita": "texto"})
        self.assertFalse(ok)
        self.assertEqual(motivo, "articulo_inexistente")

    def test_cifra_inventada_se_bloquea(self):
        ok, motivo, detalle = self.gate.verificar({
            "norma": "BOE-A-2000-323", "bloque": "a245",
            "cita": "será necesario depositar trescientos euros para impugnar la tasación"})
        self.assertFalse(ok)
        self.assertEqual(motivo, "cita_no_literal")
        self.assertIn("trescientos", detalle)

    def test_parafrasis_se_bloquea_como_tal(self):
        # Mismas palabras, otro orden: suena bien pero no es el precepto.
        ok, motivo, _ = self.gate.verificar({
            "norma": "BOE-A-2000-323", "bloque": "a245",
            "cita": "podrá ser impugnada la tasación de costas"})
        self.assertFalse(ok)
        self.assertIn(motivo, ("parafrasis_no_literal", "cita_no_literal"))

    def test_sin_cita_se_bloquea(self):
        ok, motivo, _ = self.gate.verificar({
            "norma": "BOE-A-2000-323", "bloque": "a245", "cita": ""})
        self.assertFalse(ok)
        self.assertEqual(motivo, "sin_cita_literal")

    def test_respuesta_entera_invalida_si_una_falla(self):
        valida, res = self.gate.verificar_todo([
            {"norma": "BOE-A-2000-323", "bloque": "a245",
             "cita": "La tasación de costas podrá ser impugnada"},
            {"norma": "BOE-A-2000-323", "bloque": "a245", "cita": "plazo de veinte días"},
        ])
        self.assertFalse(valida)
        self.assertEqual(len(res), 2)


class TestPlazos(unittest.TestCase):
    def test_detecta_plazo_en_cifra(self):
        p = detectar_plazos("se estará al plazo de 20 días hábiles")
        self.assertEqual(p[0]["cantidad"], 20)
        self.assertEqual(p[0]["unidad"], "día")

    def test_detecta_plazo_en_letra(self):
        # La LEC escribe "cinco días", no "5 días"
        p = detectar_plazos("se oirá en el plazo de cinco días al abogado")
        self.assertEqual(p[0]["cantidad"], 5)
        self.assertEqual(p[0]["literal"], "cinco días")

    def test_sin_plazo(self):
        self.assertEqual(detectar_plazos("la tasación de costas se impugnará"), [])


class TestCita(unittest.TestCase):
    def test_corta_en_frontera_de_frase(self):
        c = extraer_cita(TEXTO, 120)
        self.assertLessEqual(len(c), 121)
        self.assertTrue(c.endswith(".") or c.endswith("…"))

    def test_texto_corto_se_devuelve_entero(self):
        self.assertEqual(extraer_cita("Hola.", 600), "Hola.")


if __name__ == "__main__":
    unittest.main()
