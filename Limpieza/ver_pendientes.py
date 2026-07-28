#!/usr/bin/env python3
"""
ver_pendientes.py
=================
Resuelve las filas que quedaron en PENDIENTE / SIN_CANDIDATOS.

POR QUE QUEDARON PENDIENTES
    decidir.py asume que los pipes sobrantes estan TODOS en el mismo campo:
    prueba fusionar k, k+1, k+2 contiguos. Eso cubre '3136600928 | | 320668...'
    (dos pipes en el telefono), pero NO cubre un pipe en Observacion y otro
    en Telefono: dos inyecciones en columnas distintas y separadas.

EL CAMBIO DE PREGUNTA
    En vez de "¿en que campo esta el pipe?" -> "¿cuales de estos separadores
    son falsos?". Una fila de 130 campos tiene 129 separadores; 128 son reales
    y 2 son falsos. Se prueban TODAS las combinaciones de cuales 2.
    Eso cubre los dos casos sin distinguirlos.

    Solo se consideran falsos los separadores pegados a columnas TECLEABLES:
    un desplegable no puede contener un '|' escrito por nadie.

Uso:
    python ver_pendientes.py --salida Salida_Mayo
    python ver_pendientes.py --salida Salida_Mayo --linea 84632
"""

import argparse
import csv
import unicodedata
from collections import Counter, defaultdict
from itertools import combinations
from pathlib import Path

ENC = "utf-8-sig"
SEP = "|"
VENTANA = 4
MAX_COMBOS = 400_000


def cargar(ruta):
    with open(ruta, encoding=ENC, newline="") as f:
        r = csv.reader(f, delimiter=SEP)
        return next(r), list(r)


def tecleable(vals):
    if len(vals) > 50:
        return True
    return len({v.strip().lower() for v in vals}) < len(vals)


def limpio(v):
    return v.replace(SEP, "").strip()


def reconstruir(campos, falsos):
    """Une los campos cuyo separador se marco como falso."""
    prop, cur = [], campos[0]
    for i in range(len(campos) - 1):
        if i in falsos:
            cur = cur + SEP + campos[i + 1]
        else:
            prop.append(cur)
            cur = campos[i + 1]
    prop.append(cur)
    return prop


def puntuar(prop, tocados, vocab, ancho):
    """+1 si un valor esta en el vocabulario de SU columna.
       -2 si esta en el de otra columna cercana (senal de desalineacion)."""
    score = 0
    for k in tocados:
        lo, hi = max(0, k - VENTANA), min(ancho, k + VENTANA + 1)
        for j in range(lo, hi):
            if j in tocados:
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
    ap.add_argument("--linea", type=int, default=None)
    args = ap.parse_args()

    out = Path(args.salida)
    encabezado, limpias = cargar(out / "limpio.csv")
    ancho = len(encabezado)
    vocab = [set(f[i] for f in limpias) for i in range(ancho)]
    tecl = {i for i in range(ancho) if tecleable(vocab[i])}
    cerradas = {i for i in range(ancho) if i not in tecl}
    print(f"Corpus: {len(limpias)} filas | {ancho} columnas | "
          f"{len(tecl)} tecleables, {len(cerradas)} de dominio cerrado\n")

    with open(out / "cuarentena.csv", encoding=ENC, newline="") as f:
        cuar = {int(d["linea_origen"]): d for d in csv.DictReader(f)}

    ruta_dec = out / "decisiones.csv"
    with open(ruta_dec, encoding=ENC, newline="") as f:
        dec = list(csv.DictReader(f))

    objetivo = ([args.linea] if args.linea
                else [int(d["linea_origen"]) for d in dec
                      if not d["k_elegido"].strip()])
    if not objetivo:
        print("No hay filas pendientes.")
        return
    print(f"Pendientes: {len(objetivo)}  ->  {objetivo}\n")

    # agrupar duplicados: las filas de un mismo documento son la misma fila
    grupos = defaultdict(list)
    for o in objetivo:
        grupos[cuar[o]["linea_cruda"]].append(o)
    print(f"Casos unicos: {len(grupos)}\n")

    resueltas = {}
    for n_caso, (cruda, origenes) in enumerate(
            sorted(grupos.items(), key=lambda t: t[1][0]), 1):
        campos = cruda.split(SEP)
        extra = len(campos) - ancho
        print("=" * 72)
        print(f"CASO {n_caso}/{len(grupos)}  ->  L{', L'.join(map(str, origenes))}")
        print(f"{len(campos)} campos, sobran {extra}")
        print("=" * 72)

        # separadores candidatos a falsos: solo los pegados a columnas tecleables
        pos = [i for i in range(len(campos) - 1)
               if any(j in tecl for j in (i, i + 1))]
        n_combos = 1
        for a in range(extra):
            n_combos = n_combos * (len(pos) - a) // (a + 1)
        if n_combos > MAX_COMBOS:
            print(f"  [!] {n_combos:,} combinaciones. Demasiadas. Revisar a mano:")
            print(f"      {cruda[:200]!r}")
            continue

        cands = []
        for falsos in combinations(pos, extra):
            prop = reconstruir(campos, set(falsos))
            if len(prop) != ancho:
                continue
            # columnas tocadas por una fusion
            tocados, off = set(), 0
            for i in range(len(campos) - 1):
                if i in falsos:
                    tocados.add(i - off)
                    off += 1
            if tocados & cerradas:      # un desplegable no puede tener '|'
                continue
            if not all(prop[m] in vocab[m] for m in cerradas):
                continue
            cands.append((puntuar(prop, tocados, vocab, ancho),
                          tuple(sorted(tocados)), prop))

        if not cands:
            print("  [X] Ninguna lectura valida ni con inyecciones separadas.")
            print(f"      Linea cruda: {cruda[:200]!r}")
            continue

        # colapsar las que dan la misma fila tras quitar los pipes
        porfirma = {}
        for score, cols_, prop in cands:
            f_ = tuple(limpio(v) for v in prop)
            if f_ not in porfirma or score > porfirma[f_][0]:
                porfirma[f_] = (score, cols_, prop)
        ops = sorted(porfirma.values(), reverse=True, key=lambda t: t[0])

        letras = "ABCDEFGH"
        for idx, (score, cols_, prop) in enumerate(ops[:6]):
            nom = ", ".join(f"{c} ({encabezado[c].strip()})" for c in cols_)
            rec = "  <-- RECOMENDADA" if idx == 0 else ""
            tipo = "1 campo" if len(cols_) == 1 else f"{len(cols_)} campos SEPARADOS"
            print(f"\n  {letras[idx]}) pipes en {tipo}: {nom} | puntaje {score:+d}{rec}")
            for c in cols_:
                lo, hi = max(0, c - 1), min(ancho, c + 3)
                for j in range(lo, hi):
                    m = " <<<" if j in cols_ else ""
                    print(f"        [{j:>3}] {encabezado[j].strip():<30} = {prop[j]!r}{m}")

        if len(ops) == 1:
            print("\n  [AUTO] Unica lectura posible.")
            elec = 0
        else:
            r = input(f"\n  Elige [{letras[0]}]/"
                      f"{'/'.join(letras[1:len(ops[:6])])}/s=saltar: ").strip().upper()
            if r == "S":
                print()
                continue
            elec = letras.index(r) if r in letras[:len(ops[:6])] else 0

        cols_ = ops[elec][1]
        if len(cols_) > 1:
            print(f"  [!] Pipes en columnas separadas {cols_}: decisiones.csv solo "
                  f"guarda un k.\n      Anotalo y aplicalo a mano, o usa "
                  f"--linea para revisarlo despues.")
        resueltas[tuple(origenes)] = cols_
        print()

    # ---------- actualizar decisiones.csv (solo las de un punto) ----------
    unico = {}
    for origenes, cols_ in resueltas.items():
        if len(cols_) == 1:
            for o in origenes:
                unico[o] = cols_[0]

    if unico:
        for d in dec:
            o = int(d["linea_origen"])
            if o in unico:
                d["k_elegido"] = str(unico[o])
                d["estado"] = "ELEGIDA_MULTI"
        with open(ruta_dec, "w", encoding=ENC, newline="") as f:
            w = csv.DictWriter(f, fieldnames=["linea_origen", "num_campos",
                                              "k_elegido", "estado"],
                               quoting=csv.QUOTE_ALL)
            w.writeheader()
            w.writerows(dec)
        print("=" * 72)
        print(f"[OK] {len(unico)} filas actualizadas en {ruta_dec}")

    multi = {o: c for os, c in resueltas.items() if len(c) > 1 for o in os}
    if multi:
        print(f"[!] {len(multi)} filas con pipes en columnas separadas:")
        for o, c in multi.items():
            print(f"    L{o}: columnas {c}")
        print("    Esas no caben en el formato de decisiones.csv (un solo k).")
        print("    Quedan en cuarentena. No se pierden.")


if __name__ == "__main__":
    main()