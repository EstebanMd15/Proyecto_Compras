#!/usr/bin/env python3
"""
leer_excel.py
=============
Convierte el reporte de Excel al mismo CSV que consume el resto del pipeline.

POR QUE ESTE REPORTE NO NECESITA LIMPIEZA
    limpiar_reporte.py / decidir.py / finalizar_v2.py existen para arreglar una
    falla de DELIMITACION en texto plano. Un Excel no tiene delimitador: no hay
    '|' que confundir ni saltos de linea que partan registros. Ese daño es
    imposible aqui. Solo hay que leerlo sin dañarlo.

LAS DOS TRAMPAS QUE SI EXISTEN

  1) El '.xls' puede no ser un Excel.
     Muchos exportadores viejos escriben HTML o texto tabulado y le ponen
     extension .xls. Excel lo abre igual; pandas revienta. Se miran los BYTES,
     no el nombre.

  2) pandas altera los datos en silencio.
     Por defecto convierte '2026-07-01' a datetime, las celdas vacias a NaN, y
     un NIT '0012345' a numero -> el cero a la izquierda DESAPARECE. Sin error
     ni warning. Por eso: dtype=str, keep_default_na=False.

QUE HACE
    - Detecta el formato real por bytes magicos y elige el motor.
    - Encuentra la fila de encabezado (la primera con todas las celdas llenas).
    - Preserva el membrete en preambulo.txt.
    - Escribe reporte_limpio.csv con las mismas convenciones que el resto del
      pipeline, para que generar_sql.py funcione igual.
    - Sanea los '|' que los usuarios hayan tecleado (al escribir CSV delimitado
      por '|', un '|' dentro de una celda recrearia el problema original).

Uso:
    python leer_excel.py Datos/Remision_Julio.xls --salida Salida_Remision_Julio
"""

import argparse
import csv
import sys
from collections import Counter
from pathlib import Path

ENC_OUT = "utf-8-sig"
SEP = "|"

FIRMAS = [
    (b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1", "xls",  "Excel 97-2003 (OLE2)"),
    (b"PK\x03\x04",                        "xlsx", "Excel moderno (ZIP/OOXML)"),
]


def detectar_formato(path):
    with open(path, "rb") as f:
        cab = f.read(2048)
    for firma, clave, desc in FIRMAS:
        if cab.startswith(firma):
            return clave, desc
    bajo = cab.lower().lstrip()
    if bajo.startswith(b"<") or b"<table" in bajo or b"<html" in bajo:
        return "html", "HTML disfrazado de Excel (exportador viejo)"
    return "texto", "texto plano disfrazado de Excel"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("archivo")
    ap.add_argument("--salida", default="Salida_Excel")
    ap.add_argument("--hoja", default=0, help="nombre o indice de la hoja")
    ap.add_argument("--reemplazo", default=" / ")
    args = ap.parse_args()

    try:
        import pandas as pd
    except ImportError:
        sys.exit("[X] Falta pandas. pip install pandas openpyxl xlrd")

    ruta = Path(args.archivo)
    if not ruta.exists():
        sys.exit(f"[X] No existe {ruta}")

    out = Path(args.salida)
    out.mkdir(parents=True, exist_ok=True)

    # ---------- 1. Que es este archivo REALMENTE ----------
    fmt, desc = detectar_formato(ruta)
    print(f"Archivo   : {ruta}")
    print(f"Extension : {ruta.suffix}")
    print(f"Formato REAL (por bytes): {fmt}  -> {desc}")
    if fmt in ("html", "texto"):
        print(f"  [!] La extension dice {ruta.suffix} pero NO es un Excel.")
        if fmt == "texto":
            print("      Es texto plano: entonces SI puede tener el problema de")
            print("      delimitacion. Corre diagnostico_reporte.py sobre el, no esto.")
            sys.exit(1)

    # ---------- 2. Leer SIN que pandas interprete nada ----------
    # dtype=str + keep_default_na=False: sin datetimes inventados, sin NaN,
    # sin ceros a la izquierda perdidos.
    print("\nLeyendo con dtype=str, keep_default_na=False (pandas no interpreta)...")
    try:
        if fmt == "xls":
            df = pd.read_excel(ruta, sheet_name=args.hoja, header=None,
                               dtype=str, keep_default_na=False, engine="xlrd")
        elif fmt == "xlsx":
            df = pd.read_excel(ruta, sheet_name=args.hoja, header=None,
                               dtype=str, keep_default_na=False, engine="openpyxl")
        else:  # html
            tablas = pd.read_html(ruta, header=None)
            df = max(tablas, key=len).astype(str)
    except ImportError as e:
        sys.exit(f"[X] Falta el motor de lectura: {e}\n"
                 f"    xls -> pip install xlrd  |  xlsx -> pip install openpyxl")

    df = df.fillna("").astype(str)
    filas = [[c.strip() if c else "" for c in row] for row in df.values.tolist()]
    ancho = len(filas[0]) if filas else 0
    print(f"Filas leidas: {len(filas)}  |  Columnas: {ancho}")

    # ---------- 3. Encontrar el encabezado ----------
    # El membrete tiene 2-4 celdas con dato y el resto vacias.
    # El encabezado es la primera fila con (casi) todas llenas.
    i_enc = None
    for i, fila in enumerate(filas):
        llenas = sum(1 for c in fila if c)
        if llenas >= ancho * 0.9:
            i_enc = i
            break
    if i_enc is None:
        sys.exit("[X] No se encontro fila de encabezado. Revisa el archivo a mano.")

    preambulo, encabezado = filas[:i_enc], filas[i_enc]
    datos = filas[i_enc + 1:]
    # descartar filas totalmente vacias del final (Excel las agrega)
    vacias = sum(1 for f in datos if not any(f))
    datos = [f for f in datos if any(f)]

    print(f"\nMembrete   : {len(preambulo)} fila(s) -> preambulo.txt")
    for p in preambulo:
        print(f"   {[c for c in p if c]}")
    print(f"Encabezado : fila {i_enc+1}, {len(encabezado)} columnas")
    for j, n in enumerate(encabezado):
        print(f"   [{j:>3}] {n!r}")
    print(f"\nFilas de datos : {len(datos)}")
    print(f"Filas vacias descartadas (relleno de Excel): {vacias}")

    (out / "preambulo.txt").write_text(
        "\n".join(" | ".join(c for c in p if c) for p in preambulo),
        encoding=ENC_OUT)

    # ---------- 4. Sanear los '|' tecleados ----------
    # Vamos a escribir CSV delimitado por '|'. Un '|' dentro de una celda
    # recrearia exactamente el problema del otro reporte.
    saneos = []
    limpias = []
    for n, fila in enumerate(datos, 1):
        nueva = []
        for j, v in enumerate(fila):
            if SEP in v:
                nv = v.replace(SEP, args.reemplazo)
                saneos.append([n, j, encabezado[j], v, nv])
                nueva.append(nv)
            else:
                nueva.append(v)
        limpias.append(nueva)

    if saneos:
        print(f"\n[!] Celdas con '|' tecleado: {len(saneos)} (ver saneamiento.csv)")
        for s in saneos[:10]:
            print(f"    fila {s[0]} col {s[1]} ({s[2]}): {s[3]!r} -> {s[4]!r}")
        with open(out / "saneamiento.csv", "w", encoding=ENC_OUT, newline="") as f:
            w = csv.writer(f, quoting=csv.QUOTE_ALL)
            w.writerow(["fila", "columna", "nombre_columna", "antes", "despues"])
            w.writerows(saneos)
    else:
        print("\n[OK] Ninguna celda contiene '|'.")

    # ---------- 5. Verificar ANTES de escribir ----------
    malas = [n for n, f in enumerate(limpias, 1) if len(f) != len(encabezado)]
    if malas:
        sys.exit(f"[X] {len(malas)} filas sin {len(encabezado)} columnas: {malas[:5]}. "
                 "No se escribio nada.")
    if any(SEP in c for f in limpias for c in f):
        sys.exit("[X] Quedan '|' internos. No se escribio nada.")

    # ---------- 6. Escribir ----------
    ruta_out = out / "reporte_limpio.csv"
    with open(ruta_out, "w", encoding=ENC_OUT, newline="") as f:
        w = csv.writer(f, delimiter=SEP, quoting=csv.QUOTE_MINIMAL)
        w.writerow(encabezado)
        w.writerows(limpias)

    print("\n" + "=" * 60)
    print(f"  filas en Excel (sin membrete ni vacias) : {len(datos)}")
    print(f"  filas escritas                          : {len(limpias)}")
    if len(limpias) != len(datos):
        sys.exit("[X] PERDIDA DE DATOS.")
    print(f"\n[OK] {ruta_out}")
    print("\nSiguiente: generar_sql.py --salida " + str(out))
    print("  OJO: generar_sql.py asume col 2 = Documento y col 4 = Fecha.")
    print("  En este reporte las posiciones son otras. Revisar antes de correrlo.")


if __name__ == "__main__":
    main()