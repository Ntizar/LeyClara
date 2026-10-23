# LeyClara — micro informe: qué hemos aprendido y dónde está el techo

**Fecha:** 2026-10-23 · **Estado:** 26 normas · 11.684 bloques · 11.684 vectores
**Medición:** banco de 27 preguntas (22 con respuesta + 5 sin) → **22/22 (recall 1,000) · 0 falsos negativos · 1 falso positivo · abstención 4/5**

Este documento no describe lo construido (eso está en `README.md`): describe **lo que el
proyecto nos ha enseñado a golpes** y **qué le falta para ser una herramienta top** de
verdad, no una demo que impresiona.

---

## 1. Siete lecciones que costaron una medición cada una

### 1. El BOE regala la unidad citable; el trabajo es no romperla
La API de legislación consolidada devuelve `<bloque id="a245" tipo="precepto">`: el
artículo ya viene troceado. No hay que inventar chunking ni solapamientos. La consecuencia
de diseño es fuerte: **la unidad del RAG es el precepto, no el fragmento de 800 tokens**.
Trocear por caracteres habría hecho imposible citar «art. 245 LEC» — y sin eso no hay
herramienta jurídica, hay un buscador.

### 2. El banco de evaluación miente, y miente siempre en la misma dirección
Tres veces apuntó a bloques que no eran la respuesta:
- `a1902` en el Código Civil, que usa `art1902` → la pregunta no podía acertar nunca.
- Una pregunta del concurso donde valía el art. 2 **o** el 3 → falso negativo inventado.
- El art. 1 del RD 244/2019 «Objeto», cuando las modalidades están en el **art. 4
  «Clasificación de modalidades de autoconsumo»**.

Las tres veces el fallo se habría atribuido al motor. **Un banco sin validar contra el
corpus no mide el sistema: mide la memoria de quien lo escribió.** De ahí C10.

### 3. Ampliar el corpus empeora la métrica antes de mejorarla
De 11 a 26 normas el recall cayó de **1,000 a 0,909** — y no porque el motor empeorara:
las 10 preguntas nuevas eran más difíciles y de ramas distintas. La conclusión incómoda:
**un banco que sólo crece en aciertos no mide nada**. Si la métrica no puede bajar, no es
una métrica.

### 4. El 19 % de lo que indexábamos no era derecho
De 11.684 bloques, **2.184 no son preceptos**: preámbulos, encabezados de capítulo
(«CAPÍTULO III»), firmas y notas iniciales. El top-3 de «autoconsumo» era el **preámbulo
del RD 244/2019** y un título de capítulo. Filtrar por `tipo = 'precepto'` es una línea de
SQL y valió **+0,046 de recall**. Lo más barato del proyecto y lo que más mejoró.

### 5. Una cita literal no es una respuesta correcta
«¿Importe de la tasa del DNI?» devolvía el **art. 648 de la LEC (subasta electrónica)**
con cita textual íntegra, verificada por el gate, e insignia verde. Todo el mecanismo
funcionó y el resultado era basura: la palabra «tasa» casaba, el dato no estaba.

**Verificar el texto no verifica la pertinencia.** Son dos problemas distintos y el
segundo es el caro. De ahí C11: si preguntas un importe, el precepto debe contener euros;
si preguntas un plazo, una duración. Es tosco, pero cierra la clase de fallo entera.

### 6. La peor salida no es «no lo sé»: es el verde vacío
Dos preguntas negativas salían `VERIFICADO` con **cero citas**: el gate lo había rechazado
todo y el veredicto sólo miraba si hubo rechazos. Una insignia verde sin nada debajo
afirma sin respaldo, que es exactamente lo que el proyecto existe para impedir. C12.

### 7. «0 fallos» no existe; existe «0 afirmaciones sin respaldo»
Con 22/22 el sistema **sigue teniendo un falso positivo**. Perseguir el 100 % de acierto
es perseguir una quimera; lo alcanzable —y lo que un abogado necesita— es que **cada
afirmación venga con el texto y el enlace para comprobarla** y que lo que no conste se
diga. Esa es la promesa defendible; la otra no.

---

## 2. Límites para ser una herramienta top

### 2.1 Bloqueantes (sin esto no se le da a un despacho)

| Límite | Dato real | Por qué es bloqueante |
|---|---|---|
| **Cobertura** | 26 de **12.437** normas consolidadas = **0,21 %** | El 82,4 % de las relaciones de nuestras propias normas (986 de 1.197) apuntan a leyes que **no tenemos**. «No consta» hoy significa casi siempre «no la hemos cargado» |
| **Sin versiones históricas** | Sólo la última consolidada | «¿Qué decía en 1995?», «¿qué régimen se aplicaba al hecho?» es *la* pregunta del contencioso. El XML del BOE trae todas las `<version>`: no se guardan |
| **Un falso positivo de pertinencia** | «plazo de garantía comercial» → art. 127 bis («repuestos: diez años») | El dato existe en el corpus **pero es de otro sujeto**. Cerrarlo exige verificar el par pregunta‑cita, no otra regla léxica |
| **Sin cómputo de plazos** | Detecta «veinte días», no calcula | Un plazo mal contado pierde el caso. Se señala y se deriva al precepto: honesto, pero incompleto |
| **Sólo castellano** | El BOE publica también catalán, gallego y euskera | Un despacho en Barcelona o Vigo lo necesita el día uno |

### 2.2 De producto (lo que separa «mi herramienta» de «una herramienta»)

| Límite | Realidad hoy |
|---|---|
| **No ingiere tus documentos** | ISLA lee tu expediente (PDF, escaneado, audio). Nosotros sólo legislación pública: falta el 80 % del trabajo real del abogado |
| **Mono‑usuario y local** | Sin cuentas, sin permisos, sin historial compartido, sin auditoría por usuario |
| **Sin cifrado en reposo** | El corpus es público, pero en cuanto entren expedientes esto es obligatorio (AES + llavero/DPAPI) |
| **Sin API ni integración** | No habla con el gestor documental, ni con LexNET, ni con el BOE en tiempo real |
| **UI de una sola pregunta** | No hay conversación con memoria, ni comparación de supuestos, ni exportación a Word/PDF |
| **Actualización manual** | Si el BOE modifica una ley, el corpus no se entera hasta que alguien relanza la ingesta. Un «vigente» que no lo está es un fallo grave |

### 2.3 De confianza (lo que ningún test arregla)

- **Responsabilidad**: el aviso legal dice que no es asesoramiento. Con clientes reales
  eso necesita seguro y un contrato, no un `README`.
- **Desfase de consolidación**: hasta 1‑3 días hábiles. Un plazo que empieza a correr
  mañana puede estar afectado por una norma publicada hoy.
- **El juez no lee tu cita**: el sistema hace la afirmación *verificable*, no *correcta*.
  El encaje jurídico sigue siendo del abogado.

---

## 3. Dónde sí somos mejores que ISLA (y dónde no)

ISLA (Nesilabs) resuelve otro problema y lo resuelve bien: **confidencialidad por
construcción** en un portátil M1, air‑gap, cifrado, licencia atada al hardware, e ingesta
multimodal de expedientes. Su techo es el modelo de 8B local y una biblioteca congelada en
el momento del empaquetado.

| | ISLA | LeyClara |
|---|---|---|
| Aislamiento | **air‑gap real, cifrado, 2FA** | no (corpus público, sin expedientes) |
| Ingesta de tu expediente | **PDF/OCR/visión/audio** | no |
| Escala del corpus | ~30 códigos, 22.000 arts. congelados | 26 normas hoy, **pero actualizables desde el BOE** |
| Verificación | citas a fichero/página/línea | **gate determinista + cita literal por precepto + enlace oficial** |
| Cuando no sabe | no consta | **abstención informada + norma candidata del catálogo** |
| Plataforma | sólo Mac M1 | Windows/Linux/navegador |
| Precio | licencia de pago | libre |

Nuestra ventaja no es «todo el BOE en tu portátil» —eso lo hace él mejor— sino **que cada
frase se pueda abrir en el BOE y comprobar en un clic**, y que el sistema **diga lo que no
sabe** con nombre y apellidos de la ley que falta.

---

## 4. Qué haría falta para ser top (por orden de impacto/coste)

1. **Cobertura por ramas hasta ~300 normas** (todo lo que un despacho toca en un año):
   coste de ingesta ≈ 0,3 s/norma + embeddings; impacto: mata la mitad de los «no consta».
   *Empezar por las 4 normas ya indexadas sin pregunta en el banco.*
2. **Versiones históricas**: guardar todas las `<version>` del XML. Convierte «la ley hoy»
   en «la ley aplicable al hecho». Es la diferencia entre consulta y dictamen.
3. **Verificación de pertinencia** (el 1 FP): pregunta de control al LLM sólo sobre la
   cita ya verificada («¿este texto responde a *plazo de garantía comercial*?»). Coste:
   un token por cita; cierra C6.
4. **Ingesta del expediente del usuario** con cifrado en reposo. Sin esto se queda en
   herramienta de consulta, no de trabajo.
5. **Plazos con calendario procesal** (días hábiles, agosto inhábil, festivos por
   territorio). Alto riesgo, alto valor: hacerlo mal es peor que no hacerlo.
6. **Actualización automática** contra el BOE con diff de versiones y aviso de
   modificación — el «vigente» deja de ser una promesa y pasa a ser un hecho fechado.

---

## 5. La frase que resume el proyecto

> No hemos construido un asistente que responde sobre derecho.
> Hemos construido uno que **se niega a afirmar lo que no puede enseñar**.

Y el harness —22/22, 0 falsos negativos, 1 falso positivo declarado— es lo que permite
decir esa frase sin que sea marketing.

> Basado en datos de la Agencia Estatal Boletín Oficial del Estado — https://www.boe.es
> Los textos consolidados son de carácter meramente informativo. No es asesoramiento jurídico.
