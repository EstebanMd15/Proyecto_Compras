# Limpieza del Reporte de Dispensación

Guía de uso. Actualizada tras el cierre de mayo 2026.

---

## 1. El problema

El reporte se exporta como texto delimitado por `|`. Ese formato tiene dos
fallas de origen que corrompen el archivo:

**Falla 1 — Saltos de línea sin entrecomillar.**
Cuando alguien escribe un Enter dentro de un campo de texto, el exportador lo
escribe tal cual. El registro queda partido en dos líneas y cualquier programa
lo lee como dos filas distintas, ambas incompletas.

**Falla 2 — El delimitador dentro de los datos.**
El archivo separa columnas con `|`, pero los campos de texto permiten que la
gente escriba `|`. Cuando alguien anota dos teléfonos como
`3136600928 | 3206683340`, esa fila gana columnas de más y todo lo que sigue se
desplaza a la derecha.

Ninguna de las dos es un error de captura del personal. Son fallas del formato
de exportación.

### Magnitud medida

| | Enero 2026 | Mayo 2026 |
|---|---|---|
| Registros reales | 144.080 | 150.848 |
| Registros partidos por salto de línea | 233 | — |
| Registros con `\|` dentro de un campo | 24 | 34 |
| Filas correctas | 99,8% | 99,98% |

El daño es pequeño en volumen pero **inutiliza el archivo completo**: cualquier
herramienta que lo abra falla o, peor, lo abre con las columnas desalineadas
**sin avisar**.

> Ese es el punto central. El reporte llevaba meses saliendo corrupto y nadie lo
> notaba, porque Excel muestra las filas dañadas corridas y sin ningún error. El
> valor de este proceso no es que ahora se limpia: es que ahora **se sabe cuándo
> está mal**.

---

## 2. Qué garantiza

**No se pierde ningún registro.** Cada línea del original termina en el archivo
limpio o en cuarentena. Nunca se descarta nada.

**No se inventa nada.** Cuando una fila admite varias lecturas, el proceso no
elige solo: las presenta para que una persona decida.

**Todo es trazable.** `auditoria.csv` registra de qué línea vino cada fila y qué
reparación se le aplicó. `saneamiento.csv` registra cada valor modificado, antes
y después.

**Falla antes de entregar.** Los conteos se verifican *antes* de escribir la
salida. Si no cuadran, no se escribe nada.

**El original nunca se toca.** Todos los scripts son de solo lectura sobre el
archivo fuente.

---

## 3. Los scripts

Requisitos: Python 3.9+. Sin librerías externas (solo `openpyxl` si se quiere
salida `.xlsx`).

### En uso

| Script | Para qué |
|---|---|
| `diagnostico_reporte.py` | Caracteriza el daño del mes. No modifica nada |
| `limpiar_reporte.py` | Repara lo que se puede con certeza |
| `decidir.py` | Resuelve los casos dudosos con asistencia |
| `finalizar_v2.py` | Ordena, sanea y entrega el archivo final |
| `verificar_salida.py` | Diagnóstico, solo si Excel muestra algo raro |

### Obsoletos — no usar

| Script | Reemplazado por | Por qué |
|---|---|---|
| `limpiar_dispensacion.py` | `limpiar_reporte.py` | Traía el ancho y la regla de enero quemados |
| `resolver_cuarentena.py` | `decidir.py` | Obligaba a llenar `decisiones.csv` a mano |
| `finalizar.py` | `finalizar_v2.py` | Comparaba contra el conteo de enero; escribía antes de verificar |
| `verificar_v2.py`, `inspeccion_excedidas.py` | — | Fueron para investigar enero. Ya cumplieron |

---

## 4. Cómo usarlo

### Paso 1 — Diagnosticar

```bash
python diagnostico_reporte.py Datos/Reporte_Junio.csv
```

**Siempre primero.** No modifica nada. Dice cuántas filas partidas, cuántas
corridas, qué encoding y qué separador trae el mes. El daño cambia de un mes a
otro.

### Paso 2 — Limpiar

```bash
python limpiar_reporte.py Datos/Reporte_Junio.csv --salida Salida_Junio
```

Detecta solo el ancho, el encoding y el separador. Produce:

| Archivo | Contenido |
|---|---|
| `limpio.csv` | Los registros reparados con certeza |
| `cuarentena.csv` | Los que necesitan decisión humana |
| `auditoria.csv` | Qué se le hizo a cada fila |
| `preambulo.txt` | El membrete del reporte |
| `contrato.json` | El conteo esperado, para los pasos siguientes |

Si dice `PERDIDA DE DATOS`, **no seguir**. Volver al paso 1 y revisar.

### Paso 3 — Decidir

```bash
python decidir.py --salida Salida_Junio
```

Agrupa las filas duplicadas (las de un mismo documento son la misma fila
repetida), descarta las lecturas imposibles y propone la mejor. Se aprieta Enter
para aceptar o una letra para cambiar.

**Criterio para elegir:** leer las columnas y preguntarse si cada valor tiene
sentido según el nombre de su columna. Si un nombre de persona queda en el
teléfono o un parentesco en la cédula, esa opción está mal. La correcta es la
que **no reubica ningún dato real**.

> `--auto` acepta todas las recomendaciones sin preguntar. **No usarlo.** La
> recomendación es una heurística y ya se equivocó en producción: en mayo eligió
> mal en L92314 y L92315, dejando `'MINA MESSU ELSA MARY|Paciente|'` dentro de
> la columna *Teléfono Quien Recibe*.

### Paso 4 — Finalizar

```bash
python finalizar_v2.py --salida Salida_Junio
```

Restaura el orden original de las filas y reemplaza los `|` que quedaron dentro
de campos por ` / `. Ese paso es indispensable: mientras un campo contenga el
delimitador, Excel puede leer esa fila corrida aunque el archivo esté bien.

Resultado: **`reporte_limpio.csv`**.

Con `--xlsx` genera además el Excel directo, que evita el problema de
importación por completo (tarda varios minutos).

### Paso 5 — Control de calidad

```bash
notepad Salida_Junio\saneamiento.csv
```

**Este paso no es opcional.** Son 30-40 líneas y se leen en dos minutos. Cada
valor que se vea raro para su columna es una decisión mal tomada.

Es el único control que atrapa los errores que ningún conteo detecta: el archivo
puede cuadrar perfecto y aun así tener un dato en la columna equivocada.

---

## 5. Cuando algo falla

| Síntoma | Significado | Qué hacer |
|---|---|---|
| `PERDIDA DE DATOS` | Hay líneas sin clasificar | No usar la salida. Volver al paso 1 |
| Muchas filas en cuarentena | El patrón de daño cambió | Correr el diagnóstico y revisar |
| Excel muestra columnas corridas | Casi siempre es la importación | `python verificar_salida.py --archivo Salida_Junio/reporte_limpio.csv`. Si dice OK, el archivo está bien y el problema es cómo Excel lo abre |
| `SIN_CANDIDATOS` | Daño no previsto | Revisar la `linea_cruda` a mano |
| Un valor raro en `saneamiento.csv` | Decisión mal tomada | Corregir el `k` en `decisiones.csv` y repetir el paso 4 |

---

## 6. Límites conocidos

**Cuando el `|` cae junto a un campo vacío, es imposible saber de qué lado
estaba.** Esa información la destruye el exportador; ningún programa la puede
recuperar. Por eso esas filas requieren decisión humana.

**La recomendación de `decidir.py` se equivoca.** Es una heurística basada en el
vocabulario de las columnas. Cuando los campos vecinos están vacíos no tiene de
dónde agarrarse. Por eso existe el paso 5.

**Los dominios de `verificar_salida.py` son de enero.** Si aparece una sucursal,
un departamento o un tipo de contrato nuevos, los marcará como error. Hay que
actualizarlos antes de creerle.

**Cada mes puede traer un daño distinto.** En mayo aparecieron columnas de
inyección que enero no tenía (`FacSec`, `Observación Exoneración`, `Parentesco`).
El proceso lo detecta y lo manda a cuarentena en vez de romperse en silencio,
pero no lo repara solo si es un patrón nuevo.

---

## 7. Recomendación

Este proceso resuelve el síntoma. **La causa está en el sistema que exporta.**

Dos cambios en el exportador eliminarían el problema por completo:

1. **Entrecomillar los campos de texto** (norma RFC 4180). Resuelve las dos
   fallas de una vez.
2. **O exportar directamente a `.xlsx`**, que no usa delimitadores y no puede
   tener este problema.

Alternativa mínima: **bloquear el carácter `|` en los campos de captura**
elimina la Falla 2 sin tocar el formato.

Mientras eso no ocurra, este proceso hay que correrlo todos los meses **con
revisión manual**, y cada mes puede traer un caso nuevo. El costo de arreglar el
exportador se paga una sola vez; el de mantener esto se paga indefinidamente.
