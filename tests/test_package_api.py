"""
Pruebas unitarias para la API pública de alto nivel del paquete pdfextract.
"""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

import pdfextract
from pdfextract import (
    AppConfig,
    BatchProcessor,
    DocumentProcessor,
    __version__,
    extract_batch,
    extract_pdf,
    load_config,
)


def test_package_exports():
    """Verifica que los elementos clave estén exportados en la raíz del paquete."""
    assert __version__ == "1.0.2"
    assert callable(extract_pdf)
    assert callable(extract_batch)
    assert callable(load_config)
    assert DocumentProcessor is not None
    assert BatchProcessor is not None
    assert AppConfig is not None


def test_extract_pdf_file_not_found():
    """Verifica que se lance FileNotFoundError si el archivo no existe."""
    with pytest.raises(FileNotFoundError):
        extract_pdf("archivo_inexistente_12345.pdf")


def test_extract_batch_target_not_found():
    """Verifica que se lance FileNotFoundError si la ruta objetivo no existe."""
    with pytest.raises(FileNotFoundError):
        extract_batch("directorio_inexistente_12345/")


@patch("pdfextract.processors.document_processor.DocumentProcessor.process")
def test_extract_pdf_success_mock(mock_process, tmp_path):
    """Verifica que extract_pdf invoque adecuadamente a DocumentProcessor."""
    test_pdf = tmp_path / "dummy.pdf"
    test_pdf.write_bytes(b"%PDF-1.4 dummy")

    mock_process.return_value = {"status": "success", "document": {"filename": "dummy.pdf"}}

    result = extract_pdf(
        input_path=test_pdf,
        output_dir=tmp_path / "out",
        engine="docling",
        parallel=False,
    )

    assert result["status"] == "success"
    mock_process.assert_called_once()


@patch("pdfextract.processors.parallel_processor.BatchProcessor.process_all")
def test_extract_batch_success_mock(mock_process_all, tmp_path):
    """Verifica que extract_batch invoque adecuadamente a BatchProcessor."""
    test_dir = tmp_path / "pdfs"
    test_dir.mkdir()

    mock_process_all.return_value = [{"status": "success"}]

    results = extract_batch(
        input_target=test_dir,
        output_dir=tmp_path / "out",
        engine="paddleocr",
    )

    assert len(results) == 1
    mock_process_all.assert_called_once()
