"""
Inventario y muestreo estratificado del corpus de pólizas.

Uso (lee el directorio en el lugar, no modifica ni copia nada salvo con --copy):

    python -m pdfextract.qa.manifest --corpus-dir "D:\\OGOS\\DESARROLLOS\\POLIZAS\\RIESGOS VIGENTES"

Genera en --out-dir (por defecto ./qa_corpus):
    manifest.csv         Inventario completo (una fila por PDF).
    sample_manifest.csv  Muestra elegida, con columna split (dev/holdout).
Con --copy copia además los PDFs de la muestra a qa_corpus/<aseguradora>/.

La aseguradora se toma de la primera subcarpeta bajo --corpus-dir.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import shutil
import sys
from dataclasses import asdict, dataclass, fields
from pathlib import Path
from typing import Dict, List

MIN_NATIVE_CHARS = 50
PAGES_PROBED = 8


@dataclass
class PdfRecord:
    insurer: str
    rel_path: str
    size_kb: int
    sha1: str
    pages: int = 0
    native_ratio: float = 0.0
    table_pages_est: int = 0
    table_density: float = 0.0
    kind: str = "unknown"  # native | scanned | mixed | error
    error: str = ""
    selected: bool = False
    split: str = ""


def _sha1(path: Path) -> str:
    h = hashlib.sha1()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _probe_indices(n_pages: int, k: int = PAGES_PROBED) -> List[int]:
    """Índices de página repartidos uniformemente (máximo k)."""
    if n_pages <= k:
        return list(range(n_pages))
    step = n_pages / k
    return sorted({int(i * step) for i in range(k)})


def inspect_pdf(path: Path, scan_tables: bool) -> Dict[str, object]:
    from pypdf import PdfReader

    out: Dict[str, object] = {}
    reader = PdfReader(str(path))
    n = len(reader.pages)
    out["pages"] = n
    idx = _probe_indices(n)

    native = 0
    for i in idx:
        try:
            txt = reader.pages[i].extract_text() or ""
        except Exception:
            txt = ""
        if len(txt.strip()) >= MIN_NATIVE_CHARS:
            native += 1
    ratio = native / len(idx) if idx else 0.0
    out["native_ratio"] = round(ratio, 2)
    out["kind"] = "native" if ratio >= 0.9 else ("scanned" if ratio <= 0.1 else "mixed")

    if scan_tables and ratio > 0:
        import pdfplumber

        hits = 0
        with pdfplumber.open(str(path)) as pdf:
            for i in idx:
                try:
                    if pdf.pages[i].find_tables():
                        hits += 1
                except Exception:
                    continue
        out["table_pages_est"] = round(hits / len(idx) * n)
        out["table_density"] = round(hits / len(idx), 2)
    return out


def build_inventory(corpus: Path, scan_tables: bool) -> List[PdfRecord]:
    from tqdm import tqdm

    pdfs = sorted(p for p in corpus.rglob("*") if p.is_file() and p.suffix.lower() == ".pdf")
    records: List[PdfRecord] = []
    for p in tqdm(pdfs, desc="Inventariando", unit="pdf"):
        rel = p.relative_to(corpus)
        insurer = rel.parts[0] if len(rel.parts) > 1 else "SIN_ASEGURADORA"
        rec = PdfRecord(
            insurer=insurer,
            rel_path=str(rel),
            size_kb=p.stat().st_size // 1024,
            sha1=_sha1(p),
        )
        try:
            for k, v in inspect_pdf(p, scan_tables).items():
                setattr(rec, k, v)
        except Exception as exc:  # PDF corrupto o protegido
            rec.kind = "error"
            rec.error = f"{type(exc).__name__}: {exc}"[:200]
        records.append(rec)
    return records


def select_sample(records: List[PdfRecord], per_insurer: int, holdout_ratio: float) -> None:
    """Marca registros como muestra, priorizando tablas y variedad (native/scanned)."""
    by_insurer: Dict[str, List[PdfRecord]] = {}
    seen_hashes = set()
    for r in records:
        if r.kind == "error" or r.sha1 in seen_hashes:  # descarta corruptos y duplicados exactos
            continue
        seen_hashes.add(r.sha1)
        by_insurer.setdefault(r.insurer, []).append(r)

    for recs in by_insurer.values():
        recs.sort(key=lambda r: (-r.table_density, -r.pages))
        chosen: List[PdfRecord] = []
        if recs:
            chosen.append(recs[0])  # el más rico en tablas
        # variedad: otro tipo (scanned/mixed) si existe
        for r in recs:
            if len(chosen) >= per_insurer:
                break
            if r not in chosen and all(r.kind != c.kind for c in chosen):
                chosen.append(r)
        # completar con los restantes repartidos por todo el ranking
        rest = [r for r in recs if r not in chosen]
        while rest and len(chosen) < per_insurer:
            chosen.append(rest.pop(len(rest) // 2))

        # holdout determinista por hash; al menos 1 si hay >= 3 elegidos
        ordered = sorted(chosen, key=lambda r: r.sha1)
        n_hold = max(1, round(len(ordered) * holdout_ratio)) if len(ordered) >= 3 else 0
        for i, r in enumerate(ordered):
            r.selected = True
            r.split = "holdout" if i < n_hold else "dev"


def write_csv(path: Path, records: List[PdfRecord]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=[x.name for x in fields(PdfRecord)])
        w.writeheader()
        for r in records:
            w.writerow(asdict(r))


def main(argv: List[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Inventario y muestreo del corpus de pólizas")
    ap.add_argument("--corpus-dir", required=True, type=Path)
    ap.add_argument("--out-dir", type=Path, default=Path("qa_corpus"))
    ap.add_argument("--per-insurer", type=int, default=3)
    ap.add_argument("--holdout-ratio", type=float, default=0.3)
    ap.add_argument("--no-table-scan", action="store_true", help="Omite la detección de tablas (más rápido)")
    ap.add_argument("--copy", action="store_true", help="Copia los PDFs de la muestra a out-dir")
    args = ap.parse_args(argv)

    if not args.corpus_dir.is_dir():
        print(f"No existe el directorio: {args.corpus_dir}", file=sys.stderr)
        return 2

    records = build_inventory(args.corpus_dir, scan_tables=not args.no_table_scan)
    select_sample(records, args.per_insurer, args.holdout_ratio)
    sample = [r for r in records if r.selected]

    write_csv(args.out_dir / "manifest.csv", records)
    write_csv(args.out_dir / "sample_manifest.csv", sample)

    if args.copy:
        for r in sample:
            dst = args.out_dir / r.insurer / Path(r.rel_path).name
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(args.corpus_dir / r.rel_path, dst)

    insurers = {r.insurer for r in records}
    print(f"\nPDFs encontrados : {len(records)}  | aseguradoras: {len(insurers)}")
    print(f"Muestra elegida  : {len(sample)} (holdout: {sum(r.split == 'holdout' for r in sample)})")
    print(f"Con error        : {sum(r.kind == 'error' for r in records)}")
    print(f"Resultados en    : {args.out_dir.resolve()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
