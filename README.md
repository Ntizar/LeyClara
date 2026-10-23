# LeyClara

**Hablar con el BOE sin alucinaciones.** Asistente de legislación española cuyas respuestas
siempre son texto literal del Boletín Oficial del Estado, verificadas por un *gate*
determinista, con enlace a la fuente oficial y un informe que dice si la respuesta está
bien o mal.

Sin dependencias (solo librería estándar de Python), sin claves de API, sin base de datos
externa. El corpus se descarga de la API de datos abiertos del BOE.

---

## 0. Cómo se usa (y en qué soporte)

LeyClara es **un motor**, no una app. Ese motor se puede usar de tres maneras, y conviene
tener claro cuál es cuál:

| Boca | Para quién | Qué es | Estado |
|---|---|---|---|
| **1. Línea de comandos** | tú, para auditar y para cron | `python -m leyclara pregunta "..."` devuelve veredicto + citas literales + enlace oficial | ✅ hecho |
| **2. Chat local (web)** | el usuario final | `python -m leyclara servir` abre un chat en `http://127.0.0.1:8788` con veredicto, preceptos y enlace al BOE | ✅ hecho |
| **3. API HTTP** | integrarlo en otro producto (panel, gestor, dashboard) | `POST /api/preguntar` → JSON con `veredicto`, `afirmaciones`, `puentes` | ✅ hecho (la web ya consume esa API) |

**Por qué el chat va en local y no en una web pública**: en cuanto el usuario suba *sus*
documentos (un contrato, un expediente), sacarlos de su equipo deja de ser una decisión
técnica y pasa a ser un problema de secreto profesional. El motor es el mismo; lo que cambia
es dónde vive el corpus.

**El flujo de uso real, en tres pasos:**

```
1. cargas las leyes que te interesan        → config.json (una línea por ley)
2. construyes el índice                     → python -m leyclara ingesta
                                              python -m leyclara vectorial
3. preguntas y LEE EL VEREDICTO             → python -m leyclara pregunta "..."
```

Y la regla de oro de la interfaz: **el veredicto manda**.

- `✅ VERIFICADO` → todo lo que se muestra es texto literal del BOE, con enlace.
- `❔ NO CONSTA` → no hay precepto aplicable en el corpus. **No es un fallo del sistema,
  es una respuesta.**
- `⚠️ REVISAR` → algo no pasó el gate y se muestra marcado.

Esa tercera línea es la que ningún chatbot te da: no "confía en mí", sino "esto es lo que
he podido comprobar y esto es lo que no".

### Arrancar el chat

```bash
python -m leyclara servir            # http://127.0.0.1:8788
python -m leyclara servir --puerto 8790
```

Detalles de la interfaz (Aurora v10.1.0, packs `p1 p2 p3 p5 p6 p9 p14`):

- Veredicto como insignia con icono del sprite del sistema (`nz-i-069` verificado,
  `nz-i-073` no consta, `nz-i-072` revisar). **Cero emojis en la UI**: el auditor de
  Aurora los caza y con razón.
- Cada cita va en un `nz-callout` con su insignia "cita verificada" o el motivo del bloqueo.
- Interruptor **modo asistido** en la barra: apagado = extractivo (0 tokens);
  encendido = LLM + gate (`qwen3.6`).
- Servidor sólo en `127.0.0.1`: no escucha en la red.
- Verificado: `auditar-uso.py` de Aurora → **0 fallos**; sin desborde a 320/360/390 px;
  botón de envío a 44 px (táctil).

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

Corpus: **26 normas · 11.684 artículos** (9.500 citables como precepto) **· 1.429
relaciones de vigencia · 11.684 vectores**. Cinco ramas: núcleo civil/procesal/penal/
administrativo, laboral, consumo, energía y urbanismo/familia.

| Dato | Valor |
|---|---|
| Texto jurídico | 11.684 bloques (~24 MB), de los que **9.500 son preceptos citables** |
| Artículos con redacción modificada | ~2.898 (33 %) |
| Índice vectorial | 11.684 × 4.096 dims · **~1,8 M tokens** de embeddings |
| Coste del índice | pago único; regenerar sólo cuando cambie el corpus |
| Relaciones entre normas | 1.197 aristas (642 modifica · 253 deroga · 181 menciona · 121 conformidad) |

Banco de **27 preguntas** (22 con respuesta + 5 sin respuesta) en 5 ramas. Cada paso,
medido con el mismo banco:

| Configuración | Acierto | Recall | Falsos neg. | Falsos pos. | Abstención |
|---|---|---|---|---|---|
| Sólo léxico (BM25), 11 normas, banco 15 | 7/12 | 0,583 | 5 | 1 | 2/3 |
| Híbrido (BM25 + vectorial + RRF), 11 normas | 11/12 | 0,917 | 1 | 1 | 2/3 |
| Híbrido, top_k 50 + rerank denso | 12/12 | 1,000 | 0 | 1 | 2/3 |
| + 15 normas nuevas y banco de 27 | 20/22 | 0,909 | 2 | 2 | 3/5 |
| **+ filtro de citabilidad (`tipo = 'precepto'`)** | 21/22 | 0,955 | 1 | 2 | 3/5 |
| **+ banco corregido (art. 4 RD 244/2019)** | **22/22** | **1,000** | **0** | 2 | 3/5 |
| **+ C11 tipo de dato y C12 verde sin cita** | **22/22** | **1,000** | **0** | **1** | **4/5** |

Dos lecciones que costaron medidas reales, no opiniones:

1. **Ampliar el corpus empeora la métrica antes de mejorarla.** Con 26 normas el recall
   cayó de 1,000 a 0,909 — no porque el motor empeorara, sino porque el banco nuevo hacía
   preguntas más difíciles. Un banco que sólo crece en aciertos no mide nada.
2. **La recuperación estaba citando preámbulos y encabezados de capítulo.** 2.184 de los
   11.684 bloques no son preceptos, y el top-3 de «autoconsumo» era el preámbulo del
   RD 244/2019. Filtrar por `tipo = 'precepto'` es una línea de SQL y valía 0,046 de recall.

El único falso positivo que queda está identificado y medido: *«¿qué plazo de garantía
comercial debe dar el fabricante de un electrodoméstico?»* cita el art. 127 bis del
TRLGDCU («repuestos durante **diez años**»). El dato existe en el corpus, pero es de otro
sujeto. Cerrarlo requiere verificación semántica del par pregunta-cita, no otra regla
léxica. Está en `HARNESS.md` §7 como deuda declarada.

### El falso positivo que trae el vectorial (y cómo se corta)

Un buscador vectorial **siempre** devuelve "lo más parecido": sin umbral, el sistema
contestaba a las 3 preguntas sin respuesta. Se corta con `min_similitud` (coseno mínimo),
calibrado por barrido:

| `min_similitud` | Acierto | Falsos pos. | Abstención |
|---|---|---|---|
| 0,30 | 11/12 | 3 | 0/3 |
| 0,45 | 11/12 | 2 | 1/3 |
| **0,50** | **11/12** | **1** | **2/3** |
| 0,65 | 10/12 | 1 | 2/3 |

Estable entre 0,50 y 0,60; se elige **0,50** para no ahogar preguntas que nombran dos
normas (el Código Civil se quedaba a 0,001 del corte con 0,55).

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

### Saltar entre normas (lo que pediste: Costas → Código Civil)

Cuando la pregunta **nombra dos cuerpos legales**, el sistema cambia de estrategia:

1. **Detecta las normas nombradas** por alias (`config.json → normas[].alias`).
2. **Busca dentro de cada una** por separado, no sólo en el conjunto.
3. **Reparte cuota**: si hay 2 normas y 3 huecos, cada norma aporta al menos un precepto
   antes de rellenar. Sin esto, la norma léxicamente dominante ocupaba todo el top.
4. **Lee puentes en el texto oficial**: si un artículo citado menciona otra norma del
   corpus, se muestra como `🔗 puente` con la frase literal que lo prueba.

```bash
python -m leyclara pregunta "¿Cómo se aplica el incumplimiento de la Ley de Costas en el Código Civil?"
```

Y aquí hay un hallazgo que conviene saber: **la Ley de Costas no menciona el Código Civil
ni una sola vez en sus 202 artículos** (comprobado). Por tanto el enlace Costas→Civil
**no es textual**: es interpretativo. El sistema hace entonces lo único honesto:

- En **modo extractivo** te da los preceptos de ambas normas con su cita literal y **no
  inventa el puente**.
- En **modo `llm`**, el modelo propone el enlace y **el gate verifica cada mitad**: las
  citas son literales y comprobables. Ejemplo real ejecutado:

```
✅ VERIFICADO — «¿Cómo se aplica el incumplimiento de la Ley de Costas en el Código Civil?»
  ✅ BOE-A-1988-18762 · a91 · «Tendrán el carácter de infracciones leves las acciones u
     omisiones...» (Ley de Costas)
  ✅ BOE-A-1988-18762 · a91 · «El incumplimiento de lo establecido en materia de
     servidumbres... es infracción leve.»
  ✅ BOE-A-1889-4763 · tercera · «Las disposiciones del Código que sancionan con penalidad
     civil o privación de derechos actos u omisiones...» (Código Civil, D.T. 3.ª)
  · Borrador generado por qwen3.8-flash y filtrado por el gate.
```

> ⚠️ **Límite que hay que decir en voz alta:** el gate garantiza que **cada cita es literal
> y existe**. NO garantiza que el **razonamiento** que las une sea el correcto. Eso sigue
> siendo criterio profesional. Lo que elimina el gate es la alucinación documental, que es
> la que hace impresentable un asistente jurídico.

Coste real del modo `llm`: **~11.000 tokens por consulta** con `qwen3.8-flash` (es un
modelo de razonamiento: se gastó 41.880 caracteres pensando antes de responder). Los
modelos `deepseek-v4-flash`, `qwen3.6` y `glm5.3-flash` **agotaron el límite razonando y
devolvieron contenido vacío** — comprobado con el prompt real. Por eso el modo por defecto
es el extractivo.

---

## 8. El harness: qué debe cumplir

`HARNESS.md` es el **contrato de aceptación** del proyecto: 10 criterios (C1–C10) con
umbral medible, el esquema de respuesta y los cinco tipos de respuesta que buscamos
(extractiva, multi-norma con puente, abstención informada, vigencia histórica y caso
aplicado).

| Criterio | Umbral |
|---|---|
| C1 · ninguna afirmación sin cita literal | 0 excepciones |
| C2 · el gate distingue paráfrasis de invención | 100 % en tests |
| C3 · toda ley nombrada, enlazada | 0 sin enlace |
| C4 · recall@k en el banco | ≥ 0,95 |
| C5 · abstención correcta | ≥ 0,90 |
| C6 · falsos positivos en negativas | 0 |
| C7 · «no consta» dice qué falta | 100 % |
| C8 · plazos señalados, nunca calculados | 100 % |
| C9 · UI en auditor y móvil medido | 0 fallos |
| C10 · banco validado contra el corpus | 0 referencias |

El informe (`informes/`) es el entregable: métricas, **huecos detectados**, detalle por
pregunta con cita y enlace, y candidatas no cargadas.

## 8b. Grafo de relaciones

```bash
python -m leyclara grafo        # exporta informes/grafo-normas.dot
# visual: python -m leyclara servir → http://127.0.0.1:8788/grafo
```

Aristas, todas de datos oficiales: **modifica** y **deroga** (del `/analisis` del BOE),
**se dicta de conformidad**, y **menciona** (una norma nombra a otra del corpus en su
texto. Las aristas hacia normas no cargadas salen discontinuas: son el mapa de lo que
falta.

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
│   ├── recuperar.py         BM25 (FTS5) + vectorial con fusión RRF
│   ├── vectorial.py         embeddings (qwen3-embedding) + índice coseno en numpy
│   ├── verificar.py         GATE (3 asserts)
│   ├── grafo.py             relaciones entre normas (DOT + JSON para la web)
│   ├── existencias.py       catálogo de las 12.437 normas del BOE (cobertura)
│   ├── responder.py         composición extractiva / modo LLM
│   ├── informe.py           harness + informe markdown
│   └── cli.py               init · ingesta · estado · vectorial · servir · grafo · pregunta · banco · evaluar
├── HARNESS.md               qué debe cumplir el sistema y qué respuesta buscamos
├── web/index.html           chat (Aurora)
├── web/grafo.html           grafo de relaciones (canvas)
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

1. **Los umbrales están calibrados sobre 27 preguntas.** Sirven como punto de partida, no
   como verdad: cada rama nueva que se añade ha destapado un fallo que el banco anterior
   no veía. Un banco pequeño se aprueba solo.
2. **Sin cómputo de plazos**. Detecta y señala; no calcula.
3. **Cobertura = lo que hay en `config.json`**. "No consta" puede significar "no está cargada".
4. **El gate valida citas, no razonamientos.** Un enlace entre normas puede ser literalmente
   correcto y jurídicamente discutible. El sistema lo hace verificable, no lo hace cierto.
5. **Desfase de consolidación**: hasta 1-3 días hábiles desde la publicación de una modificación.
6. **El modo `llm` cuesta ~11.000 tokens por consulta** y depende de un modelo de razonamiento
   (los modelos "flash" sin razonamiento devolvieron vacío en las pruebas).
7. **Queda 1 falso positivo conocido** (C6 ❌): un dato que existe en el corpus pero
   pertenece a otro sujeto. Es el límite del filtro léxico de tipo de dato; se cierra con
   verificación semántica del par pregunta-cita (`HARNESS.md` §7).
8. **Sólo la última versión consolidada.** No se puede preguntar «qué decía en 1995»
   aunque el XML del BOE trae todas las `<version>`: no se guardan.

---

## 12. Aviso

LeyClara **no presta asesoramiento jurídico**. Los textos son consolidados del BOE de
carácter meramente informativo. Lea `AVISO-LEGAL.md` antes de usar esto con clientes.

> Basado en datos de la Agencia Estatal Boletín Oficial del Estado — <https://www.boe.es>
