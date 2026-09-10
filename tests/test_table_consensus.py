"""
Pruebas unitarias para TableConsensusEngine.
Verifica la detección de acuerdos y discrepancias entre Docling y PaddleOCR-VL.
"""

from pdfextract.core.config import TableConsensusConfig
from pdfextract.core.models import BoundingBox, Cell, Table
from pdfextract.postprocess.table_consensus import TableConsensusEngine
from pdfextract.postprocess.table_validator import TableValidator


def _build_table(table_id: str, cols: int, rows: int, x0: float = 100.0, y0: float = 100.0) -> Table:
    matrix = []
    headers = [f"Col{c}" for c in range(cols)]
    for r in range(rows):
        row = []
        for c in range(cols):
            cell = Cell(
                text=f"Val_{r}_{c}",
                row_index=r,
                col_index=c,
                bbox=BoundingBox(
                    x0=x0 + c * 40.0,
                    y0=y0 + r * 15.0,
                    x1=x0 + (c + 1) * 40.0,
                    y1=y0 + (r + 1) * 15.0,
                    page=1,
                ),
            )
            row.append(cell)
        matrix.append(row)

    return Table(
        table_id=table_id,
        page_start=1,
        page_end=1,
        num_rows=rows,
        num_cols=cols,
        headers=headers,
        rows=matrix,
        bbox=BoundingBox(
            x0=x0,
            y0=y0,
            x1=x0 + cols * 40.0,
            y1=y0 + rows * 15.0,
            page=1,
        ),
    )


def test_consensus_agreement():
    consensus = TableConsensusEngine()
    tbl_docling = _build_table("tbl_doc", cols=4, rows=5)
    tbl_paddle = _build_table("tbl_pad", cols=4, rows=5)

    res = consensus.compare_tables(tbl_docling, tbl_paddle, page_number=1)

    assert res.agreement_score >= 0.85
    assert res.requires_correction is False
    assert len(res.discrepancy_reasons) == 0
    assert res.preferred_engine in ["docling", "paddleocr"]


def test_consensus_column_discrepancy():
    consensus = TableConsensusEngine()
    # Docling: 3 cols vs Paddle: 5 cols
    tbl_docling = _build_table("tbl_doc", cols=3, rows=5)
    tbl_paddle = _build_table("tbl_pad", cols=5, rows=5)

    res = consensus.compare_tables(tbl_docling, tbl_paddle, page_number=1)

    assert res.requires_correction is True
    assert any("columnas" in r.lower() for r in res.discrepancy_reasons)
    assert res.agreement_score < 0.80


def test_consensus_single_engine_only():
    consensus = TableConsensusEngine()
    tbl_docling = _build_table("tbl_doc", cols=4, rows=5)

    res = consensus.compare_tables(tbl_docling, None, page_number=1)

    # Una tabla de alta confianza detectada solo por un motor no requiere corrección
    assert res.preferred_engine == "docling"
    assert res.paddle_table_id is None


def test_match_and_compare_page_tables():
    consensus = TableConsensusEngine()

    tbl_d1 = _build_table("d1", cols=3, rows=4, x0=50.0, y0=50.0)
    tbl_d2 = _build_table("d2", cols=4, rows=6, x0=50.0, y0=300.0)

    tbl_p1 = _build_table("p1", cols=3, rows=4, x0=52.0, y0=52.0)
    tbl_p2 = _build_table("p2", cols=4, rows=6, x0=52.0, y0=302.0)

    matched = consensus.match_and_compare_page_tables([tbl_d1, tbl_d2], [tbl_p1, tbl_p2], page_number=1)

    assert len(matched) == 2
    # El primer par debe corresponder a d1 y p1
    assert matched[0][0].table_id == "d1"
    assert matched[0][1].table_id == "p1"
    assert matched[0][2].requires_correction is False
