"""
Pruebas unitarias para el TableValidator.
Verifica la detección de tablas válidas, anómalas, irregulares y degradadas.
"""

import pytest
from pdfextract.core.config import TableValidatorConfig
from pdfextract.core.models import BoundingBox, Cell, Table
from pdfextract.postprocess.table_validator import (
    TableValidator,
    ValidationStatus,
    compute_bbox_iou,
)


def _create_clean_table(table_id: str = "clean_tbl") -> Table:
    """Crea una tabla válida de 3x3 con celdas y bboxes consistentes."""
    rows = []
    for r in range(3):
        row = []
        for c in range(3):
            cell = Cell(
                text=f"R{r}C{c}",
                row_index=r,
                col_index=c,
                row_span=1,
                col_span=1,
                is_header=(r == 0),
                bbox=BoundingBox(
                    x0=100.0 + c * 50.0,
                    y0=100.0 + r * 20.0,
                    x1=100.0 + (c + 1) * 50.0,
                    y1=100.0 + (r + 1) * 20.0,
                    page=1,
                ),
            )
            row.append(cell)
        rows.append(row)

    return Table(
        table_id=table_id,
        page_start=1,
        page_end=1,
        num_rows=3,
        num_cols=3,
        headers=["R0C0", "R0C1", "R0C2"],
        rows=rows,
        bbox=BoundingBox(x0=100.0, y0=100.0, x1=250.0, y1=160.0, page=1),
    )


def test_clean_table_validation():
    validator = TableValidator()
    table = _create_clean_table()
    report = validator.validate(table)

    assert report.confidence_score >= 0.85
    assert report.validation_status == ValidationStatus.HIGH
    assert report.is_reliable is True
    assert len(report.issues) == 0
    assert report.to_dict()["confidence_score"] >= 0.85


def test_empty_cells_penalty():
    validator = TableValidator()
    table = _create_clean_table()

    # Vaciar la mayoría de las celdas
    for row in table.rows:
        for cell in row:
            cell.text = ""

    report = validator.validate(table)
    assert report.empty_cell_ratio == 1.0
    assert any(i.category == "structure" for i in report.issues)
    assert report.confidence_score < 0.80


def test_irregular_rows_penalty():
    validator = TableValidator()
    table = _create_clean_table()

    # Agregar una celda extra a la segunda fila creando irregularidad
    extra_cell = Cell(
        text="Extra",
        row_index=1,
        col_index=3,
        bbox=BoundingBox(x0=250.0, y0=120.0, x1=300.0, y1=140.0, page=1),
    )
    table.rows[1].append(extra_cell)

    report = validator.validate(table)
    assert any("inconsistente" in i.description for i in report.issues)
    assert report.confidence_score < 1.0


def test_invalid_spans_penalty():
    validator = TableValidator()
    table = _create_clean_table()

    # Celda con colspan que excede el ancho de la tabla (col 2 + span 2 > 3 cols)
    table.rows[0][2].col_span = 3

    report = validator.validate(table)
    assert any("rowspan/colspan" in i.description for i in report.issues)
    assert report.confidence_score < 0.90


def test_degenerate_bbox_penalty():
    validator = TableValidator()
    table = _create_clean_table()

    # Bbox con x1 <= x0
    table.rows[1][1].bbox = BoundingBox(x0=150.0, y0=120.0, x1=140.0, y1=140.0, page=1)

    report = validator.validate(table)
    assert any("degeneradas" in i.description for i in report.issues)


def test_out_of_bounds_penalty():
    validator = TableValidator()
    table = _create_clean_table()

    # Celda muy lejos fuera del bbox global de la tabla
    table.rows[2][2].bbox = BoundingBox(x0=500.0, y0=500.0, x1=550.0, y1=520.0, page=1)

    report = validator.validate(table)
    assert any("sobrepasan los límites" in i.description for i in report.issues)


def test_overlapping_cells_penalty():
    validator = TableValidator()
    table = _create_clean_table()

    # Forzar que la celda (0, 0) y (0, 1) compartan exactamente el mismo bbox
    same_bbox = BoundingBox(x0=100.0, y0=100.0, x1=150.0, y1=120.0, page=1)
    table.rows[0][0].bbox = same_bbox
    table.rows[0][1].bbox = same_bbox

    report = validator.validate(table)
    assert any("solapamiento espacial" in i.description for i in report.issues)


def test_excessively_long_text_penalty():
    validator = TableValidator()
    table = _create_clean_table()

    # Celda con texto masivo de más de 500 caracteres
    table.rows[1][0].text = "Texto muy extenso " * 40

    report = validator.validate(table)
    assert any("extensos" in i.description for i in report.issues)


def test_compute_bbox_iou():
    b1 = BoundingBox(x0=10.0, y0=10.0, x1=30.0, y1=30.0, page=1)
    b2 = BoundingBox(x0=20.0, y0=20.0, x1=40.0, y1=40.0, page=1)
    b3 = BoundingBox(x0=50.0, y0=50.0, x1=70.0, y1=70.0, page=1)
    b_diff_page = BoundingBox(x0=10.0, y0=10.0, x1=30.0, y1=30.0, page=2)

    # b1 and b2 overlap in [20,20,30,30] -> area 100. Union = 400 + 400 - 100 = 700. IoU = 100/700 = 1/7
    iou12 = compute_bbox_iou(b1, b2)
    assert pytest.approx(iou12, 0.01) == 1.0 / 7.0

    # No overlap
    assert compute_bbox_iou(b1, b3) == 0.0

    # Different page
    assert compute_bbox_iou(b1, b_diff_page) == 0.0


def test_multikey_cells_penalty():
    validator = TableValidator()
    table = _create_clean_table()

    # Celda con múltiples claves colapsadas (ej: "Tipo de Póliza: Frecuencia de Pago:")
    table.rows[1][0].text = "Tipo de Póliza: Frecuencia de Pago:"
    report = validator.validate(table)

    assert report.metrics.get("multikey_cells") == 1
    assert any("etiquetas múltiples colapsadas" in i.description for i in report.issues)
    assert report.confidence_score < 1.0

