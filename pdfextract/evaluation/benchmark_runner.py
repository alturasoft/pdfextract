"""
Ejecutor de Benchmarking y Comparación Estructural.
Compara Ground Truth vs Docling vs PaddleOCR-VL vs Postprocessed
y genera reportes comparativos con métricas CER, WER, GriTS, TEDS y TEDS-S.
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from pdfextract.core.logger import get_logger
from pdfextract.core.models import DocumentModel, Table
from pdfextract.evaluation.grits_evaluator import compute_grits
from pdfextract.evaluation.teds_evaluator import compute_teds
from pdfextract.evaluation.text_metrics import compute_cer, compute_wer
from pdfextract.postprocess.table_postprocessor import PostprocessingResult

logger = get_logger("BenchmarkRunner")


@dataclass
class EngineBenchmarkMetrics:
    engine_name: str
    cer: Optional[float] = None
    wer: Optional[float] = None
    grits: Optional[float] = None
    teds: Optional[float] = None
    teds_s: Optional[float] = None
    tables_detected: int = 0
    processing_time_seconds: float = 0.0
    memory_mb: float = 0.0


@dataclass
class BenchmarkReport:
    document_name: str
    docling_metrics: Optional[EngineBenchmarkMetrics] = None
    paddle_metrics: Optional[EngineBenchmarkMetrics] = None
    postprocessed_metrics: Optional[EngineBenchmarkMetrics] = None
    tables_requiring_correction: int = 0
    tables_corrected: int = 0
    tables_unchanged: int = 0
    tables_rejected: int = 0
    details: Dict[str, Any] = field(default_factory=dict)

    def format_text_report(self) -> str:
        """Formatea el reporte comparativo para terminal según la especificación."""
        doc = self.docling_metrics
        pad = self.paddle_metrics
        fin = self.postprocessed_metrics

        def fmt_val(v: Optional[float], is_pct: bool = False) -> str:
            if v is None:
                return "N/A".rjust(10)
            if is_pct:
                return f"{v * 100:.2f}%".rjust(10)
            return f"{v:.4f}".rjust(10)

        lines = [
            f"DOCUMENTO: {self.document_name}",
            "",
            f"{'':20} {'DOCLING':>10} {'PADDLE':>10} {'FINAL':>10}",
            "-" * 55,
            f"Texto CER            {fmt_val(doc.cer if doc else None, is_pct=True)} {fmt_val(pad.cer if pad else None, is_pct=True)} {fmt_val(fin.cer if fin else None, is_pct=True)}",
            f"Texto WER            {fmt_val(doc.wer if doc else None, is_pct=True)} {fmt_val(pad.wer if pad else None, is_pct=True)} {fmt_val(fin.wer if fin else None, is_pct=True)}",
            "",
            f"GriTS                {fmt_val(doc.grits if doc else None)} {fmt_val(pad.grits if pad else None)} {fmt_val(fin.grits if fin else None)}",
            f"TEDS                 {fmt_val(doc.teds if doc else None)} {fmt_val(pad.teds if pad else None)} {fmt_val(fin.teds if fin else None)}",
            f"TEDS-S               {fmt_val(doc.teds_s if doc else None)} {fmt_val(pad.teds_s if pad else None)} {fmt_val(fin.teds_s if fin else None)}",
            "",
            f"Tablas detectadas    {str(doc.tables_detected if doc else 0):>10} {str(pad.tables_detected if pad else 0):>10} {str(fin.tables_detected if fin else 0):>10}",
            f"Tablas corregidas    {'N/A':>10} {'N/A':>10} {str(self.tables_corrected):>10}",
            f"Tablas conservadas   {'N/A':>10} {'N/A':>10} {str(self.tables_unchanged):>10}",
            "",
            f"Tiempo (s)           {fmt_val(doc.processing_time_seconds if doc else None)} {fmt_val(pad.processing_time_seconds if pad else None)} {fmt_val(fin.processing_time_seconds if fin else None)}",
            "-" * 55,
            f"Tables requiring correction: {self.tables_requiring_correction}",
            f"Tables corrected:            {self.tables_corrected}",
            f"Tables unchanged:            {self.tables_unchanged}",
            f"Tables rejected:             {self.tables_rejected}",
            "-" * 55,
        ]
        return "\n".join(lines)


class BenchmarkRunner:
    """
    Coordina la evaluación formal entre los diferentes modelos y opcionalmente el Ground Truth.
    """

    def evaluate(
        self,
        document_name: str,
        docling_doc: Optional[DocumentModel] = None,
        paddle_doc: Optional[DocumentModel] = None,
        postprocessed_res: Optional[PostprocessingResult] = None,
        ground_truth_doc: Optional[DocumentModel] = None,
        docling_time: float = 0.0,
        paddle_time: float = 0.0,
        postprocess_time: float = 0.0,
    ) -> BenchmarkReport:
        """
        Calcula las métricas comparativas y retorna el BenchmarkReport.
        """
        gt_text = ""
        if ground_truth_doc:
            gt_text = " ".join(t.text for t in ground_truth_doc.texts if t.text)

        def eval_engine(
            doc: Optional[DocumentModel],
            name: str,
            time_sec: float,
        ) -> Optional[EngineBenchmarkMetrics]:
            if not doc:
                return None

            cer_val = None
            wer_val = None
            if gt_text:
                hyp_text = " ".join(t.text for t in doc.texts if t.text)
                cer_val = compute_cer(gt_text, hyp_text)
                wer_val = compute_wer(gt_text, hyp_text)

            grits_vals = []
            teds_vals = []
            tedss_vals = []

            # Si hay ground truth con tablas
            if ground_truth_doc and ground_truth_doc.tables:
                for gt_tbl in ground_truth_doc.tables:
                    # Encontrar tabla homóloga en doc
                    best_tbl = None
                    for t in doc.tables:
                        if t.page_start == gt_tbl.page_start:
                            best_tbl = t
                            break
                    if best_tbl:
                        g_res = compute_grits(gt_tbl, best_tbl)
                        grits_vals.append(g_res.grits_overall)
                        teds_vals.append(compute_teds(gt_tbl, best_tbl, ignore_text=False))
                        tedss_vals.append(compute_teds(gt_tbl, best_tbl, ignore_text=True))
                    else:
                        grits_vals.append(0.0)
                        teds_vals.append(0.0)
                        tedss_vals.append(0.0)

            avg_grits = sum(grits_vals) / len(grits_vals) if grits_vals else None
            avg_teds = sum(teds_vals) / len(teds_vals) if teds_vals else None
            avg_tedss = sum(tedss_vals) / len(tedss_vals) if tedss_vals else None

            return EngineBenchmarkMetrics(
                engine_name=name,
                cer=cer_val,
                wer=wer_val,
                grits=avg_grits,
                teds=avg_teds,
                teds_s=avg_tedss,
                tables_detected=len(doc.tables),
                processing_time_seconds=time_sec,
            )

        doc_m = eval_engine(docling_doc, "docling", docling_time)
        pad_m = eval_engine(paddle_doc, "paddleocr", paddle_time)
        fin_doc = postprocessed_res.document if postprocessed_res else None
        fin_m = eval_engine(fin_doc, "postprocessed", postprocess_time)

        req_corr = 0
        corr = 0
        unchanged = 0
        rejected = 0

        if postprocessed_res:
            req_corr = postprocessed_res.tables_corrected + postprocessed_res.tables_rejected
            corr = postprocessed_res.tables_corrected
            unchanged = postprocessed_res.tables_unchanged
            rejected = postprocessed_res.tables_rejected

        report = BenchmarkReport(
            document_name=document_name,
            docling_metrics=doc_m,
            paddle_metrics=pad_m,
            postprocessed_metrics=fin_m,
            tables_requiring_correction=req_corr,
            tables_corrected=corr,
            tables_unchanged=unchanged,
            tables_rejected=rejected,
        )

        return report
