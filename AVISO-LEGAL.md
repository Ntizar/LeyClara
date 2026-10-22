# Aviso legal y condiciones de reutilización

LeyClara es **una herramienta de consulta**, no un despacho de abogados.

## 1. No es asesoramiento jurídico

- LeyClara **no presta asesoramiento jurídico** ni sustituye a un profesional.
- El uso de la herramienta **no crea relación abogado–cliente** de ningún tipo.
- Toda decisión con efectos jurídicos (plazos, recursos, importes, estrategia procesal)
  debe ser confirmada por un profesional habilitado y **contra el texto oficial**.

## 2. Condiciones de reutilización del BOE

Los textos se obtienen de la API de datos abiertos de la Agencia Estatal Boletín
Oficial del Estado, sujeta a las condiciones de reutilización aprobadas por
**Resolución de 27 de junio de 2024** (eficaces desde el 28/06/2024), disponibles en
<https://www.boe.es/informacion/aviso_legal/index.php>.

En la medida en que LeyClara reutiliza esos documentos, cumple y hace cumplir:

| Obligación | Cómo se cumple en este proyecto |
|---|---|
| **Citar la fuente** | Todo informe lleva: *"Basado en datos de la Agencia Estatal Boletín Oficial del Estado"* + enlace a `boe.es` |
| **No desnaturalizar el sentido** | Los textos se muestran **literales**; el gate rechaza cualquier cita que no sea textual |
| **No sugerir carácter oficial** | Cada texto consolidado se presenta como **"texto consolidado de carácter meramente informativo"** |
| **No insinuar respaldo del BOE** | No se usa marca, logotipo ni denominación del BOE; se declara expresamente que no patrocina ni apoya esta herramienta |
| **Identificar modificaciones** | Las citas son textuales; cuando un precepto ha sido modificado se indica el número de versiones consolidadas y su fecha de vigencia |
| **Conservar metadatos** | Se almacenan y muestran `fecha_actualizacion`, `fecha_vigencia` y el identificador `BOE-A-...` |

Autorización de reutilización: la licencia permite **uso comercial y no comercial**,
así como la creación de obras derivadas y productos de valor añadido.

## 3. Qué significa "texto consolidado"

Según el propio BOE, la consolidación integra en un solo texto las modificaciones,
correcciones y derogaciones **de carácter expreso**. Es decir:

- ⚠️ **No es el texto oficial.** Únicamente tienen carácter oficial y auténtico los
  textos publicados en la edición electrónica del BOE.
- ⚠️ Puede haber un desfase de **1 a 3 días hábiles** entre la publicación de una
  modificación y su incorporación al consolidado.
- ⚠️ Las derogaciones **tácitas** o las declaraciones de inconstitucionalidad pueden no
  reflejarse como tales.

## 4. Límites del sistema (declarados, no disimulados)

- **Cobertura**: sólo las normas cargadas en `config.json`. Si una ley no está, el
  sistema debe decir "no consta", no improvisar.
- **Recuperación léxica**: la búsqueda es BM25 sobre el texto. Una pregunta formulada con
  vocabulario muy distinto al del precepto puede no encontrarlo (falso negativo).
- **Sin cálculo de plazos**: LeyClara detecta y señala los plazos, pero **no computa**
  días hábiles, festivos, suspensiones ni el *dies a quo*. Eso exige el calendario
  procesal aplicable y no está implementado.
- **Sin capa vectorial todavía**: pendiente de añadir embeddings + fusión RRF.

## 5. Datos personales

El corpus es legislación pública: no contiene datos personales. Si en el futuro se
añaden documentos de usuario (modo despacho), deberán tratarse conforme al RGPD y a la
LOPDGDD, y por defecto **en local**, sin salida a red.
