#!/usr/bin/env python3
"""
verificar_salida.py
===================
Test decisivo: ¿el corrimiento esta EN EL ARCHIVO o solo en como Excel lo lee?

Lee limpio_final.csv con Python y comprueba las columnas de dominio cerrado
que ya conocemos del corpus de 144.056 filas. Si Python las ve correctas,
el archivo esta bien y el problema es la importacion de Excel.

Uso:
    python verificar_salida.py
    python verificar_salida.py --archivo Salida/limpio.csv
"""

import argparse
import csv
from collections import Counter
from pathlib import Path

ENC = "utf-8-sig"
SEP = "|"
ANCHO = 128

# Dominios cerrados, sacados del propio corpus. Si una columna se sale de
# aqui, la fila esta desalineada. No es opinion: es el 100% de las filas.
CONTRATO = {"CAPITA", "EVENTO"}
DOMINIOS = {
    1:   ({"PRINCIPAL"}, "Sucursal"),
    3:   ({"Activo", "Inactivo"}, "Estado"),
    12:  ({"CC", "CE", "PE", "PT", "RC", "SC", "TI"}, "Documento Paciente"),
    25:  ({"CAPITADO", "MIPRES", "POS", "TUTELA"}, "Tipo Servicio"),
    35:  ({"(F) FEMENINO", "(M) MASCULINO"}, "Genero"),
    46:  (CONTRATO, "Contrato"),
    48:  ({"NO", "SI"}, "Domicilio"),
    90:  ({"NO PBS", "PBS"}, "PBS/NO PBS"),
    102: ({"CAUCA"}, "Departamento tipo comprobante"),
    118: ({"No", "Si"}, "Excluir Cuota de manejo ?"),
    123: ({"0", "1", "2", "3", "4", "5", "6", "7"}, "Cantidad Soportes"),
}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--archivo", default="Salida/limpio_final.csv")
    args = ap.parse_args()

    ruta = Path(args.archivo)
    with open(ruta, encoding=ENC, newline="") as f:
        r = csv.reader(f, delimiter=SEP)
        encabezado = next(r)
        filas = list(r)

    print("=" * 68)
    print(f"ARCHIVO: {ruta}")
    print("=" * 68)
    print(f"Columnas en encabezado : {len(encabezado)}")
    print(f"Filas de datos         : {len(filas)}")

    # ---------- 1. Ancho ----------
    anchos = Counter(len(f) for f in filas)
    print(f"Anchos encontrados     : {dict(sorted(anchos.items()))}")
    if set(anchos) != {ANCHO}:
        print("  [X] Hay filas que no tienen 128 campos. Eso SI es un bug del script.")
    else:
        print("  [OK] Todas las filas tienen exactamente 128 campos.")

    # ---------- 2. El test que decide ----------
    print("\n" + "=" * 68)
    print("VALIDACION DE DOMINIOS CERRADOS  (esto decide de quien es la culpa)")
    print("=" * 68)
    total_malas = 0
    for i, (dominio, nombre) in sorted(DOMINIOS.items()):
        malas = [n for n, f in enumerate(filas, 1) if f[i] not in dominio]
        estado = "[OK]" if not malas else f"[X] {len(malas)} filas fuera"
        print(f"  [{i:>3}] {nombre:<30} {estado}")
        if malas:
            total_malas += len(malas)
            for n in malas[:3]:
                print(f"          fila {n}: {filas[n-1][i]!r}")

    # ---------- 3. Veredicto ----------
    print("\n" + "=" * 68)
    print("VEREDICTO")
    print("=" * 68)
    if total_malas == 0:
        print("El archivo esta BIEN ALINEADO leido desde Python.")
        print("Si Excel te lo muestra corrido, el problema es la IMPORTACION:")
        print("  -> Excel esta partiendo los campos entrecomillados que")
        print("     contienen '|'. Hay que importar con calificador de texto '\"'")
        print("     o cambiar el separador de salida a uno que nadie teclee.")
    else:
        print(f"El archivo esta MAL: {total_malas} violaciones de dominio.")
        print("El corrimiento SI esta en los datos. Es un bug del script.")

    # ---------- 4. Cuantas filas traen '|' adentro ----------
    con_pipe = [(n, [i for i in range(ANCHO) if SEP in f[i]])
                for n, f in enumerate(filas, 1) if any(SEP in c for c in f)]
    print(f"\nFilas con '|' DENTRO de un campo (las que Excel puede romper): "
          f"{len(con_pipe)}")
    for n, cols in con_pipe[:30]:
        detalle = ", ".join(f"{c} ({encabezado[c].strip()})" for c in cols)
        print(f"   fila {n}: col {detalle}")

    # ---------- 5. Comparacion visual encabezado vs primera fila ----------
    print("\n" + "=" * 68)
    print("ALINEACION ENCABEZADO vs FILA 1  (columnas 44..58)")
    print("=" * 68)
    for i in range(44, 59):
        print(f"  [{i:>3}] {encabezado[i].strip():<32} = {filas[0][i]!r}")


if __name__ == "__main__":
    main()