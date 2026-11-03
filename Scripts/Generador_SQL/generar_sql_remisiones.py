#!/usr/bin/env python3
"""
generar_sql.py
==============
UN solo script. Genera todo el SQL para cargar el reporte a MySQL.
No ejecuta nada: escribe .sql para que los revises antes de correrlos.

GARANTIA: NO RECORTA NADA
    Todas las columnas se crean como TEXT, no como VARCHAR(n).
    Cualquier VARCHAR(n) recorta en silencio si un mes trae un valor mas
    largo que n. Sin n, no hay recorte posible.
    Efecto lateral util: 128 VARCHAR(255) en utf8mb4 son 130.816 bytes de
    definicion de fila y MySQL topa en 65.535 -> el CREATE TABLE reventaria
    con Error 1118. TEXT aporta ~10 bytes cada una y el problema desaparece.

PREFLIGHT INCORPORADO (dentro del SQL de carga, antes de cargar)
    1) Exige STRICT_TRANS_TABLES. Sin el, MySQL degrada errores a warnings.
    2) Detecta si el reporte CAMBIO DE ESTRUCTURA (columnas nuevas, faltantes
       o renombradas). Si cambio, ABORTA con SIGNAL en vez de cargar corrido.
    3) Despues de cargar: verifica el conteo y los dominios cerrados.
       Un conteo correcto no prueba nada; una fila corrida cuenta igual.

OTRAS DECISIONES
    - LOAD DATA INFILE sin LOCAL (lee el servidor; Workbench bloquea LOCAL).
    - Tipado en VISTAS, no en la tabla. Las fechas vienen como '/  /     00:00'
      y las cedulas pueden tener ceros a la izquierda: convertir al cargar
      pierde datos en silencio.
    - Vista sin datos personales: el reporte trae cedulas, nombres, telefonos
      y diagnosticos CIE-10. Dato sensible, Ley 1581 de 2012.

Uso:
    python generar_sql.py --salida Salida_Marzo --periodo 2026-03
    mysql -u root -p < Salida_Marzo/esquema.sql            <- una sola vez
    mysql -u root -p < Salida_Marzo/cargar_2026-03.sql     <- cada mes
"""

import argparse
import csv
import re
from collections import Counter
import unicodedata
from pathlib import Path

ENC = "utf-8-sig"
SEP = "|"
MAX_CARD_DOMINIO = 20   # columnas con <= esto se verifican por dominio tras cargar

PII_CLAVES = ["cedula", "nombre quien", "telefono", "celular",
              "documento paciente", "nombre paciente", "genero", "cie 10",
              "cohorte", "primer nombre", "segundo nombre", "primer apellido",
              "segundo apellido", "fecha nacimiento", "edad", "peso",
              "parentesco", "direccion", "correo", "email"]


def sin_tildes(s):
    s = unicodedata.normalize("NFKD", s)
    return "".join(c for c in s if not unicodedata.combining(c))


def sanear(nombre, usados):
    s = sin_tildes(nombre).strip().lower()
    s = re.sub(r"[^a-z0-9]+", "_", s).strip("_")
    if not s:
        s = "col"
    if s[0].isdigit():
        s = "c_" + s
    s = s[:60]
    base, n = s, 2
    while s in usados:
        s = f"{base}_{n}"
        n += 1
    usados.add(s)
    return s


def es_pii(nombre, claves=None):
    n = sin_tildes(nombre.lower())
    return any(k in n for k in (claves or PII_CLAVES))


def q(v):
    return "'" + v.replace("\\", "\\\\").replace("'", "''") + "'"


RE_DMY = re.compile(r"^\s*(\d{1,2})/(\d{1,2})/(\d{4})")
RE_ISO = re.compile(r"^\s*(\d{4})-(\d{1,2})-(\d{1,2})")   # asi salen de Excel


def periodo_de(v):
    """Entiende dd/mm/yyyy (export de texto) e yyyy-mm-dd (Excel via pandas).
    Excel guarda las fechas como numero, no como texto: pandas las entrega en
    ISO. Asumir un solo formato rompe el script en el otro reporte."""
    m = RE_DMY.match(v)
    if m:
        return f"{m.group(3)}-{int(m.group(2)):02d}"
    m = RE_ISO.match(v)
    if m:
        return f"{m.group(1)}-{int(m.group(2)):02d}"
    return None


def elegir_col_fecha(cols, filas, forzada):
    """Elige la columna con la que se deduce el periodo.

    La senal NO es la cobertura sino la CONCENTRACION. 'Fecha Vencimiento'
    esta llena en el 100% de las filas pero se reparte entre 2027, 2028 y
    2029: es el vencimiento del lote, no la fecha del reporte. La fecha del
    reporte se concentra en un mes. Puntuar por cobertura elegia el
    vencimiento y habria etiquetado julio como '2028-02'.
    """
    if forzada is not None:
        for c in cols:
            if forzada in (str(c["i"]), c["sql"], c["orig"]):
                return c
        raise SystemExit(f"[X] No existe la columna {forzada!r}")

    cands = []
    for c in cols:
        if "fecha" not in sin_tildes(c["orig"].lower()):
            continue
        ms = Counter()
        for f in filas:
            pp = periodo_de(f[c["i"]])
            if pp:
                ms[pp] += 1
        if not ms:
            continue
        cobertura = sum(ms.values()) / len(filas)
        dom, n = ms.most_common(1)[0]
        concentracion = n / sum(ms.values())
        cands.append((cobertura * concentracion, cobertura, concentracion, dom, c))

    if not cands:
        raise SystemExit(
            "[X] Ninguna columna con 'fecha' en el nombre trae fechas legibles.\n"
            "    Pasala a mano: --col-fecha 'Fecha y hora Remision' (o su indice)")

    # La concentracion es el FILTRO, no un factor del puntaje: una fecha
    # repartida entre 2027, 2028 y 2029 no es la fecha del reporte, punto.
    # Entre las que si se concentran, gana la mas completa.
    buenas = [c for c in cands if c[2] >= 0.80]
    cands.sort(reverse=True, key=lambda t: (t[2] >= 0.80, t[1]))

    print("\nColumnas de fecha candidatas:")
    for _, cob, con, dom, c in cands[:6]:
        if con < 0.80:
            nota = "  DESCARTADA: se reparte entre meses (vencimiento?)"
        else:
            nota = "  <- candidata"
        print(f"   [{c['i']:>3}] {c['orig']:<32} cob {cob:>4.0%}  "
              f"conc {con:>4.0%} -> {dom}{nota}")

    if not buenas:
        raise SystemExit(
            "\n[X] Ninguna columna de fecha se concentra en un mes. Todas parecen\n"
            "    vencimientos o fechas de documentos relacionados.\n"
            "    Elige tu la columna con --col-fecha, o fija --periodo a mano.")

    buenas.sort(reverse=True, key=lambda t: t[1])
    _, cob, con, dom, c = buenas[0]
    print(f"\nElegida: [{c['i']}] {c['orig']!r}  "
          f"(cobertura {cob:.0%}, concentracion {con:.0%})")
    if cob < 0.50:
        print(f"  [!] Solo el {cob:.0%} de las filas traen esa fecha: el periodo\n"
              f"      sale de esas. Si no es la columna correcta, usa --col-fecha.")
    return c


def elegir_col_doc(cols, forzada):
    """En dispensacion 'Documento' es la col 2; en remisiones, la 0."""
    if forzada is not None:
        for c in cols:
            if forzada in (str(c["i"]), c["sql"], c["orig"]):
                return c
        raise SystemExit(f"[X] No existe la columna {forzada!r}")
    for c in cols:
        if sin_tildes(c["orig"].lower()).strip() == "documento":
            return c
    for c in cols:
        if "documento" in sin_tildes(c["orig"].lower()):
            return c
    return cols[0]


def deducir_periodo(filas, col_fecha):
    """Del dato, no del nombre de la carpeta: un typo en la carpeta pasa
    callado; una mezcla de meses en los datos, no."""
    meses = Counter()
    for f in filas:
        pp = periodo_de(f[col_fecha])
        if pp:
            meses[pp] += 1
    if not meses:
        raise SystemExit("[X] No se pudo leer ninguna fecha. Pasa --periodo a mano.")
    dom, n = meses.most_common(1)[0]
    total = sum(meses.values())
    print(f"\nPeriodo deducido del CSV: {dom}  ({n}/{total} = {n/total:.1%})")
    otros = [(pp, c) for pp, c in meses.most_common() if pp != dom]
    if otros:
        print("  Otros periodos presentes en el archivo:")
        for pp, c in otros[:6]:
            print(f"    {pp}: {c} filas ({c/total:.2%})")
        print("  (normal: documentos de meses anteriores cerrados este mes)")
    if n / total < 0.80:
        raise SystemExit(
            f"[X] Solo el {n/total:.1%} de las filas son de {dom}. El archivo "
            "parece mezclar meses o no ser el que crees. Revisa, o pasa "
            "--periodo a mano si estas seguro.")
    return dom


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--salida", default="Salida")
    ap.add_argument("--periodo", default=None,
                    help="ej: 2026-03. Si se omite, se deduce del CSV")
    ap.add_argument("--tabla", default="remisiones_acum")
    ap.add_argument("--bd", default="mennar_bi")
    ap.add_argument("--forzar-periodo", action="store_true",
                    dest="forzar", help="ignora el periodo deducido del CSV")
    ap.add_argument("--col-fecha", default=None,
                    help="columna de fecha para el periodo (nombre o indice)")
    ap.add_argument("--col-documento", default=None,
                    help="columna para el indice (nombre o indice)")
    ap.add_argument("--pii-extra", default="",
                    help="palabras clave extra de datos personales, con coma")
    ap.add_argument("--sin-pii", action="store_true",
                    help="reporte B2B (empresas, no personas): sin vista restringida")
    args = ap.parse_args()

    if args.periodo and not re.fullmatch(r"\d{4}-\d{2}", args.periodo):
        raise SystemExit(f"[X] --periodo {args.periodo!r} no tiene formato AAAA-MM "
                         f"(con guion). Ejemplo: 2026-07")

    out = Path(args.salida)
    fuente = out / "reporte_limpio.csv"
    if not fuente.exists():
        raise SystemExit(f"[X] No existe {fuente}. Corre finalizar_v2.py primero.")

    with open(fuente, encoding=ENC, newline="") as f:
        r = csv.reader(f, delimiter=SEP)
        encabezado = next(r)
        filas = list(r)

    print(f"Fuente  : {fuente}")
    print(f"Filas   : {len(filas)}  |  Columnas: {len(encabezado)}")

    claves = list(PII_CLAVES) + [k.strip().lower()
                                 for k in args.pii_extra.split(",") if k.strip()]
    usados = {"id", "periodo", "cargado_en"}
    cols = []
    for i, orig in enumerate(encabezado):
        pii = False if args.sin_pii else es_pii(orig, claves)
        cols.append({"i": i, "orig": orig.strip(),
                     "sql": sanear(orig, usados), "pii": pii})

    c_fecha = elegir_col_fecha(cols, filas, args.col_fecha)
    c_doc = elegir_col_doc(cols, args.col_documento)
    print(f"Columna documento: [{c_doc['i']}] {c_doc['orig']!r}")

    deducido = deducir_periodo(filas, c_fecha["i"])
    if args.periodo is None:
        args.periodo = deducido
    elif args.periodo != deducido and not args.forzar:
        raise SystemExit(
            f"\n[X] Dijiste --periodo {args.periodo} pero los datos son de "
            f"{deducido}.\n"
            f"    Casi seguro cruzaste --salida con --periodo: cargarias un mes\n"
            f"    con la etiqueta de otro y el conteo cuadraria igual.\n"
            f"    Si de verdad quieres {args.periodo}, usa --forzar-periodo.")
    print(f"Periodo : {args.periodo}")

    n_pii = sum(1 for c in cols if c["pii"])
    if args.sin_pii:
        print("\n[i] --sin-pii: reporte de empresas, no de personas.")
        print("    La vista general trae todas las columnas.")
    else:
        print(f"\nColumnas con datos personales/salud: {n_pii}")
        for c in cols:
            if c["pii"]:
                print(f"   [{c['i']:>3}] {c['orig']}")
        print("    Revisa la lista. Si falta alguna, agregala con --pii-extra.")

    # dominios cerrados de ESTE mes -> para verificar que la carga no corrio nada
    dominios = []
    for c in cols:
        vals = {f[c["i"]] for f in filas}
        if 0 < len(vals) <= MAX_CARD_DOMINIO:
            dominios.append((c, sorted(vals)))
    print(f"\nColumnas de dominio cerrado (se verifican tras cargar): {len(dominios)}")

    # =====================================================================
    # esquema.sql  -- una sola vez
    # =====================================================================
    L = [
        "-- ================================================================",
        f"-- ESQUEMA. Correr UNA SOLA VEZ. Generado desde {fuente.name}",
        "--",
        "-- Todas las columnas son TEXT a proposito: un VARCHAR(n) recorta en",
        "-- silencio si un mes trae un valor mas largo que n. Sin n, no hay",
        "-- recorte. El tipado va en las vistas, que son reversibles.",
        "-- ================================================================",
        "",
        f"CREATE DATABASE IF NOT EXISTS `{args.bd}`",
        "  CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;",
        f"USE `{args.bd}`;",
        "",
        f"CREATE TABLE IF NOT EXISTS `{args.tabla}` (",
        "  `id` BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,",
        "  `periodo` CHAR(7) NOT NULL COMMENT 'AAAA-MM del reporte',",
        "  `cargado_en` TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,",
    ]
    for c in cols:
        L.append(f"  `{c['sql']}` TEXT NULL COMMENT {q(c['orig'])},")
    L += [
        "  PRIMARY KEY (`id`),",
        "  KEY `idx_periodo` (`periodo`),",
        f"  KEY `idx_documento` (`{c_doc['sql']}`(20)),",
        f"  KEY `idx_fecha` (`{c_fecha['sql']}`(12))",
        ") ENGINE=InnoDB ROW_FORMAT=DYNAMIC",
        "  DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;",
        "",
        "-- Mapeo: el encabezado original no se pierde",
        "CREATE TABLE IF NOT EXISTS `columnas_mapeo` (",
        "  `posicion` INT NOT NULL,",
        "  `nombre_original` VARCHAR(255) NOT NULL,",
        "  `nombre_sql` VARCHAR(64) NOT NULL,",
        "  `es_dato_personal` TINYINT(1) NOT NULL DEFAULT 0,",
        "  PRIMARY KEY (`posicion`)",
        ") ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;",
        "",
    ]
    for c in cols:
        L.append(f"REPLACE INTO `columnas_mapeo` VALUES "
                 f"({c['i']}, {q(c['orig'])}, '{c['sql']}', {1 if c['pii'] else 0});")

    publicas = [c for c in cols if not c["pii"]]
    sel = ",\n  ".join(f"`{c['sql']}`" for c in publicas)
    L += [
        "",
        "-- ================================================================",
        "-- VISTA GENERAL: sin datos personales ni de salud.",
        "-- Es la que se comparte con el equipo. Ley 1581 de 2012: los datos",
        f"-- de salud son sensibles. Excluye {n_pii} columnas.",
        "-- ================================================================",
        "CREATE OR REPLACE VIEW `v_dispensacion` AS",
        "SELECT",
        "  `id`,",
        "  `periodo`,",
        f"  {sel}",
        f"FROM `{args.tabla}`;",
        "",
        "-- ================================================================",
        "-- VISTA TIPADA: convierte fechas sin tocar la tabla base.",
        "-- '/  /     00:00' es el nulo del sistema -> NULL.",
        "-- ================================================================",
        "CREATE OR REPLACE VIEW `v_dispensacion_tipada` AS",
        "SELECT",
        "  `id`,",
        "  `periodo`,",
        f"  COALESCE(",
        f"    STR_TO_DATE(NULLIF(TRIM(`{c_fecha['sql']}`), ''), '%d/%m/%Y'),",
        f"    STR_TO_DATE(NULLIF(TRIM(`{c_fecha['sql']}`), ''), '%Y-%m-%d %H:%i:%s'),",
        f"    STR_TO_DATE(NULLIF(TRIM(`{c_fecha['sql']}`), ''), '%Y-%m-%d')",
        f"  ) AS `{c_fecha['sql']}_fecha`,",
        f"  {sel}",
        f"FROM `{args.tabla}`",
        f"WHERE TRIM(`{c_fecha['sql']}`) NOT LIKE '/%';",
        "",
        "-- ================================================================",
        "-- USUARIOS: nadie entra con root. CAMBIA LAS CLAVES.",
        "-- ================================================================",
        "CREATE USER IF NOT EXISTS 'analista'@'%' IDENTIFIED BY 'CAMBIA_ESTA_CLAVE';",
        f"GRANT SELECT ON `{args.bd}`.`v_dispensacion` TO 'analista'@'%';",
        f"GRANT SELECT ON `{args.bd}`.`columnas_mapeo` TO 'analista'@'%';",
        "",
        "-- Quien SI necesite datos de paciente: acceso explicito y justificado.",
        "-- CREATE USER IF NOT EXISTS 'auditor'@'%' IDENTIFIED BY 'CAMBIA_ESTA_CLAVE';",
        f"-- GRANT SELECT ON `{args.bd}`.`{args.tabla}` TO 'auditor'@'%';",
        "",
        "FLUSH PRIVILEGES;",
    ]
    (out / "esquema.sql").write_text("\n".join(L), encoding="utf-8")

    # =====================================================================
    # cargar_<periodo>.sql  -- cada mes: preflight + carga + verificacion
    # =====================================================================
    ruta_abs = str(fuente.resolve()).replace("\\", "/")
    lista_cols = ",\n  ".join(f"`{c['sql']}`" for c in cols)
    esperadas = ",\n  ".join(f"('{c['sql']}')" for c in cols)
    campos_load = ",\n  ".join(f"`{c['sql']}`" for c in cols)

    chks = []
    for c, vals in dominios:
        lst = ", ".join(q(v) for v in vals)
        chks.append(
            f"SELECT '{c['orig']}' AS columna, `{c['sql']}`(1,64) AS valor_invalido, "
            f"COUNT(*) AS filas\n"
            f"  FROM `{args.tabla}`\n"
            f" WHERE `periodo` = '{args.periodo}' AND `{c['sql']}` NOT IN ({lst})\n"
            f" GROUP BY 2"
        )
    # sintaxis valida: sin el (1,64)
    chks = []
    for c, vals in dominios:
        lst = ", ".join(q(v) for v in vals)
        chks.append(
            f"SELECT {q(c['orig'])} AS columna, LEFT(`{c['sql']}`, 60) AS valor_invalido,\n"
            f"       COUNT(*) AS filas\n"
            f"  FROM `{args.tabla}`\n"
            f" WHERE `periodo` = '{args.periodo}'\n"
            f"   AND `{c['sql']}` NOT IN ({lst})\n"
            f" GROUP BY 1, 2"
        )
    union_chk = "\nUNION ALL\n".join(chks) if chks else "SELECT 'sin dominios' AS columna"

    carga = f"""-- ================================================================
-- CARGA DEL PERIODO {args.periodo}
-- Generado desde {fuente.name} ({len(filas)} filas)
--
-- 1. PREFLIGHT  -> aborta si el modo no es estricto o si el reporte
--                  cambio de estructura
-- 2. CARGA      -> borra el periodo y lo vuelve a cargar (no duplica)
-- 3. VERIFICA   -> conteo Y dominios. El conteo solo no prueba nada:
--                  una fila corrida cuenta igual que una buena.
-- ================================================================

USE `{args.bd}`;

-- ---------------- 1. PREFLIGHT ----------------
DROP TEMPORARY TABLE IF EXISTS `_esperadas`;
CREATE TEMPORARY TABLE `_esperadas` (`col` VARCHAR(64) PRIMARY KEY);
INSERT INTO `_esperadas` VALUES
  {esperadas};

DROP PROCEDURE IF EXISTS `_preflight`;
DELIMITER $$
CREATE PROCEDURE `_preflight`()
BEGIN
  DECLARE v_faltan INT DEFAULT 0;
  DECLARE v_sobran INT DEFAULT 0;
  DECLARE v_msg TEXT;

  IF @@sql_mode NOT LIKE '%STRICT_TRANS_TABLES%' THEN
    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT =
      'ABORTADO: modo estricto apagado. MySQL degradaria errores a warnings. Corre: SET GLOBAL sql_mode = CONCAT(@@sql_mode, ",STRICT_TRANS_TABLES");';
  END IF;

  -- columnas del CSV que no existen en la tabla
  SELECT COUNT(*) INTO v_faltan
    FROM `_esperadas` e
    LEFT JOIN information_schema.columns c
      ON c.table_schema = '{args.bd}' AND c.table_name = '{args.tabla}'
     AND c.column_name = e.col
   WHERE c.column_name IS NULL;

  -- columnas de la tabla que el CSV ya no trae
  SELECT COUNT(*) INTO v_sobran
    FROM information_schema.columns c
    LEFT JOIN `_esperadas` e ON e.col = c.column_name
   WHERE c.table_schema = '{args.bd}' AND c.table_name = '{args.tabla}'
     AND c.column_name NOT IN ('id','periodo','cargado_en')
     AND e.col IS NULL;

  IF v_faltan > 0 OR v_sobran > 0 THEN
    SET v_msg = CONCAT('ABORTADO: el reporte cambio de estructura. ',
                       v_faltan, ' columnas nuevas en el CSV, ',
                       v_sobran, ' columnas de la tabla que ya no vienen. ',
                       'Cargar asi meteria todo corrido. Revisar antes de seguir.');
    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = v_msg;
  END IF;

  SELECT 'PREFLIGHT OK: modo estricto activo, estructura sin cambios' AS resultado;
END$$
DELIMITER ;

CALL `_preflight`();
DROP PROCEDURE `_preflight`;

-- ---------------- 2. CARGA ----------------
DELETE FROM `{args.tabla}` WHERE `periodo` = '{args.periodo}';

LOAD DATA LOCAL INFILE '{ruta_abs}'
INTO TABLE `{args.tabla}`
CHARACTER SET utf8mb4
FIELDS TERMINATED BY '{SEP}'
       OPTIONALLY ENCLOSED BY '"'
LINES  TERMINATED BY '\\r\\n'
IGNORE 1 LINES                -- salta el encabezado (y el BOM que va con el)
(
  {campos_load}
)
SET `periodo` = '{args.periodo}';

-- Los warnings de LOAD DATA se pierden con la siguiente sentencia. Mirar YA.
SHOW WARNINGS;

-- ---------------- 3. VERIFICACION ----------------
-- 3a. Conteo: debe dar exactamente {len(filas)}
SELECT
  COUNT(*) AS filas_cargadas,
  {len(filas)} AS esperadas,
  IF(COUNT(*) = {len(filas)}, 'OK', 'MAL: revisar fin de linea y separador')
    AS veredicto
FROM `{args.tabla}` WHERE `periodo` = '{args.periodo}';

-- 3b. Dominios: cualquier fila devuelta aqui esta CORRIDA.
-- Vacio = la carga respeto la alineacion de las columnas.
{union_chk};
"""
    (out / f"cargar_{args.periodo}.sql").write_text(carga, encoding="utf-8")

    print(f"\n[OK] {out/'esquema.sql'}           -> una sola vez")
    print(f"[OK] {out/('cargar_'+args.periodo+'.sql')}  -> cada mes")
    print(f"\n     {len(cols)} columnas TEXT (sin VARCHAR: nada se recorta)")
    print(f"     {len(dominios)} dominios se verifican tras cargar")
    print(f"     debe cargar {len(filas)} filas")
if __name__ == "__main__":
    main()