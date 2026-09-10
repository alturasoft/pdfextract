"""
Pruebas unitarias para TableReconstructor.
Verifica la alineación geométrica de fragmentos textuales con la estructura predicha.
"""

from pdfextract.core.models import BoundingBox, Cell, Table
from pdfextract.engines.table_transformer_engine import PredictedCell, PredictedTableStructure
from pdfextract.postprocess.table_reconstructor import TableReconstructor


def test_reconstruct_table_geometry_matching():
    reconstructor = TableReconstructor()

    # Estructura predicha de 2 filas x 3 columnas:
    # Fila 0: y in [100, 120], Fila 1: y in [120, 140]
    # Col 0: x in [50, 100], Col 1: x in [100, 150], Col 2: x in [150, 200]
    row_bboxes = [
        BoundingBox(x0=50.0, y0=100.0, x1=200.0, y1=120.0, page=1),
        BoundingBox(x0=50.0, y0=120.0, x1=200.0, y1=140.0, page=1),
    ]
    col_bboxes = [
        BoundingBox(x0=50.0, y0=100.0, x1=100.0, y1=140.0, page=1),
        BoundingBox(x0=100.0, y0=100.0, x1=150.0, y1=140.0, page=1),
        BoundingBox(x0=150.0, y0=100.0, x1=200.0, y1=140.0, page=1),
    ]

    cells = []
    for r_idx in range(2):
        row = []
        for c_idx in range(3):
            pcell = PredictedCell(
                row_idx=r_idx,
                col_idx=c_idx,
                bbox=BoundingBox(
                    x0=50.0 + c_idx * 50.0,
                    y0=100.0 + r_idx * 20.0,
                    x1=50.0 + (c_idx + 1) * 50.0,
                    y1=100.0 + (r_idx + 1) * 20.0,
                    page=1,
                ),
                is_header=(r_idx == 0),
            )
            row.append(pcell)
        cells.append(row)

    predicted_struct = PredictedTableStructure(
        num_rows=2,
        num_cols=3,
        row_bboxes=row_bboxes,
        col_bboxes=col_bboxes,
        cells=cells,
        average_confidence=0.95,
    )

    # Fuente OCR con textos desalineados en una sola fila pero con bboxes correctos
    src_cells = [
        Cell(
            text="Cobertura",
            row_index=0,
            col_index=0,
            bbox=BoundingBox(x0=60.0, y0=105.0, x1=90.0, y1=115.0, page=1),
        ),
        Cell(
            text="Suma Asegurada",
            row_index=0,
            col_index=1,
            bbox=BoundingBox(x0=110.0, y0=105.0, x1=140.0, y1=115.0, page=1),
        ),
        Cell(
            text="Deducible",
            row_index=0,
            col_index=2,
            bbox=BoundingBox(x0=160.0, y0=105.0, x1=190.0, y1=115.0, page=1),
        ),
        Cell(
            text="Incendio",
            row_index=1,
            col_index=0,
            bbox=BoundingBox(x0=55.0, y0=125.0, x1=85.0, y1=135.0, page=1),
        ),
        Cell(
            text="100.000",
            row_index=1,
            col_index=1,
            bbox=BoundingBox(x0=115.0, y0=125.0, x1=145.0, y1=135.0, page=1),
        ),
        Cell(
            text="500",
            row_index=1,
            col_index=2,
            bbox=BoundingBox(x0=165.0, y0=125.0, x1=185.0, y1=135.0, page=1),
        ),
    ]

    source_table = Table(
        table_id="source_tbl",
        page_start=1,
        page_end=1,
        num_rows=2,
        num_cols=3,
        rows=[src_cells[:3], src_cells[3:]],
    )

    reconstructed = reconstructor.reconstruct(
        predicted_structure=predicted_struct,
        source_tables=[source_table],
        original_table_id="reconstructed_tbl_1",
        page_number=1,
    )

    assert reconstructed.num_rows == 2
    assert reconstructed.num_cols == 3
    assert reconstructed.headers == ["Cobertura", "Suma Asegurada", "Deducible"]

    # Verificar asignación en celdas de datos
    assert reconstructed.rows[1][0].text == "Incendio"
    assert reconstructed.rows[1][1].text == "100.000"
    assert reconstructed.rows[1][2].text == "500"
    assert reconstructed.bbox is not None
    assert reconstructed.bbox.x0 == 50.0
    assert reconstructed.bbox.x1 == 200.0
