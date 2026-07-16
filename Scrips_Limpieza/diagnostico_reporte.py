#!/usr/bin/env python3
"""
inspeccion_excedidas.py
-----------------------
NO limpia. Cierra el ultimo hueco: las 24 lineas con > 128 campos.

Estructura confirmada del archivo:
    L1  = membrete del reporte (6 campos)
    L2  = ENCABEZADO (128 campos)
    L3+ = datos
    separador '|', encoding cp1252, comillas NO estructurales.

Tecnica: en vez de inferir por tipo (ciego cuando se corren campos vacios
dentro de zonas vacias), se usa VERDAD DE TERRENO:

    Las filas del mismo Documento comparten los valores de las columnas
    de nivel documento/paciente. Se comparan las filas dañadas contra sus
    hermanas SANAS del mismo documento y el punto de inyeccion aparece solo.

Uso:
    python inspeccion_excedidas.py Datos/Reporte_Dispensacion_2026_01.csv
"""

import argparse
from collections import defaultdict

ENC = "cp1252"
SEP = "|"
ANCHO_OK = 128
COL_DOC = 2  # 'Documento'


def titulo(t):
    print("\n" + "=" * 72)
    print(t)
    print("=" * 72)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("archivo")
    args = ap.parse_args()

    with open(args.archivo, encoding=ENC, newline="") as f:
        lineas = f.read().splitlines()

    encabezado = lineas[1].split(SEP)          # L2
    datos = [(i, l.split(SEP)) for i, l in enumerate(lineas) if i >= 2]

    # ---------- 1. El encabezado completo, por fin ----------
    titulo("1. ENCABEZADO REAL (L2) - las 128 columnas")
    for i, nombre in enumerate(encabezado):
        marca = ""
        if i == 121: marca = "   <-- parentesco?"
        if i == 122: marca = "   <-- SOSPECHOSA: telefonos con '|'"
        if i == 125: marca = "   <-- LA DEL SALTO DE LINEA (daño A)"
        if i in (26, 47): marca = "   <-- tambien con '|' intruso"
        print(f"  [{i:>3}] {nombre.strip()!r}{marca}")

    # ---------- 2. Agrupar filas sanas por documento ----------
    sanas_por_doc = defaultdict(list)
    for i, f_ in datos:
        if len(f_) == ANCHO_OK:
            sanas_por_doc[f_[COL_DOC]].append(f_)

    def columnas_constantes(filas):
        """Columnas cuyo valor NO cambia entre las filas del documento.
        Esas son las de nivel documento/paciente -> sirven de checkpoint duro."""
        if len(filas) < 2:
            return {}
        const = {}
        for j in range(ANCHO_OK):
            vals = {f[j] for f in filas}
            if len(vals) == 1:
                const[j] = vals.pop()
        return const

    # ---------- 3. Las excedidas, una por una ----------
    titulo("3. LAS 24 EXCEDIDAS - punto de inyeccion por verdad de terreno")

    excedidas = [(i, f_) for i, f_ in datos if len(f_) > ANCHO_OK]
    print(f"Total: {len(excedidas)}\n")

    for i, f_ in excedidas:
        extra = len(f_) - ANCHO_OK
        doc = f_[COL_DOC]
        hermanas = sanas_por_doc.get(doc, [])
        print("-" * 72)
        print(f"L{i+1}  |  {len(f_)} campos (sobran {extra})  |  Documento={doc!r}")
        print(f"   hermanas SANAS del mismo documento: {len(hermanas)}")

        punto = None
        if len(hermanas) >= 2:
            const = columnas_constantes(hermanas)
            print(f"   columnas constantes en el documento: {len(const)}")
            # escaneo izquierda contra los valores reales, no contra tipos
            for j in sorted(const):
                if f_[j] != const[j]:
                    punto = j
                    print(f"   [!] primer desajuste en col {j} "
                          f"({encabezado[j].strip()!r})")
                    print(f"       esperado : {const[j]!r}")
                    print(f"       encontrado: {f_[j]!r}")
                    break
            if punto is None:
                print("   [OK] todas las columnas constantes cuadran desde la izquierda")
                print("        -> el '|' intruso esta en una columna que VARIA por fila")
        elif len(hermanas) == 1:
            print("   solo 1 hermana: comparacion posicional directa")
            h = hermanas[0]
            for j in range(ANCHO_OK):
                if f_[j] != h[j]:
                    print(f"   primer valor distinto en col {j} "
                          f"({encabezado[j].strip()!r}): {f_[j]!r} vs {h[j]!r}")
                    break
        else:
            print("   [!] SIN hermanas sanas. Este documento esta dañado completo.")

        # volcado crudo de la cola: aqui viven los 11 casos ciegos
        print(f"\n   COLA CRUDA (campos 118..{len(f_)-1}):")
        for k in range(118, len(f_)):
            nombre = encabezado[k].strip() if k < ANCHO_OK else ">>> EXTRA <<<"
            print(f"      f[{k:>3}] = {f_[k]!r:<45} | col esperada: {nombre}")

        # candidatos de fusion: probar cada posicion y ver cual reconstruye algo sensato
        if punto is not None:
            k = punto
            prop = f_[:k] + [SEP.join(f_[k:k + extra + 1])] + f_[k + extra + 1:]
            print(f"\n   PROPUESTA: fusionar f[{k}]..f[{k+extra}] -> {len(prop)} campos "
                  f"{'[OK]' if len(prop) == ANCHO_OK else '[X]'}")
            print(f"      col {k} ({encabezado[k].strip()!r}) = {prop[k]!r}")
            # verificar que TODO lo demas cuadre con las constantes del documento
            if len(hermanas) >= 2:
                const = columnas_constantes(hermanas)
                fallos = [j for j in const if prop[j] != const[j]]
                print(f"      constantes violadas tras fusionar: {len(fallos)} "
                      f"{'[OK] fila reconstruida' if not fallos else fallos[:6]}")
        print()

    # ---------- 4. Reconciliacion corregida ----------
    titulo("4. RECONCILIACION CORREGIDA (L2 es encabezado, no dato)")
    n128 = sum(1 for i, f_ in datos if len(f_) == ANCHO_OK)
    n126 = sum(1 for i, f_ in datos if len(f_) == 126)
    nexc = len(excedidas)
    print(f"Lineas fisicas          : {len(lineas)}")
    print(f"  L1 membrete           : 1")
    print(f"  L2 encabezado         : 1")
    print(f"  datos sanos (128)     : {n128}")
    print(f"  pares 126+3           : {n126} registros = {n126*2} lineas")
    print(f"  excedidas             : {nexc}")
    print(f"  suma                  : {2 + n128 + n126*2 + nexc}")
    print(f"\nINVARIANTE DE SALIDA: {n128 + n126 + nexc} filas de datos + 1 encabezado")
    print("El limpiador debe reventar si no produce exactamente ese numero.")


if __name__ == "__main__":
    main()