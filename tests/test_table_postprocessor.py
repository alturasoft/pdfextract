"""
Pruebas de integración para TablePostprocessor y el pipeline de DocumentProcessor.
Verifica la corrección selectiva, trazabilidad de auditoría y generación de salidas.
"""

from pathlib import Path
from unittest.mock import MagicMock

from pdfextract.core.config import AppConfig
from pdfextract.core.models import BoundingBox, Cell, DocumentMetadata, DocumentModel, Page, Table
from pdfextract.engines.base import BaseExtractionEngine, ExtractionResult
from pdfextract.engines.table_transformer_engine import (
    PredictedCell,
    PredictedTableStructure,
    TableTransformerEngine,
)
from pdfextract.postprocess.table_postprocessor import TablePostprocessor
from pdfextract.processors.document_processor import DocumentProcessor


def _make_page_with_table(page_num: int, num_cols: int, num_rows: int, table_id: str) -> Page:
    rows = []
    for r in range(num_rows):
        row = []
        for c in range(num_cols):
            row.append(
                Cell(
                    text=f"Cell_{r}_{c}",
                    row_index=r,
                    col_index=c,
                    bbox=BoundingBox(
                        x0=100.0 + c * 50.0,
                        y0=100.0 + r * 20.0,
                        x1=100.0 + (c + 1) * 50.0,
                        y1=100.0 + (r + 1) * 20.0,
                        page=page_num,
                    ),
                )
            )
        rows.append(row)

    tbl = Table(
        table_id=table_id,
        page_start=page_num,
        page_end=page_num,
        num_rows=num_rows,
        num_cols=num_cols,
        headers=[f"Col_{c}" for c in range(num_cols)],
        rows=rows,
        bbox=BoundingBox(
            x0=100.0,
            y0=100.0,
            x1=100.0 + num_cols * 50.0,
            y1=100.0 + num_rows * 20.0,
            page=page_num,
        ),
    )
    return Page(
        page_number=page_num,
        tables=[tbl],
    )


def test_postprocessor_selective_correction_preserved(tmp_path):
    """Cuando ambos motores coinciden con alta confianza, no se aplica corrección."""
    config = AppConfig()
    postprocessor = TablePostprocessor(config.table_postprocessing)

    pg_d = _make_page_with_table(1, num_cols=4, num_rows=4, table_id="tbl_clean")
    pg_p = _make_page_with_table(1, num_cols=4, num_rows=4, table_id="tbl_clean")

    doc_d = DocumentModel(
        metadata=DocumentMetadata(document_id="doc1", filename="doc1.pdf", engine_name="docling"),
        pages=[pg_d],
        tables=pg_d.tables,
    )
    doc_p = DocumentModel(
        metadata=DocumentMetadata(document_id="doc1", filename="doc1.pdf", engine_name="paddleocr"),
        pages=[pg_p],
        tables=pg_p.tables,
    )

    pdf_dummy = tmp_path / "dummy.pdf"
    pdf_dummy.write_bytes(b"%PDF-1.4 dummy")

    res = postprocessor.postprocess(pdf_dummy, doc_d, doc_p)

    assert res.tables_analyzed == 1
    assert res.tables_unchanged == 1
    assert res.tables_corrected == 0
    assert len(res.audit_records) == 1
    audit = res.audit_records[0]
    assert audit.correction_applied is False
    assert audit.detected_problem == "Ninguno (Alta confianza y/o consenso)"


def test_postprocessor_triggers_table_transformer_on_discrepancy(tmp_path):
    """Cuando hay discrepancia severa de columnas (3 vs 5), se activa Table Transformer."""
    config = AppConfig()

    mock_transformer = MagicMock(spec=TableTransformerEngine)
    mock_transformer.config = config.table_postprocessing.table_transformer

    # Simular que Table Transformer detecta una grilla perfecta de 5 cols x 4 rows
    row_bboxes = [
        BoundingBox(x0=100.0, y0=100.0 + r * 20.0, x1=350.0, y1=100.0 + (r + 1) * 20.0, page=1)
        for r in range(4)
    ]
    col_bboxes = [
        BoundingBox(x0=100.0 + c * 50.0, y0=100.0, x1=100.0 + (c + 1) * 50.0, y1=180.0, page=1)
        for c in range(5)
    ]
    cells = []
    for r in range(4):
        row = []
        for c in range(5):
            row.append(
                PredictedCell(
                    row_idx=r,
                    col_idx=c,
                    bbox=BoundingBox(
                        x0=100.0 + c * 50.0,
                        y0=100.0 + r * 20.0,
                        x1=100.0 + (c + 1) * 50.0,
                        y1=100.0 + (r + 1) * 20.0,
                        page=1,
                    ),
                    is_header=(r == 0),
                )
            )
        cells.append(row)

    mock_structure = PredictedTableStructure(
        num_rows=4,
        num_cols=5,
        row_bboxes=row_bboxes,
        col_bboxes=col_bboxes,
        cells=cells,
        average_confidence=0.98,
    )
    mock_transformer.predict_structure.return_value = mock_structure

    postprocessor = TablePostprocessor(
        config=config.table_postprocessing,
        transformer_engine=mock_transformer,
    )

    # Docling 3 cols vs Paddle 5 cols -> discrepancia crítica
    pg_d = _make_page_with_table(1, num_cols=3, num_rows=4, table_id="tbl_discrepant")
    pg_p = _make_page_with_table(1, num_cols=5, num_rows=4, table_id="tbl_discrepant")

    doc_d = DocumentModel(
        metadata=DocumentMetadata(document_id="doc1", filename="doc1.pdf", engine_name="docling"),
        pages=[pg_d],
        tables=pg_d.tables,
    )
    doc_p = DocumentModel(
        metadata=DocumentMetadata(document_id="doc1", filename="doc1.pdf", engine_name="paddleocr"),
        pages=[pg_p],
        tables=pg_p.tables,
    )

    pdf_dummy = tmp_path / "dummy.pdf"
    pdf_dummy.write_bytes(b"%PDF-1.4 dummy")

    res = postprocessor.postprocess(pdf_dummy, doc_d, doc_p)

    # Verificar que el transformer fue llamado
    assert mock_transformer.predict_structure.called
    assert res.tables_analyzed == 1
    assert res.tables_corrected == 1
    assert len(res.audit_records) == 1
    audit = res.audit_records[0]
    assert audit.correction_applied is True
    assert "Discrepancia" in audit.detected_problem
    assert audit.final_structure["num_cols"] == 5


class DummyMockEngine(BaseExtractionEngine):
    def __init__(self, name: str, doc: DocumentModel):
        self._name = name
        self._doc = doc

    @property
    def name(self) -> str:
        return self._name

    def is_available(self) -> bool:
        return True

    def extract(self, pdf_path: Path) -> ExtractionResult:
        return ExtractionResult(
            engine_name=self._name,
            document=self._doc,
            processing_time_seconds=0.1,
            status="success",
        )


def test_document_processor_with_postprocessing_outputs(tmp_path, synthetic_pdf):
    """Verifica que DocumentProcessor genere la carpeta postprocessed/ y sus archivos."""
    config = AppConfig()
    config.output.output_dir = str(tmp_path / "output")
    config.table_postprocessing.enabled = True
    config.table_postprocessing.save_audit_log = True

    pg = _make_page_with_table(1, num_cols=3, num_rows=3, table_id="tbl_p1")
    doc_mock = DocumentModel(
        metadata=DocumentMetadata(
            document_id="poliza_prueba",
            filename=synthetic_pdf.name,
            engine_name="mock",
        ),
        pages=[pg],
        tables=pg.tables,
    )

    d_eng = DummyMockEngine("docling", doc_mock)
    p_eng = DummyMockEngine("paddleocr", doc_mock)

    proc = DocumentProcessor(config, docling_engine=d_eng, paddleocr_engine=p_eng)
    meta = proc.process(synthetic_pdf)

    out_root = Path(config.output.output_dir) / "poliza_prueba"
    assert out_root.exists()

    # Verificar que exista la subcarpeta postprocessed/
    post_dir = out_root / "postprocessed"
    assert post_dir.exists()

    # Verificar archivos exportados
    assert (post_dir / "poliza_prueba.json").exists()
    assert (post_dir / "poliza_prueba.md").exists()
    assert (post_dir / "poliza_prueba.txt").exists()
    assert (post_dir / "table_postprocessing_audit.json").exists()
    assert (out_root / "benchmark_report.txt").exists()
    assert meta["table_postprocessing_summary"] is not None
