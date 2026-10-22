# LeyClara

**Hablar con el BOE sin alucinaciones.** Asistente de legislación española cuyas respuestas
siempre son texto literal del Boletín Oficial del Estado, verificadas por un *gate*
determinista, con enlace a la fuente oficial y un informe que dice si la respuesta está
bien o mal.

Sin dependencias (solo librería estándar de Python), sin claves de API, sin base de datos
externa. El corpus se descarga de la API de datos abiertos del BOE.

---

## 1. Las dos formas de fallar (el porqué del diseño)

Un asistente jurídico puede equivocarse de dos maneras, y **la segunda casi nadie la mide**:

| Fallo | Qué es | Cómo se combate aquí |
|---|---|---|
| **Falso positivo** | Inventa una cifra, un plazo o un artículo que no existe | **Gate**: la cita debe aparecer *textualmente* en el precepto |
| **Falso negativo** | La ley aplicable existe, pero **no la miró** | **Harness**: se mide el recall y se listan los huecos |

Y dos matices que en derecho son la diferencia entre servir y no servir:

- **Parafrasear ya es fallar.** "El plazo es de diez días" suena perfecto y puede ser falso.
  El gate distingue `cita` de `parafrasis_no_literal`.
- **Un plazo mal computado es un plazo perdido.** LeyClara **detecta y señala** los plazos
  citados, pero **no los calcula**: el cómputo (día inicial, hábiles, suspensiones) exige el
  calendario procesal y no está implementado. Se declara en cada respuesta.

**Principio rector:** el "0 fallos" no lo da un modelo que acierte siempre. Lo da una
arquitectura en la que **es imposible mostrar un dato que no esté en el texto oficial**.

---

## 2. Instalación

Requisitos: Python 3.9 o superior. Nada más.

```bash
git clone <este-repo> LeyClara
cd LeyClara
python -m unittest discover -s pruebas -v     # 14 pruebas del harness, sin red
```

No hay `pip install`. No hay `requirements.txt` a propósito: si un día lo hay, será por la
capa vectorial, no por el núcleo.

---

## 3. Configuración: `config.json`

Todo el comportamiento del sistema se controla desde **un único fichero**. No hay variables
de entorno ni rutas mágicas.

```json
{
  "corpus":      { "db": "corpus/leyclara.db", "jsonl": "corpus/articulos.jsonl" },
  "boe":         { "base": "...", "user_agent": "...", "reintentos": 3, "pausa_ms": 400 },
  "recuperacion":{ "top_k": 5, "solo_vigentes": false, "min_caracteres_articulo": 15 },
  "respuesta":   { "modo": "extractivo", "max_citas": 3, "max_caracteres_cita": 600 },
  "llm":         { "habilitado": false, "...": "..." },
  "informe":     { "dir": "informes", "incluir_enlace_oficial": true },
  "normas":      [ { "id": "BOE-A-2000-323", "nombre": "LEC", "nucleo": true } ]
}
```

### Campo a campo

| Clave | Qué controla | Cuándo tocarlo |
|---|---|---|
| `corpus.db` | Dónde vive el SQLite del corpus | Si quieres varios corpus (p. ej. por cliente) |
| `corpus.jsonl` | Volcado plano de artículos (para embeddings/auditoría) | Al conectar la capa vectorial |
| `boe.base` | Endpoint de la API | Nunca, salvo cambio del BOE |
| `boe.user_agent` | Identificación ante el BOE | **Pon tu contacto**: sin User-Agent propio el BOE devuelve 403 |
| `boe.pausa_ms` | Espera entre peticiones | Súbelo si el BOE te limita; bájalo si tienes prisa |
| `recuperacion.top_k` | Cuántos artículos se recuperan por pregunta | Súbelo si hay falsos negativos por omisión |
| `recuperacion.solo_vigentes` | Filtra a normas con vigencia no agotada | `true` en producción |
| `recuperacion.min_caracteres_articulo` | Descarta bloques basura (encabezados) | Rara vez |
| `respuesta.modo` | `extractivo` (0 tokens) o `llm` (gasta tokens) | Ver §6 |
| `respuesta.max_citas` | Cuántos preceptos se muestran (y se verifican) | Súbelo para preguntas que abarcan varias normas |
| `respuesta.max_caracteres_cita` | Longitud del extracto literal | Bájalo para respuestas más escuetas |
| `llm.habilitado` | Enciende el modo asistido | Solo si aceptas coste por token |
| `informe.dir` | Dónde se escriben los informes | — |
| `normas[]` | **El catálogo de leyes cargadas** | Ver §5 |

### ⚠️ Las normas van con identificador curado, no buscadas

`config.json` guarda el `BOE-A-AAAA-NNNNN` de cada ley **a mano, a propósito**.
La búsqueda por título de la API del BOE **no ordena por relevancia**: al pedir
`titulo:"Código Civil"` devuelve primero el Código Civil **de Cataluña** y leyes que
*modifican* el Código Civil. Verificado en vivo. Por eso el catálogo es explícito.

---

## 4. Primer arranque

```bash
python -m leyclara init        # crea el corpus vacío
python -m leyclara ingesta     # descarga las 10 normas del núcleo (~5-8 min)
python -m leyclara estado      # qué hay dentro
```

Salida de `ingesta`: una línea por norma con artículos y cambios de vigencia.

```
  [ 1] BOE-A-1978-31229   210 arts ·   12 cambios · Constitución Española.
  [ 2] BOE-A-1889-4763   2441 arts ·   85 cambios · Real Decreto de 24 de julio de 1889...
  ...
== 10 normas · 8651 artículos · 771 cambios · 6240 remisiones
```

### Estado real de esta entrega (medido, no prometido)

Corpus: **10 normas · 8.651 artículos · 771 relaciones de vigencia · 6.240 remisiones ·
24,1 MB** (de ellos **2.898 artículos con redacción modificada**, el 33 %).

Banco de 15 preguntas (12 con respuesta + 3 sin respuesta), modo extractivo:

| Métrica | Valor |
|---|---|
| Acierto | **7/12** (recall 0,583) |
| Falso negativo — recuperación | **5** ← el fallo silencioso que hay que bajar |
| Falso negativo — omisión | 0 |
| Abstención correcta | 2/3 |
| **Falso positivo** | **1** |
| **Afirmaciones bloqueadas por el gate** | **0** |

Ese `1` de falso positivo está identificado: *"¿importe de la tasa del DNI?"* devuelve los
arts. 647-648 de la LEC porque hablan de «tasa» en otro sentido. Es un fallo **léxico**, y
es exactamente lo que arreglará la capa vectorial.

Los 5 falsos negativos son todos del mismo tipo: la pregunta usa un vocabulario que el
precepto no emplea («pena por homicidio» frente a «castigado con la pena de…»). Un
recuperador léxico no los ve; uno semántico sí.

### Preguntar

```bash
python -m leyclara pregunta "¿Se puede impugnar la tasación de costas si los honorarios son excesivos?"
```

```
✅  VERIFICADO  —  «¿Se puede impugnar la tasación de costas...?»
   modo: extractivo

  ✅  BOE-A-2000-323 · a245 · Artículo 245
     «Impugnación de la tasación de costas y solicitud de exoneración o moderación...»

  📎 https://www.boe.es/buscar/act.php?id=BOE-A-2000-323#a245
```

Añade `--json` para la salida estructurada completa (afirmaciones, motivos del gate,
fuentes, plazos, notas) y así integrarlo en cualquier interfaz.

---

## 5. Añadir una ley

Tres pasos y ninguno más:

1. **Busca el identificador** en <https://www.boe.es/buscar/legislacion.php> — en la ficha,
   el campo *Identificador* es del tipo `BOE-A-2015-11430`. **No lo busques por título en la
   API** (ver aviso arriba).
2. **Añádelo a `config.json`**:

```json
{ "id": "BOE-A-1985-12666", "nombre": "Ley Orgánica del Poder Judicial", "nucleo": true }
```

3. **Ingesta sólo esa norma** (no re-descarga las demás):

```bash
python -m leyclara ingesta --norma BOE-A-1985-12666
```

La ingesta es **idempotente y resumible**: volver a ejecutarla para una norma borra y
reescribe sólo esa norma. Para actualizar todo el corpus tras un cambio normativo:

```bash
python -m leyclara ingesta        # recorre todas las normas del config
```

> Empezar con 10 normas es deliberado: el coste está en la calidad del harness, no en el
> volumen. Añadir las 12.300 normas consolidadas del BOE es un bucle de una noche, pero
> sólo tiene sentido cuando el banco de evaluación ya mide bien estas 10.

---

## 6. Los dos modos

### `extractivo` (por defecto — 0 tokens, 0 alucinación posible)

No hay generación de lenguaje. Se recuperan preceptos y **se citan literalmente**. El
usuario lee texto del BOE, no una redacción del modelo. Es el modo que se puede poner
delante de un abogado sin pedir perdón.

### `llm` (opcional — gasta tokens, gate obligatorio)

```bash
# config.json → "llm": { "habilitado": true, "endpoint": "http://127.0.0.1:8080/v1/chat/completions", "modelo": "..." }
python -m leyclara pregunta "..." --llm
```

El modelo recibe el contexto recuperado y devuelve afirmaciones estructuradas
(`norma`, `bloque`, `cita`). **El gate las verifica una a una**; lo que no pasa, no se
muestra. Si el modelo inventa, se ve en el informe como *bloqueado*, no como respuesta.

Sirve cualquier servidor compatible con la API de OpenAI: `llama.cpp`, Ollama, vLLM o un
proveedor en la nube. Pero el modelo **nunca** es la fuente de la verdad: sólo redacta.

---

## 7. El gate

Tres asserts deterministas sobre cada afirmación:

1. **La norma existe** en el corpus.
2. **El bloque existe** dentro de esa norma.
3. **La cita aparece textualmente** en ese artículo.

Motivos de rechazo:

| Motivo | Significado |
|---|---|
| `norma_inexistente` | El identificador `BOE-A-...` no está en el corpus (¿inventado? ¿no cargado?) |
| `articulo_inexistente` | La norma existe pero ese artículo no |
| `sin_cita_literal` | No se aporta texto literal: no se puede verificar |
| `parafrasis_no_literal` | Las palabras existen pero **reordenadas**: es reformulación, no cita |
| `cita_no_literal` | Hay contenido que **no está** en el precepto (cifras, plazos, incisos) |

Detalle importante: la comparación **conserva las tildes** (`deposito` ≠ `depósito`),
normaliza comillas tipográficas y espacios, pero no perdona acentos. En derecho, una tilde
cambia el sentido.

---

## 8. El harness y el informe

### El banco (`banco/preguntas.jsonl`)

Una pregunta por línea. `esperado` es el precepto que **debe** citarse; `null` significa
*no hay dato en el corpus y debe abstenerse*.

```json
{"id":"q02","tipo":"plazo","pregunta":"¿Cuál es el plazo para apelar una sentencia?",
 "esperado":{"norma":"BOE-A-2000-323","bloque":"a458"}}
{"id":"q13","tipo":"negativa","pregunta":"¿Cuál es la tasa del DNI?","esperado":null}
```

**Valida el banco antes de fiarte** —el banco también puede mentir:

```bash
python -m leyclara banco
```

Comprueba que cada `norma`+`bloque` existe de verdad y, si no, sugiere el identificador
correcto.

### Evaluar

```bash
python -m leyclara evaluar      # → informes/informe-YYYY-MM-DD.md
```

Clasifica cada pregunta en una de cinco categorías —porque no todos los fallos son iguales:

| Clase | Significado |
|---|---|
| `acierto` | El precepto esperado se cita y se verifica |
| `falso_negativo_omision` | Estaba en el top-k, pero no llegó a la respuesta |
| `falso_negativo_recuperacion` | **Ni siquiera se recuperó: la ley aplicable no se revisó** |
| `abstencion_correcta` | No había dato y dijo "no consta" |
| `falso_positivo` | No había dato y respondió igualmente |

El informe incluye: tabla de métricas, **sección de huecos detectados**, detalle pregunta a
pregunta con la cita literal, y **enlace a la fuente oficial de cada precepto** para
comprobarlo a mano.

### Qué encontró el harness en la primera pasada (y se corrigió)

Esto es lo que justifica tener harness y no sólo un chatbot: tres fallos reales que no se
ven leyendo el código.

| # | Fallo encontrado | Cómo se detectó | Corrección |
|---|---|---|---|
| 1 | **El banco mentía**: 2 de 15 preguntas apuntaban a bloques inexistentes (`a1902` en el Código Civil, que usa `art1902`) | `python -m leyclara banco` | el banco se valida contra el corpus antes de usarse, y sugiere el ID correcto |
| 2 | **Un AND demasiado listo tapaba la respuesta**: para «tasación de costas…» el art. 246 casaba con *todos* los términos y el 245 nunca llegaba a verse | recall cayó de 6/12 a 2/12 | una sola pasada OR (recall) y la cobertura como **filtro**, no como criterio de orden |
| 3 | **El recorte de la cita rompía la literalidad**: se añadía «…» al truncar, así que 2 citas verdaderas eran bloqueadas por el gate | el informe marcó `2 afirmaciones bloqueadas` en modo extractivo, donde debe ser 0 | el truncado nunca añade caracteres |

Los tres son ejemplos del mismo principio: **el sistema tiene que ser capaz de decirte que
se equivoca**. Un chatbot que sólo acierta "casi siempre" no te lo dice nunca.

---

## 9. Estructura

```
LeyClara/
├── config.json              ← ÚNICO punto de configuración
├── AVISO-LEGAL.md           ← condiciones del BOE + no es asesoramiento
├── banco/preguntas.jsonl    ← banco de evaluación
├── leyclara/
│   ├── config.py            carga y resuelve rutas
│   ├── boe.py               cliente de la API (con las trampas documentadas)
│   ├── ingesta.py           BOE → SQLite, troceado por artículo + grafo de remisiones
│   ├── recuperar.py         BM25 sobre FTS5
│   ├── verificar.py         GATE (3 asserts)
│   ├── responder.py         composición extractiva / modo LLM
│   ├── informe.py           harness + informe markdown
│   └── cli.py               init · ingesta · estado · pregunta · banco · evaluar
├── pruebas/test_harness.py  14 pruebas sin red
├── informes/                informes generados (evidencia, se versiona)
└── corpus/                  generado, NO se versiona (regenerable)
```

### Esquema de datos

| Tabla | Contenido |
|---|---|
| `normas` | Identificador, título, rango, departamento, fechas, vigencia, URL |
| `articulos` | **Un artículo = una fila** (bloque, título, texto literal, nº de versiones, fecha de vigencia) |
| `articulos_fts` | Índice FTS5 (BM25) sobre título de bloque y texto |
| `cambios` | Grafo de vigencia del `/analisis` del BOE: `SE MODIFICA`, `SE DEROGA`, `SE DICTA DE CONFORMIDAD`… |
| `remisiones` | Grafo artículo → artículo extraído del propio texto |

No se trocea por número de caracteres ni por tokens: **la unidad citable es el precepto**.

---

## 10. Trampas del BOE ya resueltas (para que no las sufras)

| Trampa | Realidad verificada |
|---|---|
| `?limit=-1` devuelve todo | **No**: corta en 10.000 y no avisa. Hay que paginar con `offset` |
| `/id/{id}` acepta JSON | **No**: devuelve 400. Ese endpoint es XML-only |
| Buscar por título funciona | Devuelve normas modificadoras y códigos autonómicos homónimos |
| Sin cabeceras | 403 |
| El texto consolidado es el oficial | **No**: es informativo. El oficial es el diario publicado |

---

## 11. Limitaciones declaradas

1. **Recuperación sólo léxica (BM25)**. Una pregunta con vocabulario muy distinto al del
   precepto puede no encontrarlo → falso negativo. La capa vectorial + RRF está pendiente.
2. **Sin cómputo de plazos**. Detecta y señala; no calcula.
3. **Cobertura = lo que hay en `config.json`**. "No consta" puede significar "no está cargada".
4. **El modo `llm` no está probado end-to-end en esta entrega** (no hay modelo conectado por
   defecto). El modo extractivo sí está probado y medido.
5. **Desfase de consolidación**: hasta 1-3 días hábiles desde la publicación de una modificación.

---

## 12. Aviso

LeyClara **no presta asesoramiento jurídico**. Los textos son consolidados del BOE de
carácter meramente informativo. Lea `AVISO-LEGAL.md` antes de usar esto con clientes.

> Basado en datos de la Agencia Estatal Boletín Oficial del Estado — <https://www.boe.es>
