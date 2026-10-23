# HARNESS — qué debe cumplir LeyClara

Este documento es el **contrato de aceptación** del proyecto: qué tiene que hacer el
sistema, cómo se comprueba y qué forma tiene la respuesta. Si algo no cumple un criterio
de aquí, no está terminado, por bien que se vea.

---

## 1. Los cuatro fallos que hay que medir

| Fallo | Qué es | Se mide con |
|---|---|---|
| **Falso positivo** | Afirma algo que no responde a lo preguntado | banco, entradas `esperado: null` |
| **Falso negativo — recuperación** | El precepto aplicable no llegó ni al pool | `recall@k` sobre el banco |
| **Falso negativo — omisión** | Estaba en el pool y no se citó | posición del esperado vs `max_citas` |
| **Hueco de cobertura** | La norma aplicable **no está cargada** | `abstención` + `candidatas` del catálogo |

El cuarto no es un fallo del buscador: es una decisión de producto. Pero si no se mide,
se disfraza de «no consta» y el usuario cree que no existe la ley.

**El quinto fallo, que no aparece en ningún banco: el banco miente.** En tres pasadas de
este harness el banco apuntó a bloques que no eran la respuesta (un `a1902` inexistente
en el Código Civil, un artículo del concurso del que valía el 2 **o** el 3, y el art. 1
del RD 244/2019 cuando las modalidades de autoconsumo están en el art. 4). Por eso C10 es
obligatorio antes de creerse cualquier métrica.

---

## 2. Criterios de aceptación (C1–C12)

| # | Criterio | Umbral | Cómo se verifica |
|---|---|---|---|
| **C1** | Ninguna afirmación sin cita literal del BOE | **0 excepciones** | `verificar.py`; el informe debe marcar `bloqueadas = 0` en extractivo |
| **C2** | El gate distingue paráfrasis de invención | 100 % de los casos | `pruebas/test_harness.py` (5 motivos) |
| **C3** | Toda ley citada es un hipervínculo a la norma o al artículo | **0 leyes sin enlazar** | recuento en el DOM / informe |
| **C4** | Recall@k en el banco | ≥ 0,95 | `leyclara evaluar` |
| **C5** | Abstención correcta en preguntas sin dato | ≥ 0,90 | banco, entradas `esperado: null` |
| **C6** | Falsos positivos en negativas | **0** | banco |
| **C7** | «No consta» siempre dice **qué falta** | 100 % | campo `candidatas` + nota de motivo |
| **C8** | Todo plazo citado va señalado, sin calcularlo | 100 % | campo `plazos` + nota obligatoria |
| **C9** | La UI pasa el auditor del design system y el móvil medido | 0 fallos · sin desborde | `auditar-uso.py` + CDP |
| **C10** | El banco se valida contra el corpus antes de usarse | 0 referencias inexistentes | `leyclara banco` |
| **C11** | Si la pregunta pide un **tipo de dato** (importe, plazo, porcentaje), el precepto citado lo contiene | 100 % | `responder.tipo_dato` / `contiene_dato` |
| **C12** | Nunca hay veredicto `VERIFICADO` sin al menos una cita que lo respalde | **0 casos** | aserción en `responder` + test |

C11 y C12 nacieron de fallos reales medidos, no de la teoría:

- **C11**: «¿importe de la tasa por expedición del DNI?» devolvía el **art. 648 de la
  LEC (subasta electrónica)** con cita literal y veredicto verde. La cita era verdad y la
  respuesta era falsa. Un precepto sin euros no puede responder a una pregunta de importe.
- **C12**: dos preguntas negativas salían `VERIFICADO` con **cero citas** (el gate había
  rechazado todo y el veredicto solo miraba si hubo rechazos). Una insignia verde sin nada
  debajo es la peor salida posible: afirma sin respaldo.

### Estado medido hoy (26 normas cargadas · banco de 27 preguntas)

| Criterio | Medición | Cumple |
|---|---|---|
| C1 | 0 citas bloqueadas en extractivo | ✅ |
| C2 | 14 pruebas en verde | ✅ |
| C3 | 0 leyes sin enlazar | ✅ |
| C4 | **recall 1,00 (22/22)** | ✅ |
| C5 | **0,80 (4/5)** | ❌ |
| C6 | **1 falso positivo** (ver §7) | ❌ |
| C7 | implementado (catálogo de 12.437 normas) | ✅ |
| C8 | detecta cifra y letra («cinco días») | ✅ |
| C9 | 0 fallos de auditor · sin desborde | ✅ |
| C10 | 27/27 válidas | ✅ |
| C11 | implementado; cierra el FP de la tasa del DNI | ✅ |
| C12 | implementado; ya no hay verde sin cita | ✅ |

> **El harness honesto dice que no cumple 2 de 12.** C5 y C6 son el mismo problema
> residual: el sistema prefiere responder a abstenerse cuando el dato existe en el corpus
> pero **pertenece a otro sujeto**. Ese es el trabajo pendiente, no el diseño.

**Por qué esta tabla cambió a mejor de golpe:** el mismo banco, sin tocar el modelo, pasó
de 20/22 a 22/22 al descubrir que la recuperación estaba devolviendo **preámbulos y
encabezados de capítulo** (2.184 bloques de 11.684) como si fueran artículos. El top-3 de
«autoconsumo» era el preámbulo del RD 244/2019. Filtrar por `tipo = 'precepto'` subió el
recall 0,909 → 0,955… y el último punto era del banco, no del motor.

---

## 3. El contrato de respuesta (lo que devuelve el motor)

`POST /api/preguntar` → JSON con esta forma **estable**:

```json
{
  "pregunta": "texto original",
  "modo": "extractivo | llm",
  "veredicto": "VERIFICADO | NO CONSTA | REVISAR",
  "afirmaciones": [
    { "texto": "Artículo 56",
      "norma": "BOE-A-2015-11430",
      "bloque": "a56",
      "cita": "fragmento literal del BOE",
      "ok": true,
      "motivo": "ok",
      "url": "https://www.boe.es/buscar/act.php?id=...#a56" }
  ],
  "grupos":     [ { "norma": "...", "titulo_norma": "...", "articulos": [...] } ],
  "puentes":    [ { "desde": "...", "desde_art": "...", "hacia": "...", "evidencia": "«...»" } ],
  "plazos":     [ { "cantidad": 20, "unidad": "día", "literal": "veinte días" } ],
  "fuentes":    [ { "norma": "...", "bloque": "...", "url": "...", "n_versiones": 4 } ],
  "candidatas": [ { "identificador": "...", "titulo": "...", "origen": "catalogo local" } ],
  "notas":      [ "avisos al usuario" ]
}
```

### Reglas invariantes

1. **`afirmaciones` solo contiene texto que pasó el gate.** Si no pasa, no se incluye.
2. **`url` va siempre**, en cada afirmación y en cada fuente. `#bloque` solo si el bloque
   es numérico (`a245`, `art1902`).
3. **`candidatas` es la respuesta al hueco de cobertura**: qué existe y no tenemos.
4. **`plazos` nunca calcula**: detecta y señala. El cómputo exige calendario procesal.
5. **`veredicto` es la interfaz**. O verificado con cita, o no consta con motivo, o
   revisar. Nunca verde vacío (C12).
6. **La unidad citable es el precepto.** Nunca se cita un preámbulo, un índice ni un
   encabezado de capítulo, aunque el ranking los ponga arriba.

---

## 4. Los seis tipos de respuesta que buscamos

| Tipo | Pregunta de ejemplo | Qué debe devolver | Estado |
|---|---|---|---|
| **1. Extractiva simple** | «¿plazo para reclamar por despido?» | 1-3 preceptos, cita literal, enlace, plazo señalado | ✅ |
| **2. Multi-norma con puente** | «¿cómo aplica el incumplimiento de Costas en el Código Civil?» | Cuota por norma + puentes leídos del texto, o aviso de que el enlace es interpretativo | ✅ |
| **3. Abstención informada** | «¿cuánto cuesta renovar el pasaporte?» | «No consta» + qué falta + norma candidata del catálogo | ✅ |
| **4. Caso aplicado** | «tengo una casa de 30 años en dominio público» | Disposiciones (DT/DA) + articulado, con la advertencia de que el encaje es interpretativo | ✅ |
| **5. Vigencia / histórica** | «¿qué decía la ley en 1995?» | Solo la última versión consolidada; el histórico está en el XML sin explotar | ⏳ |
| **6. Dato pedido que el precepto no contiene** | «¿qué plazo de garantía comercial debe dar el fabricante?» | Cita el precepto aplicable **y dice expresamente que no fija ese dato**; jamás rellena la cifra | ⚠️ parcial |

**Lo que NO queremos**: párrafos generados con una cita al final. Queremos **precepto →
texto → enlace**, y que el sistema diga lo que no sabe. Y si el dato pedido no está en el
precepto, decirlo: en derecho, una cifra sin precepto es un error, no una aproximación.

---

## 5. Cómo se ejecuta

```bash
python -m leyclara banco        # valida el banco contra el corpus (C10)
python -m leyclara evaluar      # corre el banco y escribe informes/informe-FECHA.md
python -m unittest discover -s pruebas    # gate y utilidades, sin red (C2)
python -m leyclara grafo        # relaciones entre normas (DOT) · /grafo para el mapa
python scripts/auditar-uso.py web/index.html   # Aurora (C9)
```

El informe es el entregable: tabla de métricas, **huecos detectados**, detalle por
pregunta con cita y enlace, y las candidatas no cargadas.

---

## 6. Cuándo se considera «hecho»

1. Los tests pasan (`unittest`).
2. El banco valida (0 referencias inexistentes).
3. El informe se regenera y **las métricas no empeoran** — o si empeoran, está escrito por qué.
4. La UI pasa el auditor y el móvil medido (si toca UI).
5. El commit dice qué se midió, con números.

---

## 7. Estado y deuda declarada

| Deuda | Impacto | Palanca |
|---|---|---|
| **FP residual: dato de otro sujeto** | «plazo de garantía comercial» cita el art. 127 bis («repuestos durante diez años»): el plazo existe, pero es de otra cosa. Es C6 ❌ | Modo LLM con pregunta de verificación («¿este texto responde a *plazo de garantía comercial*?») o cross-encoder de pares |
| Cobertura: 26 de 12.437 normas (0,2 %) | El límite real de «encontrar todo». El grafo lo dibuja: 986 de 1.197 relaciones apuntan a normas que no tenemos | Ingesta por ramas (5 hechas) + catálogo de 12.437 para avisar |
| Sin versiones históricas | No responde «la ley en 1995» | Guardar todas las `<version>` del XML |
| Banco de 27 preguntas, 5 ramas | Un banco pequeño se aprueba solo | Ampliar por ramas; cada nueva rama ya ha destapado un fallo real |
| Cifras sin precepto | C11 cubre importe/plazo/porcentaje; sanciones y escalas quedan fuera | Ampliar `tipo_dato` con «sanción», «cuantía», «grado» |

> Basado en datos de la Agencia Estatal Boletín Oficial del Estado — https://www.boe.es
> Los textos consolidados son de carácter meramente informativo. No es asesoramiento jurídico.
