"""
Agregador del reporte de QA: combina Señal A (completitud numérica) y los dos jueces de visión,
segmentando por aseguradora, tipo de PDF (nativo/mixto/escaneado) y split (dev/holdout).

Uso:
    python -m pdfextract.qa.report --run qa_runs/baseline
Genera <run>/qa_report.md y <run>/qa_scores.csv
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Dict, List, Optional

DISAGREE = 0.15


def judge_score(path: Path) -> Optional[Dict[str, Any]]:
    if not path.exists():
        return None
    d = json.loads(path.read_text(encoding="utf-8"))
    tot = sum(p.get("items_total", 0) for p in d["pages"])
    ok = sum(min(p.get("items_correct", 0), p.get("items_total", 0)) for p in d["pages"])
    issues = [i for p in d["pages"] for i in p["issues"]]
    return {
        "score": ok / tot if tot else None,
        "items_total": tot,
        "issues": issues,
        "cost": d.get("_meta", {}).get("cost_usd", 0.0),
    }


def mean(xs: List[float]) -> Optional[float]:
    xs = [x for x in xs if x is not None]
    return sum(xs) / len(xs) if xs else None


def pct(x: Optional[float]) -> str:
    return "n/d" if x is None else f"{x * 100:.1f}%"


def main(argv: List[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Reporte de QA")
    ap.add_argument("--run", type=Path, required=True)
    ap.add_argument("--pages-manifest", type=Path, default=Path("qa_pages/pages_manifest.csv"))
    ap.add_argument("--judges", nargs="+", default=["gpt-4.1-mini", "gpt-4.1"])
    args = ap.parse_args(argv)

    with open(args.pages_manifest, newline="", encoding="utf-8-sig") as f:
        manifest = list(csv.DictReader(f))

    sig_a: Dict[str, Dict[str, str]] = {}
    sa_path = args.run / "signal_a.csv"
    if sa_path.exists():
        with open(sa_path, newline="", encoding="utf-8-sig") as f:
            sig_a = {r["sha8"]: r for r in csv.DictReader(f)}

    rows: List[Dict[str, Any]] = []
    issue_counter: Dict[str, Counter] = {m: Counter() for m in args.judges}
    sev_counter: Counter = Counter()
    total_cost = 0.0
    for m in manifest:
        sha8 = m["sha8"]
        js = {j: judge_score(args.run / "judge" / j / f"{sha8}.json") for j in args.judges}
        scores = [v["score"] for v in js.values() if v and v["score"] is not None]
        for j, v in js.items():
            if v:
                total_cost += v["cost"]
                issue_counter[j].update(i["type"] for i in v["issues"])
        strong = js.get(args.judges[-1])
        if strong:
            sev_counter.update(f'{i["type"]}|{i["severity"]}' for i in strong["issues"])
        sa = sig_a.get(sha8, {})
        recall = float(sa["recall"]) if sa.get("recall") not in (None, "") else None
        disagreement = (max(scores) - min(scores)) if len(scores) == len(args.judges) else None
        rows.append({
            "sha8": sha8, "insurer": m["insurer"], "kind": m["kind"], "split": m["split"],
            "pages": len(m["selected_pages"].split(";")),
            "recall_numeros": recall,
            **{f"score_{j}": (js[j]["score"] if js[j] else None) for j in args.judges},
            "score_consenso": mean(scores),
            "desacuerdo": disagreement,
            "baja_confianza": bool(disagreement is not None and disagreement > DISAGREE),
        })

    with open(args.run / "qa_scores.csv", "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)

    def group(key: str) -> List[str]:
        buckets = defaultdict(list)
        for r in rows:
            buckets[r[key]].append(r)
        out = ["| Segmento | Docs | Páginas | Score IA | Recall números | Baja confianza |", "|---|---|---|---|---|---|"]
        for k, rs in sorted(buckets.items(), key=lambda kv: (mean([r["score_consenso"] for r in kv[1]]) or 9)):
            out.append(
                f"| {k} | {len(rs)} | {sum(r['pages'] for r in rs)} | "
                f"{pct(mean([r['score_consenso'] for r in rs]))} | "
                f"{pct(mean([r['recall_numeros'] for r in rs]))} | "
                f"{sum(r['baja_confianza'] for r in rs)} |"
            )
        return out

    judged = [r for r in rows if r["score_consenso"] is not None]
    lines = [
        "# Reporte de QA de extracción",
        "",
        f"- Documentos evaluados por IA: **{len(judged)}/{len(rows)}**",
        f"- Score IA global (promedio de documentos): **{pct(mean([r['score_consenso'] for r in judged]))}**",
        f"- Recall numérico global (nativos): **{pct(mean([r['recall_numeros'] for r in rows]))}**",
        f"- Documentos de baja confianza (jueces discrepan > {int(DISAGREE * 100)} pp): "
        f"**{sum(r['baja_confianza'] for r in rows)}**",
        f"- Gasto aproximado en API: **${total_cost:.2f}**",
        "",
        "> El *score IA* es la proporción de elementos de información correctamente extraídos y bien "
        "asignados, según el consenso de dos modelos de visión que comparan la imagen del PDF con el "
        "Markdown. Es una estimación de fiabilidad asistida por IA, no una verdad humana.",
        "",
        "## Por tipo de PDF", *group("kind"),
        "", "## Por split", *group("split"),
        "", "## Por aseguradora", *group("insurer"),
        "", "## Tipos de error (juez fuerte)",
        "| Tipo | Severidad | Cantidad |", "|---|---|---|",
    ]
    for key, n in sev_counter.most_common(20):
        t, s = key.split("|")
        lines.append(f"| {t} | {s} | {n} |")
    lines += ["", "## 15 documentos con menor score",
              "| sha8 | Aseguradora | Tipo | Score | Recall |", "|---|---|---|---|---|"]
    for r in sorted(judged, key=lambda r: r["score_consenso"])[:15]:
        lines.append(f"| {r['sha8']} | {r['insurer'][:35]} | {r['kind']} | "
                     f"{pct(r['score_consenso'])} | {pct(r['recall_numeros'])} |")

    report = args.run / "qa_report.md"
    report.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"Reporte: {report}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
