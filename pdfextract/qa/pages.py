"""
Selector de páginas para QA: recorta cada PDF de la muestra a un máximo de N páginas
representativas (priorizando páginas con tablas y números) y registra el mapa
página-recortada -> página-original.

Uso:
    python -m pdfextract.qa.pages --manifest qa_corpus/sample_manifest.csv ^
        --corpus qa_corpus --out-dir qa_pages --max-pages 10

Genera:
    qa_pages/<aseguradora>/<sha8>.pdf   PDF recortado (deterministico)
    qa_pages/pages_manifest.csv         sha8, aseguradora, origen, kind, split, páginas elegidas
"""

from __future__ import annotations

import argparse
import csv
import math
import re
import sys
from pathlib import Path
from typing import Dict, List

_SLUG_RE = re.compile(r"[^A-Za-z0-9]+")
MAX_CANDIDATES = 60  # páginas a puntuar en PDFs largos


def slug(text: str) -> str:
    return _SLUG_RE.sub("_", text).strip("_")[:40]


def _page_scores(pdf_path: Path, candidates: List[int]) -> Dict[int, float]:
    """Puntúa páginas (0-index) por tablas detectadas y densidad numérica. 0 si no hay texto."""
    import pdfplumber

    scores: Dict[int, float] = {}
    with pdfplumber.open(str(pdf_path)) as pdf:
        for i in candidates:
            try:
                page = pdf.pages[i]
                text = page.extract_text() or ""
                if len(text.strip()) < 50:
                    scores[i] = 0.0
                    continue
                n_tables = len(page.find_tables())
                digits = sum(ch.isdigit() for ch in text) / max(len(text), 1)
                scores[i] = n_tables * 10 + digits * 20
            except Exception:
                scores[i] = 0.0
    return scores


def select_pages(pdf_path: Path, n_pages: int, max_pages: int) -> List[int]:
    """Devuelve índices (0-index, ordenados) de hasta max_pages páginas."""
    if n_pages <= max_pages:
        return list(range(n_pages))

    step = max(1, math.ceil(n_pages / MAX_CANDIDATES))
    candidates = list(range(0, n_pages, step))
    scores = _page_scores(pdf_path, candidates)

    n_top = math.ceil(max_pages * 0.7)
    top = [i for i, s in sorted(scores.items(), key=lambda kv: (-kv[1], kv[0])) if s > 0][:n_top]
    chosen = set(top)

    # completar con páginas repartidas uniformemente (cubre escaneados, sin texto)
    spread = [int(k * n_pages / max_pages) for k in range(max_pages)]
    for i in spread:
        if len(chosen) >= max_pages:
            break
        chosen.add(i)
    for i in range(n_pages):  # último recurso
        if len(chosen) >= max_pages:
            break
        chosen.add(i)
    return sorted(chosen)


def main(argv: List[str] | None = None) -> int:
    from pypdf import PdfReader, PdfWriter

    ap = argparse.ArgumentParser(description="Recorta los PDFs de la muestra a páginas representativas")
    ap.add_argument("--manifest", type=Path, default=Path("qa_corpus/sample_manifest.csv"))
    ap.add_argument("--corpus", type=Path, default=Path("qa_corpus"), help="Carpeta con los PDFs copiados")
    ap.add_argument("--out-dir", type=Path, default=Path("qa_pages"))
    ap.add_argument("--max-pages", type=int, default=10)
    args = ap.parse_args(argv)

    with open(args.manifest, newline="", encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))

    args.out_dir.mkdir(parents=True, exist_ok=True)
    out_rows = []
    for row in rows:
        src = args.corpus / row["insurer"] / Path(row["rel_path"]).name
        if not src.exists():
            print(f"[AVISO] No existe: {src}", file=sys.stderr)
            continue
        sha8 = row["sha1"][:8]
        dst = args.out_dir / slug(row["insurer"]) / f"{sha8}.pdf"
        dst.parent.mkdir(parents=True, exist_ok=True)

        try:
            reader = PdfReader(str(src))
            n = len(reader.pages)
            idx = select_pages(src, n, args.max_pages)
            writer = PdfWriter()
            for i in idx:
                writer.add_page(reader.pages[i])
            with open(dst, "wb") as fh:
                writer.write(fh)
        except Exception as exc:
            print(f"[ERROR] {src.name}: {exc}", file=sys.stderr)
            continue

        out_rows.append({
            "sha8": sha8,
            "insurer": row["insurer"],
            "source": str(src),
            "kind": row["kind"],
            "split": row["split"],
            "total_pages": n,
            "selected_pages": ";".join(str(i + 1) for i in idx),  # 1-index, orden = páginas del recorte
            "trimmed_pdf": str(dst),
        })
        print(f"{sha8}  {row['kind']:8} {n:4d} pág -> {len(idx):2d}  {slug(row['insurer'])}")

    manifest_out = args.out_dir / "pages_manifest.csv"
    with open(manifest_out, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=list(out_rows[0].keys()))
        w.writeheader()
        w.writerows(out_rows)

    total = sum(len(r["selected_pages"].split(";")) for r in out_rows)
    print(f"\nPDFs recortados: {len(out_rows)} | páginas a evaluar: {total} | {manifest_out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
