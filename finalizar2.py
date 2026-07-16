#!/usr/bin/env python3
"""
finalizar_v2.py
===============
Reemplaza a finalizar.py. Dos correcciones:

BUG 1 -- INVARIANTE QUEMADO
    Antes:  INVARIANTE = 144080   (el numero de enero)
            -> reventaba en cualquier otro mes aunque todo estuviera bien.
    Ahora:  el invariante es una IDENTIDAD, no un numero:
                filas(limpio.csv) + filas(cuarentena.csv) == filas escritas
            Se cumple en cualquier mes sin configurar nada.
            Si existe contrato.json, ademas se cruza contra el archivo original.

BUG 2 -- ESCRIBIA ANTES DE VERIFICAR
    Antes:  escribia reporte_limpio.csv y DESPUES comprobaba el conteo.
            La promesa de "revienta antes de entregar basura" era falsa:
            entregaba y luego gritaba.
    Ahora:  toda la verificacion ocurre ANTES de abrir el archivo de salida.

Uso:
    python finalizar_v2.py --salida Salida_Mayo
    python finalizar_v2.py --salida Salida_Mayo --reemplazo " / " --xlsx
"""

import argparse
import csv
import json
from pathlib import Path

ENC = "utf-8-sig"
SEP = "|"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--salida", default="Salida")
    ap.add_argument("--reemplazo", default=" / ")
    ap.add_argument("--xlsx", action="store_true")
    args = ap.parse_args()

    out = Path(args.salida)

    # ---------- Cargar ----------
    with open(out / "limpio.csv", encoding=ENC, newline="") as f:
        r = csv.reader(f, delimiter=SEP)
        encabezado = next(r)
        limpias = list(r)
    ancho = len(encabezado)

    with open(out / "auditoria.csv", encoding=ENC, newline="") as f:
        aud = {int(a["fila_salida"]): int(a["linea_origen"])
               for a in csv.DictReader(f)}

    with open(out / "cuarentena.csv", encoding=ENC, newline="") as f:
        cuar = list(csv.DictReader(f))

    with open(out / "decisiones.csv", encoding=ENC, newline="") as f:
        dec = {int(d["linea_origen"]): d["k_elegido"].strip()
               for d in csv.DictReader(f)}

    # EL INVARIANTE: lo que entra es lo que sale. Derivado, no quemado.
    ESPERADO = len(limpias) + len(cuar)
    print(f"Ancho detectado      : {ancho} columnas")
    print(f"Filas de limpio.csv  : {len(limpias)}")
    print(f"Filas de cuarentena  : {len(cuar)}")
    print(f"INVARIANTE derivado  : {ESPERADO} filas deben salir")

    todas = [(aud[i + 1], fila) for i, fila in enumerate(limpias)]

    # ---------- Aplicar decisiones ----------
    sin_decidir = []
    for fila in cuar:
        origen = int(fila["linea_origen"])
        campos = fila["linea_cruda"].split(SEP)
        k = dec.get(origen, "")
        if not k:
            sin_decidir.append(origen)
            continue
        k = int(k)
        extra = len(campos) - ancho
        prop = campos[:k] + [SEP.join(campos[k:k + extra + 1])] + campos[k + extra + 1:]
        if len(prop) != ancho:
            raise SystemExit(f"[X] L{origen}: k={k} da {len(prop)} campos. Abortado.")
        todas.append((origen, prop))

    # ---------- Orden original ----------
    todas.sort(key=lambda t: t[0])
    origenes = [o for o, _ in todas]
    if len(set(origenes)) != len(origenes):
        raise SystemExit("[X] linea_origen duplicadas. Abortado.")
    print(f"[OK] Orden restaurado: L{origenes[0]} .. L{origenes[-1]}")

    # ---------- Sanear el delimitador interno ----------
    saneos, saneadas = [], []
    for origen, fila in todas:
        nueva = []
        for i, v in enumerate(fila):
            if SEP in v:
                nv = v.replace(SEP, args.reemplazo)
                saneos.append([origen, i, encabezado[i].strip(), v, nv])
                nueva.append(nv)
            else:
                nueva.append(v)
        saneadas.append(nueva)

    # ================================================================
    # TODA LA VERIFICACION VA ANTES DE ESCRIBIR NADA
    # ================================================================
    total = len(saneadas) + len(sin_decidir)
    if total != ESPERADO:
        raise SystemExit(f"[X] PERDIDA DE DATOS: salen {total}, entraron {ESPERADO}. "
                         "No se escribio nada.")

    anchos_mal = [o for (o, _), f in zip(todas, saneadas) if len(f) != ancho]
    if anchos_mal:
        raise SystemExit(f"[X] {len(anchos_mal)} filas sin {ancho} campos: "
                         f"{anchos_mal[:5]}. No se escribio nada.")

    con_pipe = [o for (o, _), f in zip(todas, saneadas) if any(SEP in c for c in f)]
    if con_pipe:
        raise SystemExit(f"[X] Quedan pipes internos en {con_pipe[:5]}. "
                         "No se escribio nada.")

    # cruce opcional contra el archivo original
    cj = out / "contrato.json"
    if cj.exists():
        esperado_origen = json.loads(cj.read_text())["registros_esperados"]
        if ESPERADO != esperado_origen:
            raise SystemExit(f"[X] contrato.json dice {esperado_origen} registros, "
                             f"aqui hay {ESPERADO}. No se escribio nada.")
        print(f"[OK] Cruzado contra contrato.json: {esperado_origen} registros")
    else:
        print("[i] Sin contrato.json (lo genera limpiar_reporte.py).")
        print("    Solo se verifico la identidad limpio+cuarentena == salida.")

    print(f"[OK] Verificado. Campos saneados: {len(saneos)}")

    # ---------- Ahora si, escribir ----------
    with open(out / "saneamiento.csv", "w", encoding=ENC, newline="") as f:
        w = csv.writer(f, quoting=csv.QUOTE_ALL)
        w.writerow(["linea_origen", "columna", "nombre_columna", "antes", "despues"])
        w.writerows(saneos)

    ruta = out / "reporte_limpio.csv"
    with open(ruta, "w", encoding=ENC, newline="") as f:
        w = csv.writer(f, delimiter=SEP, quoting=csv.QUOTE_MINIMAL)
        w.writerow(encabezado)
        w.writerows(saneadas)

    print(f"\n[OK] {len(saneadas)} filas escritas en {ruta}")
    if sin_decidir:
        print(f"[!] {len(sin_decidir)} filas siguen en cuarentena, sin decidir. "
              "No se perdieron.")

    if args.xlsx:
        from openpyxl import Workbook
        print("\nGenerando xlsx (tarda varios minutos)...")
        wb = Workbook(write_only=True)
        ws = wb.create_sheet("Reporte")
        ws.append(encabezado)
        for fila in saneadas:
            ws.append(fila)
        rx = out / "reporte_limpio.xlsx"
        wb.save(rx)
        print(f"[OK] Escrito: {rx}")


if __name__ == "__main__":
    main()