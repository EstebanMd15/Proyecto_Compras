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


def es_pii(nombre):
    n = sin_tildes(nombre.lower())
    return any(k in n for k in PII_CLAVES)


def q(v):
    return "'" + v.replace("\\", "\\\\").replace("'", "''") + "'"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--salida", default="Salida")
    ap.add_argument("--periodo", required=True, help="ej: 2026-03")
    ap.add_argument("--tabla", default="dispensacion_acum")
    ap.add_argument("--bd", default="mennar_bi")
    # Catalogo de codigos de sucursal (ya existe como tabla en MySQL).
    # Se cruza Bodega Encabezado contra el nombre de la sucursal para traer su codigo.
    ap.add_argument("--cat-tabla", default="codigos_sucursales",
                    help="tabla catalogo con los codigos de sucursal")
    ap.add_argument("--cat-col-nombre", default="Sucursal",
                    help="columna del catalogo que cruza con Bodega Encabezado")
    ap.add_argument("--cat-col-codigo", default="Codigo Bodega",
                    help="columna del catalogo que trae el codigo")
    ap.add_argument("--col-cruce", default="Bodega Encabezado",
                    help="columna del reporte que cruza con el catalogo de sucursales")
    ap.add_argument("--col-codigo", default="codigo_bodega",
                    help="nombre de la columna nueva en la tabla de dispensacion")
    ap.add_argument("--col-codigo-anterior", default="codigo_tipo_comprobante",
                    help="nombre viejo a migrar con CHANGE COLUMN (conserva datos); "
                         "vacio o igual a --col-codigo para no migrar")
    args = ap.parse_args()

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
    print(f"Periodo : {args.periodo}")

    usados = {"id", "periodo", "cargado_en", args.col_codigo}
    cols = []
    for i, orig in enumerate(encabezado):
        cols.append({"i": i, "orig": orig.strip(),
                     "sql": sanear(orig, usados), "pii": es_pii(orig)})

    # Columna del reporte que cruza con el catalogo de sucursales (Bodega
    # Encabezado). Se busca por el nombre original del encabezado, no por
    # posicion, y se aborta con mensaje claro si el reporte no la trae.
    _cruce = next((c for c in cols
                   if c["orig"].strip().lower() == args.col_cruce.strip().lower()), None)
    if _cruce is None:
        raise SystemExit(f"[X] No encontre la columna '{args.col_cruce}' en el "
                         f"encabezado del reporte. Revisa --col-cruce.")
    col_cruce = _cruce["sql"]

    # Columna que precede a la de cruce -> el codigo se inserta ANTES de
    # Bodega Encabezado (MySQL no tiene BEFORE: se usa AFTER la anterior).
    i_cruce = _cruce["i"]
    col_antes = cols[i_cruce - 1]["sql"] if i_cruce > 0 else None
    tras = f" AFTER `{col_antes}`" if col_antes else " FIRST"

    i_cruce = _cruce["i"]
    col_antes = cols[i_cruce - 1]["sql"] if i_cruce > 0 else None

    # Normalizacion del cruce. DEBE ser identica en ambos lados o no emparejan:
    # quita espacios, luego comillas dobles envolventes, luego espacios otra vez
    # (por si al quitar la comilla queda un espacio pegado).
    def norm(ref):
        # colapsa runs de 2+ espacios a 1, quita comillas envolventes y recorta
        ref2 = f"REGEXP_REPLACE({ref}, ' +', ' ')"
        return f"TRIM(TRIM(BOTH '\"' FROM TRIM({ref2})))"
    norm_cat = norm(f"`{args.cat_col_nombre}`")     # lado catalogo
    norm_disp = norm(f"d.`{col_cruce}`")            # lado dispensacion

    def limpiar_espacios(where_sql):
        # deja `col_cruce` con 1 solo espacio entre palabras (reescribe el valor)
        return [
            f"-- Normaliza espacios de `{col_cruce}`: colapsa 2+ a 1 y recorta.",
            f"UPDATE `{args.tabla}`",
            f"SET `{col_cruce}` = REGEXP_REPLACE(TRIM(`{col_cruce}`), ' +', ' ')"
            f"{where_sql};",
        ]

    def bloque_codigo(proc, where_sql):
        """Procedimiento que llena la columna del codigo cruzando contra el
        catalogo. Va dentro de un guard: si el catalogo no existe, avisa y no
        rompe el script. Usa una temporal indexada (rapido, no tumba conexion)
        y LEFT JOIN (una bodega sin codigo queda en NULL). where_sql filtra el
        UPDATE por periodo ('' = todas las filas)."""
        return [
            f"DROP PROCEDURE IF EXISTS `{proc}`;",
            "DELIMITER $$",
            f"CREATE PROCEDURE `{proc}`()",
            "BEGIN",
            "  IF NOT EXISTS (SELECT 1 FROM information_schema.tables",
            f"                 WHERE table_schema = '{args.bd}'",
            f"                   AND table_name = '{args.cat_tabla}') THEN",
            f"    SELECT 'AVISO: no existe {args.cat_tabla}; "
            f"`{args.col_codigo}` queda en NULL' AS aviso;",
            "  ELSE",
            "    DROP TEMPORARY TABLE IF EXISTS `_cat_suc`;",
            "    CREATE TEMPORARY TABLE `_cat_suc` (",
            "      `nombre` VARCHAR(190) NOT NULL,",
            "      `codigo` VARCHAR(64) NULL,",
            "      KEY `ix_nombre` (`nombre`)",
            "    ) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;",
            "    INSERT INTO `_cat_suc` (`nombre`, `codigo`)",
            f"    SELECT {norm_cat}, MAX(`{args.cat_col_codigo}`)",
            f"      FROM `{args.cat_tabla}` GROUP BY 1;",
            f"    UPDATE `{args.tabla}` d",
            "      LEFT JOIN `_cat_suc` c",
            f"        ON c.`nombre` = {norm_disp}",
            f"    SET d.`{args.col_codigo}` = c.`codigo`{where_sql};",
            "    DROP TEMPORARY TABLE `_cat_suc`;",
            "  END IF;",
            "END$$",
            "DELIMITER ;",
            f"CALL `{proc}`();",
            f"DROP PROCEDURE `{proc}`;",
        ]

    n_pii = sum(1 for c in cols if c["pii"])
    print(f"\nColumnas con datos personales/salud: {n_pii}")
    for c in cols:
        if c["pii"]:
            print(f"   [{c['i']:>3}] {c['orig']}")

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
        if c["sql"] == col_cruce:
            # codigo de sucursal, pegado justo ANTES de Bodega Encabezado
            L.append(f"  `{args.col_codigo}` VARCHAR(64) NULL "
                     f"COMMENT {q('Codigo Bodega del catalogo ' + args.cat_tabla)},")
        L.append(f"  `{c['sql']}` TEXT NULL COMMENT {q(c['orig'])},")
    L += [
        "  PRIMARY KEY (`id`),",
        "  KEY `idx_periodo` (`periodo`),",
        f"  KEY `idx_documento` (`{cols[2]['sql']}`(20)),",
        f"  KEY `idx_fecha` (`{cols[4]['sql']}`(12))",
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

    # =====================================================================
    # CODIGO DE SUCURSAL: columna nueva (o migrada) + backfill de lo cargado
    # =====================================================================
    comentario_col = q("Codigo Bodega (" + args.cat_tabla + ") por " + args.col_cruce)
    anterior = (args.col_codigo_anterior or "").strip()
    migra = bool(anterior) and anterior != args.col_codigo

    L += [
        "",
        "-- ================================================================",
        f"-- CODIGO DE SUCURSAL. Deja lista la columna `{args.col_codigo}`",
        (f"-- (la crea, o migra la vieja `{anterior}` conservando sus datos) y"
         if migra else "-- (la crea si la tabla ya existia sin ella) y"),
        f"-- llena TODAS las filas cruzando `{col_cruce}` contra `{args.cat_tabla}`.",
        "-- Idempotente: se puede volver a correr sin dañar nada.",
        "-- ================================================================",
        "DROP PROCEDURE IF EXISTS `_add_col_codigo`;",
        "DELIMITER $$",
        "CREATE PROCEDURE `_add_col_codigo`()",
        "BEGIN",
        "  DECLARE v_nuevo INT DEFAULT 0;",
    ]
    if migra:
        L.append("  DECLARE v_viejo INT DEFAULT 0;")
    L += [
        "  SELECT COUNT(*) INTO v_nuevo FROM information_schema.columns",
        f"   WHERE table_schema = '{args.bd}' AND table_name = '{args.tabla}'",
        f"     AND column_name = '{args.col_codigo}';",
    ]
    if migra:
        L += [
            "  SELECT COUNT(*) INTO v_viejo FROM information_schema.columns",
            f"   WHERE table_schema = '{args.bd}' AND table_name = '{args.tabla}'",
            f"     AND column_name = '{anterior}';",
            "  IF v_nuevo = 0 AND v_viejo > 0 THEN",
            "    -- migra el nombre viejo conservando los datos ya llenos",
            f"    ALTER TABLE `{args.tabla}`",
            f"      CHANGE COLUMN `{anterior}` `{args.col_codigo}` VARCHAR(64) NULL",
            f"      COMMENT {comentario_col}{tras};",
            "  ELSEIF v_nuevo = 0 THEN",
            "    -- no existe ninguna: la crea nueva",
            f"    ALTER TABLE `{args.tabla}`",
            f"      ADD COLUMN `{args.col_codigo}` VARCHAR(64) NULL",
            f"      COMMENT {comentario_col}{tras};",
            "  END IF;",
        ]
    else:
        L += [
            "  IF v_nuevo = 0 THEN",
            f"    ALTER TABLE `{args.tabla}`",
            f"      ADD COLUMN `{args.col_codigo}` VARCHAR(64) NULL",
            f"      COMMENT {comentario_col}{tras};",
            "  END IF;",
        ]
    L += [
        "END$$",
        "DELIMITER ;",
        "CALL `_add_col_codigo`();",
        "DROP PROCEDURE `_add_col_codigo`;",
        "",
        "-- Backfill (una vez): primero normaliza los espacios de la bodega y",
        "-- luego llena la columna del codigo cruzando contra el catalogo. Con",
        "-- guard: si el catalogo no existe, avisa y NO rompe la creacion del",
        "-- esquema. En instalacion de cero la tabla esta vacia, asi que aqui no",
        "-- cambia nada; cada periodo se llena solo en su cargar_<periodo>.sql.",
    ]
    L += limpiar_espacios("")
    L += bloque_codigo("_backfill_codigo", "")
    L += [""]

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
        f"  `{args.col_codigo}`,",
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
        f"  `{args.col_codigo}`,",
        f"  STR_TO_DATE(NULLIF(TRIM(`{cols[4]['sql']}`), ''), '%d/%m/%Y')",
        f"    AS `{cols[4]['sql']}_fecha`,",
        f"  {sel}",
        f"FROM `{args.tabla}`",
        f"WHERE TRIM(`{cols[4]['sql']}`) NOT LIKE '/%';",
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

    # Columnas que el preflight NO debe contar como "sobrantes": las fijas y la
    # del codigo. Se incluye tambien el nombre viejo por si aun no se ha migrado.
    ignora = ["id", "periodo", "cargado_en", args.col_codigo]
    if migra:
        ignora.append(anterior)
    ignora_sql = ",".join("'" + x + "'" for x in ignora)

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

    # bloque 2b: normaliza espacios de la bodega y luego llena el codigo de
    # ESTE periodo (mismo guard de catalogo)
    bloque_2b = "\n".join(
        limpiar_espacios(f" WHERE `periodo` = '{args.periodo}'")
        + bloque_codigo("_codigo_periodo", f" WHERE d.`periodo` = '{args.periodo}'"))

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
      'ABORTADO: falta STRICT_TRANS_TABLES en @@sql_mode. MySQL degradaria errores a warnings. Activalo antes de cargar.';
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
     AND c.column_name NOT IN ({ignora_sql})
     AND e.col IS NULL;

  IF v_faltan > 0 OR v_sobran > 0 THEN
    SET v_msg = CONCAT('ABORTADO: estructura cambiada. ',
                       v_faltan, ' cols nuevas en CSV, ',
                       v_sobran, ' cols que sobran en la tabla. Revisar antes de cargar.');
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

-- ---------------- 2b. CODIGO DE SUCURSAL ----------------
-- Llena `{args.col_codigo}` cruzando Bodega Encabezado contra `{args.cat_tabla}`.
-- El catalogo se normaliza UNA vez en una temporal indexada por nombre, para
-- que el UPDATE haga busquedas por indice y no un escaneo con TRIM en ambos
-- lados (eso tumbaba la conexion: Error 2013). LEFT JOIN: una bodega sin
-- codigo queda en NULL. Guard: si no existe el catalogo, avisa y no rompe.
-- Se llena solo cada mes.
{bloque_2b}

-- Bodegas de este periodo que NO estan en el catalogo (quedaron sin codigo).
-- Si sale algo: agrega ese nombre a `{args.cat_tabla}` y vuelve a correr el UPDATE.
SELECT d.`{col_cruce}` AS bodega_sin_codigo, COUNT(*) AS filas
  FROM `{args.tabla}` d
 WHERE d.`periodo` = '{args.periodo}' AND d.`{args.col_codigo}` IS NULL
 GROUP BY d.`{col_cruce}`
 ORDER BY filas DESC;

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
    print(f"     codigo: `{args.col_codigo}` = {args.cat_tabla}.`{args.cat_col_codigo}`"
          f"  (cruce por `{col_cruce}`, se llena solo)")
    if migra:
        print(f"     migra columna vieja `{anterior}` -> `{args.col_codigo}` "
              f"(CHANGE COLUMN, conserva datos)")
if __name__ == "__main__":
    main()