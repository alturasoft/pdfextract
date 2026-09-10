"""
Fixtures y generadores de datos sintéticos para las pruebas automatizadas.
"""

from pathlib import Path
from typing import List
import pytest

from pdfextract.core.models import (
    BoundingBox,
    Cell,
    DocumentMetadata,
    DocumentModel,
    Page,
    RAGChunk,
    Table,
    TextElement,
)
from pdfextract.engines.base import BaseExtractionEngine, ExtractionResult


@pytest.fixture
def synthetic_pdf(tmp_path: Path) -> Path:
    """Genera un archivo PDF sintético con contenido textual de póliza para tests."""
    pdf_path = tmp_path / "poliza_prueba.pdf"
    content = """BT
/F1 14 Tf
50 750 Td
(POLIZA DE PRUEBA NRO 12345) Tj
/F1 10 Tf
0 -30 Td
(Asegurado: Seguros Globales S.A.) Tj
0 -25 Td
(Cobertura: Todo Riesgo Incendio - Suma: USD 500.000) Tj
ET"""
    content_bytes = content.encode("latin1")
    pdf_data = f"""%PDF-1.4
1 0 obj
<< /Type /Catalog /Pages 2 0 R >>
endobj
2 0 obj
<< /Type /Pages /Kids [3 0 R] /Count 1 >>
endobj
3 0 obj
<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>
endobj
4 0 obj
<< /Length {len(content_bytes)} >>
stream
{content}
endstream
endobj
5 0 obj
<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>
endobj
xref
0 6
0000000000 65535 f 
0000000009 00000 n 
0000000058 00000 n 
0000000115 00000 n 
0000000234 00000 n 
0000000300 00000 n 
trailer
<< /Size 6 /Root 1 0 R >>
startxref
400
%%EOF"""
    with open(pdf_path, "w", encoding="latin1") as f:
        f.write(pdf_data)

    return pdf_path


@pytest.fixture
def sample_document_model() -> DocumentModel:
    """Retorna una instancia canónica completa de DocumentModel con tablas complejas y bboxes."""
    meta = DocumentMetadata(
        document_id="poliza_test_001",
        filename="poliza_test_001.pdf",
        file_size_bytes=1024,
        file_hash_sha256="abcdef1234567890",
        total_pages=1,
        engine_name="mock_engine",
        engine_version="1.0.0",
        processing_time_seconds=1.25,
        status="success",
    )

    bbox_title = BoundingBox(x0=50.0, y0=750.0, x1=400.0, y1=770.0, page=1)
    bbox_para = BoundingBox(x0=50.0, y0=700.0, x1=500.0, y1=720.0, page=1)

    elem_title = TextElement(
        element_id="txt_001",
        type="title",
        text="CONDICIONES PARTICULARES DE POLIZA",
        bbox=bbox_title,
        page=1,
        reading_order=0,
    )
    elem_para = TextElement(
        element_id="txt_002",
        type="paragraph",
        text="La compañía asegura contra daños directos sufridos durante la vigencia.",
        bbox=bbox_para,
        page=1,
        reading_order=1,
    )

    # Tabla con celdas combinadas y encabezados
    cell_h1 = Cell(text="Cobertura", row_index=0, col_index=0, is_header=True, col_span=1, row_span=1)
    cell_h2 = Cell(text="Suma Asegurada", row_index=0, col_index=1, is_header=True, col_span=1, row_span=1)
    cell_h3 = Cell(text="Deducible", row_index=0, col_index=2, is_header=True, col_span=1, row_span=1)

    cell_r1_c1 = Cell(text="Incendio y Rayo", row_index=1, col_index=0, is_header=False)
    cell_r1_c2 = Cell(text="USD 500.000", row_index=1, col_index=1, is_header=False)
    cell_r1_c3 = Cell(text="5% min USD 200", row_index=1, col_index=2, is_header=False)

    cell_r2_c1 = Cell(text="Terremoto / Temblor", row_index=2, col_index=0, is_header=False)
    cell_r2_c2 = Cell(text="USD 300.000", row_index=2, col_index=1, is_header=False)
    cell_r2_c3 = Cell(text="10% min USD 500", row_index=2, col_index=2, is_header=False)

    table = Table(
        table_id="tbl_001",
        page_start=1,
        page_end=1,
        num_rows=3,
        num_cols=3,
        headers=["Cobertura", "Suma Asegurada", "Deducible"],
        rows=[
            [cell_h1, cell_h2, cell_h3],
            [cell_r1_c1, cell_r1_c2, cell_r1_c3],
            [cell_r2_c1, cell_r2_c2, cell_r2_c3],
        ],
        caption="Cuadro General de Coberturas",
        is_multipage=False,
    )

    page = Page(
        page_number=1,
        width=612.0,
        height=792.0,
        is_scanned=False,
        has_native_text=True,
        elements=[elem_title, elem_para],
        tables=[table],
        raw_text="CONDICIONES PARTICULARES DE POLIZA\nLa compañía asegura contra daños directos.",
    )

    rag_chunk = RAGChunk(
        chunk_id="poliza_test_001_chunk_001",
        document_id="poliza_test_001",
        section="CONDICIONES PARTICULARES",
        page_start=1,
        page_end=1,
        chunk_type="text",
        text="CONDICIONES PARTICULARES DE POLIZA La compañía asegura contra daños directos.",
        bboxes=[bbox_title, bbox_para],
        token_estimate=12,
    )

    return DocumentModel(
        metadata=meta,
        pages=[page],
        sections=[],
        texts=[elem_title, elem_para],
        tables=[table],
        rag_chunks=[rag_chunk],
        raw_engine_data={"mock_key": "mock_value"},
    )


class MockSuccessEngine(BaseExtractionEngine):
    def __init__(self, engine_name: str = "mock_success"):
        self._name = engine_name

    @property
    def name(self) -> str:
        return self._name

    def is_available(self) -> bool:
        return True

    def extract(self, pdf_path: Path) -> ExtractionResult:
        meta = DocumentMetadata(
            document_id=pdf_path.stem,
            filename=pdf_path.name,
            total_pages=1,
            engine_name=self.name,
            processing_time_seconds=0.1,
            status="success",
        )
        doc = DocumentModel(metadata=meta)
        return ExtractionResult(
            engine_name=self.name,
            document=doc,
            processing_time_seconds=0.1,
            status="success",
        )


class MockFailingEngine(BaseExtractionEngine):
    def __init__(self, engine_name: str = "mock_fail"):
        self._name = engine_name

    @property
    def name(self) -> str:
        return self._name

    def is_available(self) -> bool:
        return True

    def extract(self, pdf_path: Path) -> ExtractionResult:
        raise RuntimeError("Simulated crash in mock engine for fault-tolerance test")
