"""
Pruebas unitarias de los exportadores (TXT, Markdown y JSON).
"""

import json
from pathlib import Path

from pdfextract.core.models import DocumentModel
from pdfextract.engines.base import ExtractionResult
from pdfextract.exporters.json_exporter import JsonExporter
from pdfextract.exporters.markdown_exporter import MarkdownExporter
from pdfextract.exporters.txt_exporter import TxtExporter


def test_txt_exporter(sample_document_model: DocumentModel, tmp_path: Path):
    result = ExtractionResult(
        engine_name="test_engine",
        document=sample_document_model,
        processing_time_seconds=1.2,
        status="success",
    )
    exporter = TxtExporter()
    out_file = exporter.export(result, tmp_path, "test_doc")

    assert out_file.exists()
    content = out_file.read_text(encoding="utf-8")
    assert "DOCUMENTO: poliza_test_001.pdf" in content
    assert "--- [PÁGINA 1] ---" in content
    assert "CONDICIONES PARTICULARES DE POLIZA" in content
    # Verificar tabla formateada
    assert "Incendio y Rayo" in content
    assert "USD 500.000" in content


def test_markdown_exporter(sample_document_model: DocumentModel, tmp_path: Path):
    result = ExtractionResult(
        engine_name="test_engine",
        document=sample_document_model,
        processing_time_seconds=1.2,
        status="success",
    )
    exporter = MarkdownExporter()
    out_file = exporter.export(result, tmp_path, "test_doc")

    assert out_file.exists()
    content = out_file.read_text(encoding="utf-8")
    assert "# CONDICIONES PARTICULARES DE POLIZA" in content or "poliza_test_001.pdf" in content
    # Verificar sintaxis de tabla Markdown GFM
    assert "| Cobertura | Suma Asegurada | Deducible |" in content
    assert "| --- | --- | --- |" in content
    assert "| Incendio y Rayo | USD 500.000 | 5% min USD 200 |" in content


def test_markdown_exporter_table_title_promotion(tmp_path: Path):
    from pdfextract.core.models import Cell, Table
    table = Table(
        table_id="tbl_title_test",
        page_start=1,
        page_end=1,
        num_rows=3,
        num_cols=3,
        rows=[
            [
                Cell(text="CONDICION DE PAGO", row_index=0, col_index=0, col_span=3, is_header=True),
                Cell(text="CONDICION DE PAGO", row_index=0, col_index=1, col_span=3, is_header=True),
                Cell(text="CONDICION DE PAGO", row_index=0, col_index=2, col_span=3, is_header=True),
            ],
            [
                Cell(text="Forma Pago", row_index=1, col_index=0, is_header=True),
                Cell(text="Prima Anual", row_index=1, col_index=1, is_header=True),
                Cell(text="Prima Total", row_index=1, col_index=2, is_header=True),
            ],
            [
                Cell(text="CONTADO", row_index=2, col_index=0),
                Cell(text="424,00", row_index=2, col_index=1),
                Cell(text="424,00", row_index=2, col_index=2),
            ],
        ],
    )
    exporter = MarkdownExporter()
    md = exporter._format_table_as_markdown(table)
    assert "**Tabla: CONDICION DE PAGO**" in md
    assert "| Forma Pago | Prima Anual | Prima Total |" in md
    assert "| CONTADO | 424,00 | 424,00 |" in md


def test_markdown_exporter_span_expansion(tmp_path: Path):
    from pdfextract.core.models import Cell, Table
    # Celda combinada con row_span=2 y col_span=2
    table = Table(
        table_id="tbl_span_test",
        page_start=1,
        page_end=1,
        num_rows=3,
        num_cols=3,
        headers=["Cat", "SubCat", "Valor"],
        rows=[
            [
                Cell(text="SECCIÓN A", row_index=0, col_index=0, row_span=2, col_span=2),
                Cell(text="100", row_index=0, col_index=2),
            ],
            [
                Cell(text="200", row_index=1, col_index=2),
            ],
        ],
    )
    exporter = MarkdownExporter()
    md = exporter._format_table_as_markdown(table)
    # En GFM, SECCIÓN A se replica verticalmente para autocontención de chunks RAG,
    # mientras que las columnas cubiertas por colspan quedan limpias (sin duplicación horizontal redundante).
    assert "| SECCIÓN A |  | 100 |" in md
    assert "| SECCIÓN A |  | 200 |" in md


def test_json_exporter(sample_document_model: DocumentModel, tmp_path: Path):
    result = ExtractionResult(
        engine_name="test_engine",
        document=sample_document_model,
        processing_time_seconds=1.2,
        status="success",
    )
    exporter = JsonExporter()
    out_file = exporter.export(result, tmp_path, "test_doc")

    assert out_file.exists()
    with open(out_file, "r", encoding="utf-8") as f:
        data = json.load(f)

    # Validar campos de primer nivel
    assert "document" in data
    assert "extraction" in data
    assert "pages" in data
    assert "texts" in data
    assert "tables" in data
    assert "rag_chunks" in data
    assert "raw_engine_data" in data

    # Validar datos estructurales de tabla
    assert len(data["tables"]) == 1
    tbl = data["tables"][0]
    assert tbl["table_id"] == "tbl_001"
    assert tbl["num_rows"] == 3
    assert tbl["num_cols"] == 3
    assert tbl["headers"] == ["Cobertura", "Suma Asegurada", "Deducible"]

    # Validar coordenadas de textos
    first_text = data["texts"][0]
    assert first_text["bbox"]["x0"] == 50.0
    assert first_text["bbox"]["page"] == 1

    # Validar chunks RAG
    assert len(data["rag_chunks"]) == 1
    assert data["rag_chunks"][0]["document_id"] == "poliza_test_001"
