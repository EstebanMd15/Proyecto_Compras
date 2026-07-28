# Limpieza y carga de reportes MENNAR

Guía completa. Cubre los dos reportes: Dispensación (texto delimitado) y
Remisiones (Excel). Actualizada tras cargar marzo e integrar remisiones.

---

## 0. Ordenar la carpeta primero

En la carpeta hay scripts de dos tipos: los que se usan cada mes y los que
fueron para investigar o quedaron reemplazados. **Borra los que sobran**, para
que nadie del equipo corra el que no es.

### Se usan — NO borrar

| Script | Cuándo |
|---|---|
| `diagnostico_reporte.py` | Solo reportes de texto. Diagnóstico inicial |
| `limpiar_reporte.py` | Solo reportes de texto. Repara |
| `decidir.py` | Solo reportes de texto. Resuelve dudas |
| `ver_pendientes.py` | Solo reportes de texto. Casos raros |
| `finalizar_v2.py` | Solo reportes de texto. Entrega final |
| `leer_excel.py` | Solo reportes en Excel (Remisiones) |
| `exportar.py` | Opcional. Formato para abrir en Excel |
| `generar_sql.py` | Ambos reportes. Genera el SQL de carga |

### Sobran — borrar

```
finalizar.py              (lo reemplazó finalizar_v2.py)
limpiar_dispensacion.py   (lo reemplazó limpiar_reporte.py)
resolver_cuarentena.py    (lo reemplazó decidir.py)
preflight.py              (quedó incorporado dentro de generar_sql.py)
verificar_hipotesis.py    (fue para investigar enero)
verificar_v2.py           (fue para investigar enero)
inspeccion_excedidas.py   (fue para investigar enero)
verificar_salida.py       (sus dominios eran de enero; ya no aplica)
```

---

## 1. Qué reporte tienes

El camino depende del formato, y el formato no es la extensión sino los bytes.

- **Reporte de texto** (Dispensación, `.csv` o `.txt` delimitado por `|`):
  puede tener el daño de saltos de línea y columnas corridas. Va por la
  **Ruta A**.
- **Reporte en Excel** (Remisiones, `.xls` / `.xlsx`): no tiene delimitadores,
  así que ese daño es imposible. Va por la **Ruta B**.

Si dudas, `leer_excel.py` detecta el formato real y te avisa si un `.xls`
resulta ser texto disfrazado.

---

## 2. RUTA A — Reporte de texto (Dispensación)

### A1. Diagnosticar
```bash
python diagnostico_reporte.py Datos\Reporte.csv
```
No modifica nada. Dice el patrón de daño del mes. **Siempre primero.**

### A2. Limpiar
```bash
python limpiar_reporte.py Datos\Reporte.csv --salida Salida_Mes
```
Detecta encoding, separador y ancho del propio archivo. Produce `limpio.csv`,
`cuarentena.csv`, `auditoria.csv`, `preambulo.txt`, `contrato.json`.
Si dice `PERDIDA DE DATOS`, parar y volver a A1.

### A3. Decidir
```bash
python decidir.py --salida Salida_Mes
```
Muestra los casos dudosos agrupados, con la lectura recomendada. Enter acepta,
una letra cambia. **No uses `--auto` la primera vez:** la recomendación se ha
equivocado (mayo, L92314).

**Criterio:** después de fusionar, cada valor debe tener sentido según el nombre
de su columna. Si un nombre queda en el teléfono, esa opción está mal.

### A4. Pendientes (solo si quedaron)
```bash
python ver_pendientes.py --salida Salida_Mes
```
Resuelve filas con el `|` en columnas separadas, que A3 no cubre. Si te dice que
una fila tiene el pipe en dos columnas, esa queda en cuarentena: no se pierde.

### A5. Finalizar
```bash
python finalizar_v2.py --salida Salida_Mes
```
Ordena las filas, reemplaza los `|` internos por ` / ` y verifica el conteo
**antes** de escribir. Resultado: `reporte_limpio.csv`.

### A6. Control de calidad — no opcional
```bash
notepad Salida_Mes\saneamiento.csv
```
Son 30-40 líneas. Cada valor raro para su columna es una decisión mal tomada.
Es el único control que atrapa lo que los conteos no ven: un dato bien contado
pero en la columna equivocada.

---

## 3. RUTA B — Reporte en Excel (Remisiones)

Un Excel no tiene delimitadores, así que **no hay nada que limpiar**: solo hay
que leerlo sin que pandas dañe los datos.

### B1. Leer el Excel
```bash
pip install pandas openpyxl xlrd     # una sola vez
python leer_excel.py Datos\Remision.xls --salida Salida_Remision
```

Lo primero que imprime es el formato real:
- `Excel 97-2003` o `Excel moderno` → sigue.
- `texto plano disfrazado` → NO es Excel. Va por la Ruta A.
- `HTML disfrazado` → intenta leerlo; avisa si algo se ve raro.

Lee con `dtype=str`: pandas no convierte fechas ni borra ceros a la izquierda.
Produce `reporte_limpio.csv`, el mismo formato que la Ruta A.

No hace falta A3-A5: no hay cuarentena porque no hay daño de delimitación.

---

## 4. Exportar para Excel (opcional, ambas rutas)

Si vas a abrir el CSV en Excel en vez de cargarlo a MySQL:
```bash
python exportar.py --salida Salida_Mes --formato excel
```
Genera `reporte_excel.csv` con la línea `sep=|`, que Excel abre en columnas con
doble clic. Para pandas después, ese archivo necesita `skiprows=1`.

> No cargues `reporte_excel.csv` a MySQL: su primera línea desplaza todo.
> Para MySQL siempre `reporte_limpio.csv`.

---

## 5. Cargar a MySQL (ambas rutas)

### 5.1. Generar el SQL
```bash
# Dispensación
python generar_sql.py --salida Salida_Mes

# Remisiones (empresas, no personas; y se fija el periodo a mano)
python generar_sql.py --salida Salida_Remision --tabla remisiones_raw ^
  --sin-pii --periodo 2026-07 --col-fecha "Fecha y hora Remisión"
```

El script detecta solo la columna de fecha y de documento. Puntos clave:
- **El periodo se deduce del dato**, no del nombre de la carpeta. Si pasas
  `--periodo` y no coincide con los datos, aborta (evita etiquetar un mes con
  otro).
- Descarta las columnas de fecha repartidas entre años (vencimientos).
- Si la fecha del reporte no sirve (como en Remisiones), fija `--periodo` a mano
  y pasa `--col-fecha` para que no forcejee.
- `--sin-pii` para reportes de empresas. `--pii-extra "palabra"` si detecta de
  menos las columnas personales.

Revisa lo que imprime **antes** de cargar: que el periodo sea el mes correcto y
que la columna documento tenga sentido.

Produce `esquema.sql` (una vez) y `cargar_AAAA-MM.sql` (cada mes).

### 5.2. IMPORTANTE si ya cargaste otro reporte

`esquema.sql` crea la vista `v_dispensacion`, la tabla `columnas_mapeo` y el
usuario `analista`. Si cargas un **segundo** reporte, esos nombres chocan y
pisan lo del primero. Antes de ejecutar el `esquema.sql` del segundo reporte,
en Workbench (`Ctrl+H`, Replace All):

| Buscar | Reemplazar |
|---|---|
| `v_dispensacion` | `v_remisiones` |
| `columnas_mapeo` | `columnas_mapeo_remisiones` |

Y verifica con `Ctrl+F` que no quede ninguno antes de ejecutar.

### 5.3. Ejecutar en Workbench

Prerrequisitos, una sola vez:
- `SET GLOBAL local_infile = 1;` (o `local_infile=1` en `my.ini`)
- `secure-file-priv` apuntando a la carpeta de los CSV, en `my.ini`. **Si hay
  dos líneas `secure-file-priv`, MySQL usa la última:** deja solo una.
- **Edit → Preferences → SQL Editor → desmarca "Safe Updates"**, luego
  Query → Reconnect to Server. Sin esto, el `DELETE` del carga falla con 1175.

Orden (cada script: `File → Open SQL Script`, luego **`Ctrl+Shift+Enter`** =
rayo doble = ejecutar todo; el rayo sencillo corre una sola sentencia):

```
1. esquema.sql            -> una sola vez por reporte
2. cargar_AAAA-MM.sql     -> cada mes
```

El SQL de carga trae preflight incorporado: aborta si el modo estricto está
apagado o si el reporte cambió de estructura. Al final imprime `filas_cargadas`
y verifica los dominios.

### 5.4. Verificar la carga

El conteo no basta: una fila corrida cuenta igual que una buena.
```sql
USE mennar;
SELECT contrato, COUNT(*) FROM dispensacion_raw
 WHERE periodo='2026-03' GROUP BY contrato;
```
Solo debe salir `CAPITA` y `EVENTO`. Cualquier otra cosa = corrimiento.
(En Remisiones, usa una columna de dominio conocido de ese reporte.)

Y en el panel de la carga, mira `Records: N  Warnings: 0`. Si hay warnings, algo
se recortó — investigar antes de dar el mes por bueno.

---

## 6. Compartir con el equipo

`esquema.sql` crea el usuario `analista` (cámbiale la clave) con acceso **solo a
la vista**, no a la tabla. Prueba que sea así:
```sql
-- debe funcionar:
SELECT COUNT(*) FROM v_dispensacion;   -- como analista
-- debe dar error de permisos:
SELECT * FROM dispensacion_raw;        -- como analista
```
Si la segunda funciona, los GRANT quedaron mal.

**Dónde debe vivir la base:** Dispensación trae cédulas, nombres, teléfonos y
diagnósticos CIE-10 — dato sensible bajo la Ley 1581 de 2012, y el responsable
es MENNAR, no tú. No la montes en tu portátil ni en la nube sin autorización
escrita. Pide un MySQL en infraestructura de la empresa. Remisiones es B2B
(empresas), así que no tiene esa restricción.

---

## 7. Resumen de un mes típico

**Dispensación:**
```bash
python diagnostico_reporte.py Datos\Disp.csv
python limpiar_reporte.py     Datos\Disp.csv --salida Salida_Disp
python decidir.py             --salida Salida_Disp
python ver_pendientes.py      --salida Salida_Disp     # si hay pendientes
python finalizar_v2.py        --salida Salida_Disp
notepad Salida_Disp\saneamiento.csv                     # revisar
python generar_sql.py         --salida Salida_Disp
#   -> Workbench: esquema.sql (1ª vez), cargar_AAAA-MM.sql
```

**Remisiones:**
```bash
python leer_excel.py   Datos\Remision.xls --salida Salida_Rem
python generar_sql.py  --salida Salida_Rem --tabla remisiones_raw --sin-pii ^
   --periodo AAAA-MM --col-fecha "Fecha y hora Remisión"
#   -> Workbench: renombrar vistas, esquema.sql (1ª vez), cargar_AAAA-MM.sql
```

---

## 8. Recomendación de fondo

El problema de Dispensación nace en el exportador: escribe texto delimitado por
`|` sin escapar los `|` que la gente teclea, y mete saltos de línea sin
entrecomillar. Este pipeline lo resuelve cada mes, pero cada mes puede traer un
caso nuevo que requiera revisión manual.

Dos cambios en el exportador lo eliminarían de raíz: entrecomillar los campos de
texto (RFC 4180), o exportar a `.xlsx` — que es justo por qué Remisiones no da
problemas. El costo de arreglar el exportador se paga una vez; el de mantener
este proceso, todos los meses.
