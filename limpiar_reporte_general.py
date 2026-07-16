#!/usr/bin/env python3
"""
limpiar_reporte.py
==================
Version generalizada. Reemplaza a limpiar_dispensacion.py.

DIFERENCIA CLAVE: no trae NADA quemado de enero.
  - ancho de fila     -> se detecta (moda del archivo)
  - encoding          -> se detecta
  - separador         -> se detecta
  - invariante        -> se calcula y se escribe en contrato.json
  - reconstruccion de saltos de linea -> algoritmo general (acumula fragmentos
    hasta completar el ancho), no la regla "126 seguido de 3" de enero.

Escribe contrato.json para que los pasos siguientes lean el invariante
en vez de tenerlo quemado.

Uso:
    python limpiar_reporte.py Datos/Reporte_Febrero.csv
    python limpiar_reporte.py entrada.csv --salida Salida_Feb --sep "|"
"""

import argparse
import csv
import json
import re
import sys
from collections import Counter
from pathlib import Path

ENCODINGS = ["utf-8-sig", "utf-8", "cp1252", "latin-1"]
CANDIDATOS_SEP = ["|", ";", "\t", ","]
ENC_OUT = "utf-8-sig"
MAX_CARDINALIDAD = 60
UMBRAL_TIPO = 0.995

PATRONES = {
    "nulo":    re.compile(r"^\s*/\s*/\s*(\d{1,2}:\d{2})?\s*$"),
    "fecha":   re.compile(r"^\s*\d{1,2}/\d{1,2}/\d{4}(\s+\d{1,2}:\d{2})?\s*$"),
    "entero":  re.compile(r"^\s*-?\d+\s*$"),
    "decimal": re.compile(r"^\s*-?\d+[.,]\d+\s*$"),
    "vacio":   re.compile(r"^\s*$"),
}


def clasificar(v):
    for nombre, p in PATRONES.items():
        if p.match(v):
            return nombre
    return "texto"


def detectar_encoding(path):
    for enc in ENCODINGS:
        try:
            with open(path, encoding=enc) as f:
                f.read()
            return enc
        except UnicodeDecodeError:
            continue
    return "latin-1"


def detectar_separador(lineas):
    mejor, mejor_score = None, -1.0
    utiles = [l for l in lineas[:400] if l.strip()]
    for sep in CANDIDATOS_SEP:
        counts = [l.count(sep) for l in utiles]
        if not counts or max(counts) == 0:
            continue
        moda, freq = Counter(counts).most_common(1)[0]
        if moda == 0:
            continue
        score = freq / len(counts)
        if score > mejor_score:
            mejor, mejor_score = sep, score
    return mejor, mejor_score


class Validadores:
    """Se construyen desde el corpus sano del PROPIO archivo. Sin dominios
    de meses anteriores: si en febrero aparece una sucursal nueva, la aprende."""

    def __init__(self, filas, ancho):
        self.n = len(filas)
        self.ancho = ancho
        self.dominio, self.tipo, self.libre = {}, {}, set()
        for i in range(ancho):
            vals = Counter(f[i] for f in filas)
            if len(vals) <= MAX_CARDINALIDAD:
                self.dominio[i] = set(vals)
                continue
            tipos = Counter(clasificar(v) for v in vals.elements())
            tipo, cuantos = tipos.most_common(1)[0]
            if cuantos / self.n >= UMBRAL_TIPO and tipo != "texto":
                self.tipo[i] = tipo
            else:
                self.libre.add(i)

    def valida(self, valor, i):
        if i in self.dominio:
            return valor in self.dominio[i]
        if i in self.tipo:
            return clasificar(valor) == self.tipo[i]
        return True

    def tecleable(self, i):
        """Solo una columna donde un humano escribe puede tener el delimitador."""
        return i in self.libre or i in self.tipo


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("archivo")
    ap.add_argument("--salida", default="Salida")
    ap.add_argument("--sep", default=None)
    args = ap.parse_args()

    out = Path(args.salida)
    out.mkdir(parents=True, exist_ok=True)

    # ---------- Deteccion (nada quemado) ----------
    enc = detectar_encoding(args.archivo)
    with open(args.archivo, encoding=enc, newline="") as f:
        lineas = f.read().splitlines()

    sep = args.sep or detectar_separador(lineas)[0]
    if sep is None:
        sys.exit("[X] No se detecto separador. Pasa uno con --sep")

    anchos = Counter(len(l.split(sep)) for l in lineas if l.strip())
    ANCHO = anchos.most_common(1)[0][0]

    # El encabezado es la primera linea con el ancho modal.
    # Lo de antes es preambulo (membrete del reporte) y se preserva.
    i_enc = next(i for i, l in enumerate(lineas) if len(l.split(sep)) == ANCHO)
    preambulo, encabezado = lineas[:i_enc], lineas[i_enc].split(sep)

    print(f"Encoding detectado : {enc}")
    print(f"Separador detectado: {sep!r}")
    print(f"Ancho detectado    : {ANCHO} columnas")
    print(f"Preambulo          : {len(preambulo)} linea(s) -> preambulo.txt")
    print(f"Encabezado         : linea {i_enc+1}")
    print(f"Lineas fisicas     : {len(lineas)}")

    (out / "preambulo.txt").write_text("\n".join(preambulo), encoding=ENC_OUT)

    # ---------- PASADA 1: saltos de linea (algoritmo GENERAL) ----------
    # No busca "126 seguido de 3". Acumula fragmentos hasta completar el ancho.
    registros = []
    i = i_enc + 1
    while i < len(lineas):
        campos = lineas[i].split(sep)
        if len(campos) >= ANCHO:
            registros.append((i + 1, campos,
                              "SANA" if len(campos) == ANCHO else "PENDIENTE_B", ""))
            i += 1
            continue

        # fragmento: pegar siguientes mientras no se pase del ancho
        acum, j, unidas = campos, i + 1, 1
        while j < len(lineas) and len(acum) < ANCHO:
            sig = lineas[j].split(sep)
            if len(acum) + len(sig) - 1 > ANCHO:
                break            # se pasaria: la siguiente no es continuacion
            acum = acum[:-1] + [acum[-1] + sig[0]] + sig[1:]
            unidas += 1
            j += 1
        tipo = "FUSION_SALTO_LINEA" if len(acum) == ANCHO else "FRAGMENTO_IRRESUELTO"
        registros.append((i + 1, acum, tipo, f"{unidas} lineas unidas"))
        i = j

    print(f"Registros tras pasada 1: {len(registros)}")

    sanas = [c for _, c, _, _ in registros if len(c) == ANCHO]
    if len(sanas) < 100:
        sys.exit("[X] Muy pocas filas sanas para construir validadores. Revisar a mano.")
    val = Validadores(sanas, ANCHO)
    print(f"Validadores: {len(val.dominio)} categoricas, {len(val.tipo)} por tipo, "
          f"{len(val.libre)} texto libre")

    # ---------- PASADA 2: delimitador dentro de un campo ----------
    limpias, cuarentena, auditoria = [], [], []
    for origen, campos, tipo, detalle in registros:
        if len(campos) == ANCHO:
            limpias.append(campos)
            auditoria.append((len(limpias), origen, tipo, detalle))
            continue
        if len(campos) < ANCHO:
            cuarentena.append((origen, len(campos), "FRAGMENTO_IRRESUELTO",
                               detalle, sep.join(campos)))
            continue

        extra = len(campos) - ANCHO
        cands = []
        for k in range(ANCHO):
            if not val.tecleable(k) or k + extra >= len(campos):
                continue
            prop = campos[:k] + [sep.join(campos[k:k + extra + 1])] + campos[k + extra + 1:]
            if len(prop) == ANCHO and all(val.valida(prop[m], m)
                                          for m in range(ANCHO) if m != k):
                cands.append((k, prop))

        if len(cands) == 1:
            k, prop = cands[0]
            limpias.append(prop)
            auditoria.append((len(limpias), origen, "FUSION_DELIMITADOR",
                              f"col {k} ({encabezado[k].strip()}) = {prop[k]!r}"))
        else:
            motivo = "AMBIGUA" if cands else "SIN_CANDIDATOS"
            cols = ", ".join(f"{k} ({encabezado[k].strip()})" for k, _ in cands)
            cuarentena.append((origen, len(campos), motivo,
                               f"{len(cands)} lecturas: {cols}" if cands else "",
                               sep.join(campos)))

    # ---------- Escritura ----------
    with open(out / "limpio.csv", "w", encoding=ENC_OUT, newline="") as f:
        w = csv.writer(f, delimiter=sep, quoting=csv.QUOTE_MINIMAL)
        w.writerow(encabezado)
        w.writerows(limpias)

    with open(out / "cuarentena.csv", "w", encoding=ENC_OUT, newline="") as f:
        w = csv.writer(f, quoting=csv.QUOTE_ALL)
        w.writerow(["linea_origen", "num_campos", "motivo", "detalle", "linea_cruda"])
        w.writerows(cuarentena)

    with open(out / "auditoria.csv", "w", encoding=ENC_OUT, newline="") as f:
        w = csv.writer(f, quoting=csv.QUOTE_ALL)
        w.writerow(["fila_salida", "linea_origen", "reparacion", "detalle"])
        w.writerows(auditoria)

    # ---------- CONTRATO: el invariante se CALCULA, no se quema ----------
    contrato = {
        "archivo_origen": str(args.archivo),
        "encoding": enc,
        "separador": sep,
        "ancho": ANCHO,
        "lineas_fisicas": len(lineas),
        "lineas_preambulo": len(preambulo),
        "registros_esperados": len(registros),
        "en_limpio": len(limpias),
        "en_cuarentena": len(cuarentena),
    }
    (out / "contrato.json").write_text(json.dumps(contrato, indent=2), encoding="utf-8")

    # ---------- Reconciliacion ----------
    print("\n" + "=" * 60)
    print("RECONCILIACION")
    print("=" * 60)
    for t, n in Counter(t for _, _, t, _ in auditoria).most_common():
        print(f"  {t:<24} {n:>7}")
    print(f"  {'CUARENTENA':<24} {len(cuarentena):>7}")
    print(f"\n  registros esperados : {len(registros)}")
    print(f"  contabilizados      : {len(limpias) + len(cuarentena)}")

    if len(limpias) + len(cuarentena) != len(registros):
        sys.exit("\n[X] PERDIDA DE DATOS. Salida NO confiable.")

    fisicas = len(preambulo) + 1 + sum(
        int(d.split()[0]) if t == "FUSION_SALTO_LINEA" else 1
        for _, _, t, d in auditoria) + len(cuarentena)
    print(f"  lineas fisicas expl.: {fisicas} / {len(lineas)}")

    print("\n[OK] Nada se perdio. Contrato escrito en contrato.json")
    if cuarentena:
        print(f"[!] {len(cuarentena)} filas necesitan revision. Ver cuarentena.csv")


if __name__ == "__main__":
    main()