#!/usr/bin/env python3
"""
decidir.py
==========
Llena k_elegido de decisiones.csv sin que tengas que teclear fila por fila.

TRES RECORTES, EN ESTE ORDEN:

  1) AGRUPAR DUPLICADOS
     L570-573 son la misma fila repetida (4 renglones del mismo documento).
     Se decide una vez por caso unico, no una vez por fila.

  2) COLAPSAR OPCIONES EQUIVALENTES
     Si dos lecturas producen la misma fila despues de quitar el '|' sobrante,
     no hay nada que decidir: son la misma respuesta. Si TODAS las lecturas
     colapsan a una, el caso se resuelve solo.

  3) PUNTUAR CON EL VOCABULARIO DEL CORPUS
     Si un valor pertenece al vocabulario de OTRA columna, esa lectura esta mal.
     'hija' aparece miles de veces en Parentesco y jamas en Nombre -> la lectura
     que pone 'hija' en Nombre queda descartada. Esto no adivina: usa las
     144.056 filas sanas como evidencia.

Lo que queda despues de los tres recortes es ambigüedad real, y esa la decides tu.

Uso:
    python decidir.py                    # interactivo (recomendado)
    python decidir.py --auto             # acepta todas las recomendaciones
    python decidir.py --salida Salida_Feb
"""

import argparse
import csv
import json
from collections import Counter, defaultdict
from pathlib import Path

ENC = "utf-8-sig"
SEP = "|"
VENTANA = 4          # columnas a cada lado de k que se examinan


def cargar(ruta):
    with open(ruta, encoding=ENC, newline="") as f:
        r = csv.reader(f, delimiter=SEP)
        return next(r), list(r)


def vocabularios(filas, ancho):
    """Vocabulario observado de CADA columna. Incluye las de alta cardinalidad:
    aunque no sirvan de validador duro, sirven de evidencia."""
    return [set(f[i] for f in filas) for i in range(ancho)]


def tecleable(vocab_col, n_filas):
    """Solo una columna donde un humano escribe puede contener el delimitador.
    Evidencia: alta cardinalidad, o variantes de mayusculas ('Paciente'/'PACIENTE')."""
    if len(vocab_col) > 50:
        return True
    return len({v.strip().lower() for v in vocab_col}) < len(vocab_col)


def limpio(v):
    return v.replace(SEP, "").strip()


def firma(prop):
    """Como queda la fila si le quitas los '|' sobrantes. Dos lecturas con la
    misma firma son la misma respuesta."""
    return tuple(limpio(v) for v in prop)


def puntuar(prop, k, vocab, ancho):
    """+1 si un valor esta en el vocabulario de SU columna.
       -2 si esta en el de otra columna cercana (senal de desalineacion)."""
    lo, hi = max(0, k - VENTANA), min(ancho, k + VENTANA + 1)
    score = 0
    for j in range(lo, hi):
        if j == k:
            continue
        v = prop[j].strip()
        if not v:
            continue
        if v in vocab[j]:
            score += 1
            continue
        for m in range(lo, hi):
            if m != j and v in vocab[m]:
                score -= 2
                break
    return score


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--salida", default="Salida")
    ap.add_argument("--auto", action="store_true")
    args = ap.parse_args()

    out = Path(args.salida)
    encabezado, limpias = cargar(out / "limpio.csv")
    ancho = len(encabezado)
    vocab = vocabularios(limpias, ancho)
    tecl = {i for i in range(ancho) if tecleable(vocab[i], len(limpias))}
    print(f"Corpus: {len(limpias)} filas | {ancho} columnas | "
          f"{len(tecl)} tecleables\n")

    with open(out / "cuarentena.csv", encoding=ENC, newline="") as f:
        cuar = list(csv.DictReader(f))

    # ---------- RECORTE 1: agrupar filas identicas ----------
    grupos = defaultdict(list)
    for fila in cuar:
        grupos[fila["linea_cruda"]].append(int(fila["linea_origen"]))
    print(f"Filas en cuarentena : {len(cuar)}")
    print(f"Casos unicos        : {len(grupos)}   <- solo estos hay que decidir\n")

    decisiones = {}
    pendientes = []

    for n_caso, (cruda, origenes) in enumerate(sorted(
            grupos.items(), key=lambda t: t[1][0]), 1):
        campos = cruda.split(SEP)
        extra = len(campos) - ancho

        # candidatos, restringidos a columnas tecleables
        cands = []
        for k in sorted(tecl):
            if k + extra >= len(campos):
                continue
            prop = campos[:k] + [SEP.join(campos[k:k + extra + 1])] + campos[k + extra + 1:]
            if len(prop) != ancho:
                continue
            # las columnas de dominio cerrado deben respetarse
            ok = all(prop[m] in vocab[m] for m in range(ancho)
                     if m != k and m not in tecl)
            if ok:
                cands.append((k, prop))

        if not cands:
            pendientes.append((origenes, "SIN_CANDIDATOS"))
            continue

        # ---------- RECORTE 2: colapsar equivalentes ----------
        porfirma = defaultdict(list)
        for k, prop in cands:
            porfirma[firma(prop)].append((k, prop))

        # ---------- RECORTE 3: puntuar ----------
        opciones = []
        for f_, lista in porfirma.items():
            k, prop = max(lista, key=lambda t: puntuar(t[1], t[0], vocab, ancho))
            opciones.append((puntuar(prop, k, vocab, ancho), k, prop, len(lista)))
        opciones.sort(reverse=True)

        etiqueta = (f"CASO {n_caso}/{len(grupos)}  ->  {len(origenes)} fila(s): "
                    f"L{', L'.join(str(o) for o in origenes)}")
        print("=" * 70)
        print(etiqueta)
        print("=" * 70)

        if len(opciones) == 1:
            _, k, prop, _ = opciones[0]
            print(f"  [AUTO] Todas las lecturas dan la misma fila. k={k}")
            for o in origenes:
                decisiones[o] = (k, len(campos), "AUTO_EQUIVALENTES")
            print()
            continue

        letras = "ABCDEFGH"
        for idx, (score, k, prop, n_eq) in enumerate(opciones):
            eq = f" (={n_eq} lecturas equivalentes)" if n_eq > 1 else ""
            rec = "  <-- RECOMENDADA" if idx == 0 else ""
            print(f"\n  {letras[idx]}) k={k} -> '|' en {encabezado[k].strip()!r} "
                  f"| puntaje {score:+d}{eq}{rec}")
            lo, hi = max(0, k - 2), min(ancho, k + 3)
            for j in range(lo, hi):
                marca = " <<<" if j == k else ""
                print(f"        [{j:>3}] {encabezado[j].strip():<28} = {prop[j]!r}{marca}")

        mejor_k = opciones[0][1]
        if args.auto:
            print(f"\n  [AUTO] {letras[0]}  (k={mejor_k})")
            eleccion = 0
        else:
            resp = input(f"\n  Elige [{letras[0]}]/{'/'.join(letras[1:len(opciones)])}"
                         f"/s=saltar: ").strip().upper()
            if resp == "S":
                pendientes.append((origenes, "SALTADO"))
                print()
                continue
            eleccion = letras.index(resp) if resp in letras[:len(opciones)] else 0

        k = opciones[eleccion][1]
        for o in origenes:
            decisiones[o] = (k, len(campos), "ELEGIDA")
        print()

    # ---------- Escribir decisiones.csv ----------
    ruta = out / "decisiones.csv"
    with open(ruta, "w", encoding=ENC, newline="") as f:
        w = csv.writer(f, quoting=csv.QUOTE_ALL)
        w.writerow(["linea_origen", "num_campos", "k_elegido", "estado"])
        for fila in cuar:
            o = int(fila["linea_origen"])
            if o in decisiones:
                k, nc, estado = decisiones[o]
                w.writerow([o, nc, k, estado])
            else:
                w.writerow([o, fila["num_campos"], "", "PENDIENTE"])

    print("=" * 70)
    print(f"  filas decididas : {len(decisiones)} / {len(cuar)}")
    print(f"  pendientes      : {len(cuar) - len(decisiones)}")
    print(f"\nEscrito: {ruta}")
    if len(decisiones) == len(cuar):
        print("Siguiente: python finalizar.py --salida " + str(out))
    else:
        print("[!] Hay filas sin decidir. No se pierden: quedan en cuarentena.")


if __name__ == "__main__":
    main()