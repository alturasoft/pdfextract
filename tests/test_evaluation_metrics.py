"""
Pruebas unitarias para las métricas de evaluación (CER, WER, GriTS, TEDS, TEDS-S y BenchmarkRunner).
"""

from pdfextract.core.models import BoundingBox, Cell, DocumentMetadata, DocumentModel, Table
from pdfextract.evaluation.benchmark_runner import BenchmarkRunner
from pdfextract.evaluation.grits_evaluator import compute_grits
from pdfextract.evaluation.teds_evaluator import compute_teds, table_to_tree
from pdfextract.evaluation.text_metrics import compute_cer, compute_wer


def _make_simple_table(table_id: str, values: list) -> Table:
    rows = []
    num_rows = len(values)
    num_cols = len(values[0]) if num_rows > 0 else 0
    for r in range(num_rows):
        row = []
        for c in range(num_cols):
            cell = Cell(
                text=str(values[r][c]),
                row_index=r,
                col_index=c,
                is_header=(r == 0),
            )
            row.append(cell)
        rows.append(row)

    headers = [str(v) for v in values[0]] if values else []
    return Table(
        table_id=table_id,
        page_start=1,
        page_end=1,
        num_rows=num_rows,
        num_cols=num_cols,
        headers=headers,
        rows=rows,
    )


def test_cer_and_wer_metrics():
    # Coincidencia idéntica
    assert compute_cer("Seguros de Automóvil", "Seguros de Automóvil") == 0.0
    assert compute_wer("Seguros de Automóvil", "Seguros de Automóvil") == 0.0

    # Texto vacío
    assert compute_cer("", "") == 0.0
    assert compute_wer("", "") == 0.0

    # Diferencias
    assert compute_cer("Auto", "Autos") == 0.25
    assert compute_wer("Seguros de Auto", "Seguros de Vehículo") == 1.0 / 3.0


def test_grits_metric():
    tbl_gt = _make_simple_table("gt", [["Col1", "Col2"], ["A", "B"], ["C", "D"]])
    tbl_pred_exact = _make_simple_table("p1", [["Col1", "Col2"], ["A", "B"], ["C", "D"]])
    tbl_pred_diff = _make_simple_table("p2", [["Col1", "Col2", "Col3"], ["A", "B", "X"]])

    res_exact = compute_grits(tbl_gt, tbl_pred_exact)
    assert res_exact.grits_overall == 1.0
    assert res_exact.grits_top == 1.0
    assert res_exact.grits_cont == 1.0

    res_diff = compute_grits(tbl_gt, tbl_pred_diff)
    assert res_diff.grits_overall < 1.0


def test_teds_and_teds_s_metrics():
    tbl_gt = _make_simple_table("gt", [["Col1", "Col2"], ["100", "200"]])
    tbl_exact = _make_simple_table("ex", [["Col1", "Col2"], ["100", "200"]])
    tbl_text_diff = _make_simple_table("td", [["Col1", "Col2"], ["100", "999"]])

    # Exacto: TEDS y TEDS-S son 1.0
    assert compute_teds(tbl_gt, tbl_exact, ignore_text=False) == 1.0
    assert compute_teds(tbl_gt, tbl_exact, ignore_text=True) == 1.0

    # Estructura idéntica pero texto diferente:
    # TEDS-S (structure-only) debe ser 1.0, mientras que TEDS completo debe ser menor a 1.0
    teds_s = compute_teds(tbl_gt, tbl_text_diff, ignore_text=True)
    teds_full = compute_teds(tbl_gt, tbl_text_diff, ignore_text=False)

    assert teds_s == 1.0
    assert teds_full < 1.0


def test_benchmark_runner_report():
    runner = BenchmarkRunner()
    tbl = _make_simple_table("tbl1", [["A", "B"], ["1", "2"]])

    doc = DocumentModel(
        metadata=DocumentMetadata(
            document_id="doc_test",
            filename="doc_test.pdf",
            engine_name="test",
        ),
        tables=[tbl],
    )

    report = runner.evaluate(
        document_name="doc_test.pdf",
        docling_doc=doc,
        paddle_doc=doc,
        ground_truth_doc=doc,
    )

    text_rep = report.format_text_report()
    assert "DOCUMENTO: doc_test.pdf" in text_rep
    assert "DOCLING" in text_rep
    assert "PADDLE" in text_rep
    assert "FINAL" in text_rep
    assert "GriTS" in text_rep
    assert "TEDS" in text_rep
    assert "Tables requiring correction" in text_rep
