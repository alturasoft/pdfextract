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
