"""
Señal A de QA: completitud numérica determinista (sin IA).

Compara los números/importes/fechas del texto NATIVO del PDF recortado con los que
aparecen en el Markdown extraído. Para páginas escaneadas (sin texto nativo) no aplica.

Uso:
    python -m pdfextract.qa.signal_a --run qa_runs/baseline
"""

from __future__ import annotations

import argparse
import csv
import re
import sys
from pathlib import Path
from typing import Dict, List, Optional, Set

NUM_RE = re.compile(r"\d[\d.,/\-]*\d|\d{3,}")
MIN_DIGITS = 3
MIN_NATIVE_CHARS = 50


def digit_tokens(text: str) -> Set[str]:
    """Tokens numéricos normalizados a solo dígitos (tolera cambios de separadores)."""
    out = set()
    for m in NUM_RE.findall(text):
        d = re.sub(r"\D", "", m)
        if len(d) >= MIN_DIGITS:
            out.add(d)
    return out


def native_text(pdf_path: Path) -> Optional[str]:
    """Texto nativo concatenado de las páginas con texto real; None si no hay ninguna."""
    from pypdf import PdfReader

    parts = []
    for page in PdfReader(str(pdf_path)).pages:
        try:
            t = page.extract_text() or ""
        except Exception:
            t = ""
        if len(t.strip()) >= MIN_NATIVE_CHARS:
            parts.append(t)
    return "\n".join(parts) if parts else None


def find_md(run_dir: Path, sha8: str) -> Optional[Path]:
    hits = list(run_dir.glob(f"{sha8}*/docling/*.md"))
    return hits[0] if hits else None


def compute(pdf_path: Path, md_path: Path) -> Dict[str, object]:
    ref = native_text(pdf_path)
    if ref is None:
        return {"applicable": False}
    ref_tokens = digit_tokens(ref)
    md_tokens = digit_tokens(md_path.read_text(encoding="utf-8", errors="ignore"))
    if not ref_tokens:
        return {"applicable": False}
    missing = sorted(
        t for t in ref_tokens
        if t not in md_tokens and not any(t in m for m in md_tokens)
    )
    found = len(ref_tokens) - len(missing)
    return {
        "applicable": True,
        "ref_tokens": len(ref_tokens),
        "found": found,
        "recall": round(found / len(ref_tokens), 4),
        "missing_sample": missing[:15],
    }


def main(argv: List[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Señal A: completitud numérica")
    ap.add_argument("--run", type=Path, required=True, help="Carpeta de la corrida (qa_runs/baseline)")
    ap.add_argument("--pages-manifest", type=Path, default=Path("qa_pages/pages_manifest.csv"))
    ap.add_argument("--out", type=Path, default=None)
    args = ap.parse_args(argv)

    with open(args.pages_manifest, newline="", encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))

    out_path = args.out or (args.run / "signal_a.csv")
    result_rows = []
    for r in rows:
        md = find_md(args.run, r["sha8"])
        base = {"sha8": r["sha8"], "insurer": r["insurer"], "kind": r["kind"], "split": r["split"]}
        if md is None:
            result_rows.append({**base, "status": "sin_extraccion", "applicable": "", "ref_tokens": "",
                                "found": "", "recall": "", "missing_sample": ""})
            continue
        res = compute(Path(r["trimmed_pdf"]), md)
        result_rows.append({
            **base,
            "status": "ok",
            "applicable": res["applicable"],
            "ref_tokens": res.get("ref_tokens", ""),
            "found": res.get("found", ""),
            "recall": res.get("recall", ""),
            "missing_sample": ";".join(res.get("missing_sample", [])),
        })

    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=list(result_rows[0].keys()))
        w.writeheader()
        w.writerows(result_rows)

    ok = [x for x in result_rows if x["status"] == "ok" and x["applicable"] is True]
    if ok:
        tot = sum(x["ref_tokens"] for x in ok)
        fnd = sum(x["found"] for x in ok)
        print(f"Documentos evaluables: {len(ok)} | recall global (ponderado): {fnd / tot:.2%}")
    print(f"Sin extracción aún: {sum(x['status'] == 'sin_extraccion' for x in result_rows)} | {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
