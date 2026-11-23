"""
Juez de visión: compara las imágenes de las páginas del PDF contra el Markdown extraído.
No requiere ground truth. Usa dos jueces de OpenAI (mini y fuerte) para redundancia.

Uso:
    python -m pdfextract.qa.judge --run qa_runs/baseline --dry-run
    python -m pdfextract.qa.judge --run qa_runs/baseline --max-cost 8

Los resultados se cachean en <run>/judge/<modelo>/<sha8>.json (se puede reanudar).
La clave se lee de OPENAI_API_KEY (entorno o archivo .env).
"""

from __future__ import annotations

import argparse
import base64
import csv
import io
import json
import os
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import httpx

API_URL = "https://api.openai.com/v1/chat/completions"
JUDGES = ["gpt-4.1-mini", "gpt-4.1"]
# Tarifas orientativas USD por 1M de tokens (entrada, salida). VERIFICAR contra la tarifa vigente.
PRICES = {"gpt-4.1-mini": (0.40, 1.60), "gpt-4.1": (2.00, 8.00)}
EST_TOKENS_PER_IMAGE = 1800
MAX_MD_CHARS = 60_000
DISAGREE_THRESHOLD = 0.15

ISSUE_TYPES = [
    "missing_content", "wrong_value", "label_value_mismatch", "table_structure",
    "merged_cells_error", "reading_order", "hallucinated_content", "noise", "other",
]

SCHEMA = {
    "name": "extraction_audit",
    "strict": True,
    "schema": {
        "type": "object",
        "additionalProperties": False,
        "required": ["pages", "summary"],
        "properties": {
            "summary": {"type": "string"},
            "pages": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["page", "items_total", "items_correct", "fidelity_score", "issues"],
                    "properties": {
                        "page": {"type": "integer"},
                        "items_total": {"type": "integer"},
                        "items_correct": {"type": "integer"},
                        "fidelity_score": {"type": "number"},
                        "issues": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "additionalProperties": False,
                                "required": ["type", "severity", "description", "expected", "found"],
                                "properties": {
                                    "type": {"type": "string", "enum": ISSUE_TYPES},
                                    "severity": {"type": "string", "enum": ["low", "medium", "high"]},
                                    "description": {"type": "string"},
                                    "expected": {"type": "string"},
                                    "found": {"type": "string"},
                                },
                            },
                        },
                    },
                },
            },
        },
    },
}

SYSTEM_PROMPT = """Eres un auditor de calidad de extracción documental para pólizas de seguros.
Recibes las imágenes de las páginas de un PDF (en orden, página 1..N) y el Markdown (GFM) que un
sistema automático extrajo de ese PDF. Tu tarea es medir la FIDELIDAD de la extracción respecto de
las imágenes, que son la verdad. El Markdown alimenta una base vectorial: un dato mal asignado es
peor que un dato faltante.

Revisa por página:
- missing_content: texto, filas, columnas o importes visibles que no están en el Markdown.
- wrong_value: números, fechas, nombres o códigos distintos a los de la imagen.
- label_value_mismatch: una etiqueta (p. ej. "Ramo:", "Moneda:") asociada al valor equivocado,
  o etiquetas separadas de su valor en formularios de pares etiqueta-valor.
- table_structure: tabla de la imagen no representada como tabla, columnas/filas desalineadas,
  encabezados mal ubicados, celdas desplazadas.
- merged_cells_error: celdas combinadas mal aplanadas (el valor debe repetirse en cada celda cubierta).
- reading_order: orden de lectura que cambia el significado.
- hallucinated_content: contenido que no existe en la imagen.
- noise: encabezados/pies/marcas repetidas que ensucian el contenido (solo si es relevante).
- other.

Reglas:
- Ignora diferencias puramente cosméticas (negritas, espacios, saltos de línea, escapes de |).
- Si el documento está escaneado, tolera diferencias mínimas de OCR no relevantes (tildes) como low.
- Sé específico: en expected pon lo que ve en la imagen y en found lo que hay en el Markdown.
- items_total / items_correct (por página): cuenta los elementos de información discretos visibles
  (cada par etiqueta-valor, cada celda con contenido de tabla, cada párrafo corto) y cuántos de ellos
  están correctos y bien asignados en el Markdown. Un párrafo largo cuenta como 1 elemento.
- fidelity_score = items_correct / items_total (redondeado a 2 decimales).
- Reporta CADA problema raíz UNA sola vez: no dupliques el mismo error con dos tipos distintos
  (p. ej. un valor asignado a la etiqueta equivocada es solo label_value_mismatch, no también
  missing_content). Si varios pares están desplazados en cascada, puedes agruparlos en un issue
  que liste los pares afectados.
- No inventes issues. Si una página está bien, issues=[] y score cercano a 1.0.
- Devuelve una entrada por cada página recibida."""


def load_env() -> None:
    env = Path(".env")
    if env.exists():
        for line in env.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def render_pages(pdf_path: Path, max_side: int = 1500) -> List[str]:
    """Renderiza cada página a JPEG base64 (data URL)."""
    import pypdfium2 as pdfium

    doc = pdfium.PdfDocument(str(pdf_path))
    out = []
    for i in range(len(doc)):
        page = doc[i]
        w, h = page.get_size()
        scale = min(2.0, max_side / max(w, h))
        img = page.render(scale=scale).to_pil().convert("RGB")
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=82)
        out.append("data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode())
    return out


def find_md(run_dir: Path, sha8: str) -> Optional[Path]:
    hits = list(run_dir.glob(f"{sha8}*/docling/*.md"))
    return hits[0] if hits else None


def cost_usd(model: str, usage: Dict[str, int]) -> float:
    pin, pout = PRICES[model]
    return usage.get("prompt_tokens", 0) / 1e6 * pin + usage.get("completion_tokens", 0) / 1e6 * pout


def call_judge(model: str, images: List[str], md_text: str, api_key: str) -> Tuple[Dict[str, Any], Dict[str, int]]:
    content: List[Dict[str, Any]] = [{
        "type": "text",
        "text": f"El PDF tiene {len(images)} página(s). Las imágenes siguen en orden.\n\n"
                f"=== MARKDOWN EXTRAÍDO ===\n{md_text[:MAX_MD_CHARS]}\n=== FIN ===",
    }]
    for i, url in enumerate(images, 1):
        content.append({"type": "text", "text": f"Página {i}:"})
        content.append({"type": "image_url", "image_url": {"url": url, "detail": "high"}})

    payload = {
        "model": model,
        "temperature": 0,
        "messages": [{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": content}],
        "response_format": {"type": "json_schema", "json_schema": SCHEMA},
    }
    headers = {"Authorization": f"Bearer {api_key}"}
    last_err = ""
    for attempt in range(5):
        try:
            r = httpx.post(API_URL, json=payload, headers=headers, timeout=240)
            if r.status_code == 200:
                data = r.json()
                return json.loads(data["choices"][0]["message"]["content"]), data["usage"]
            last_err = f"HTTP {r.status_code}: {r.text[:300]}"
            if r.status_code not in (408, 409, 429, 500, 502, 503, 504):
                break
        except httpx.HTTPError as exc:
            last_err = f"{type(exc).__name__}: {exc}"
        time.sleep(2 ** attempt * 3)
    raise RuntimeError(last_err)


def main(argv: List[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Juez de visión (OpenAI)")
    ap.add_argument("--run", type=Path, required=True)
    ap.add_argument("--pages-manifest", type=Path, default=Path("qa_pages/pages_manifest.csv"))
    ap.add_argument("--judges", nargs="+", default=JUDGES)
    ap.add_argument("--only", nargs="*", default=None, help="Limitar a estos sha8")
    ap.add_argument("--dry-run", action="store_true", help="Solo estima costo; no llama a la API")
    ap.add_argument("--max-cost", type=float, default=8.0, help="Tope de gasto USD (aprox.)")
    args = ap.parse_args(argv)

    load_env()
    api_key = os.environ.get("OPENAI_API_KEY", "")
    if not api_key and not args.dry_run:
        print("Falta OPENAI_API_KEY (entorno o .env).", file=sys.stderr)
        return 2

    with open(args.pages_manifest, newline="", encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))
    if args.only:
        rows = [r for r in rows if r["sha8"] in set(args.only)]

    todo = []
    for r in rows:
        md = find_md(args.run, r["sha8"])
        if md is not None:
            todo.append((r, md))
    n_pages = sum(len(r["selected_pages"].split(";")) for r, _ in todo)
    est = sum(
        (n_pages * EST_TOKENS_PER_IMAGE) / 1e6 * PRICES[m][0] + len(todo) * 3000 / 1e6 * PRICES[m][1]
        for m in args.judges
    )
    print(f"Documentos con extracción: {len(todo)}/{len(rows)} | páginas: {n_pages} | "
          f"costo estimado ~ ${est:.2f} (aprox.)")
    if args.dry_run:
        return 0

    spent = 0.0
    for r, md in todo:
        sha8 = r["sha8"]
        cached = all((args.run / "judge" / m / f"{sha8}.json").exists() for m in args.judges)
        if cached:
            continue
        images = render_pages(Path(r["trimmed_pdf"]))
        md_text = md.read_text(encoding="utf-8", errors="ignore")
        for model in args.judges:
            out = args.run / "judge" / model / f"{sha8}.json"
            if out.exists():
                continue
            if spent >= args.max_cost:
                print(f"Tope de costo alcanzado (${spent:.2f}). Detenido.", file=sys.stderr)
                return 3
            try:
                result, usage = call_judge(model, images, md_text, api_key)
            except Exception as exc:
                print(f"[ERROR] {sha8} {model}: {exc}", file=sys.stderr)
                continue
            c = cost_usd(model, usage)
            spent += c
            out.parent.mkdir(parents=True, exist_ok=True)
            result["_meta"] = {"sha8": sha8, "model": model, "usage": usage, "cost_usd": round(c, 5)}
            out.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
            scores = [p["fidelity_score"] for p in result["pages"]]
            mean = sum(scores) / len(scores) if scores else 0
            print(f"{sha8} {model:13} score={mean:.2f} issues={sum(len(p['issues']) for p in result['pages']):3d} "
                  f"cost=${c:.3f} total=${spent:.2f}")
    print(f"\nGasto total aproximado: ${spent:.2f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
