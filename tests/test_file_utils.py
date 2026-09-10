"""
Pruebas de utilidades de sistema de archivos e inspección de PDFs.
"""

from pathlib import Path
import pytest

from pdfextract.utils.file_utils import (
    calculate_sha256,
    copy_original_pdf,
    find_pdf_files,
    normalize_document_id,
    prepare_document_output_dirs,
)
from pdfextract.utils.pdf_utils import get_pdf_page_count, inspect_pdf_pages


def test_normalize_document_id():
    p1 = Path("Poliza Seguros #123 (Final).PDF")
    assert normalize_document_id(p1) == "Poliza_Seguros_123_Final"

    p2 = Path("anexo_coberturas_2026.pdf")
    assert normalize_document_id(p2) == "anexo_coberturas_2026"


def test_calculate_sha256(synthetic_pdf: Path):
    h = calculate_sha256(synthetic_pdf)
    assert isinstance(h, str)
    assert len(h) == 64  # SHA-256 produce 64 caracteres hexadecimales


def test_prepare_document_output_dirs(tmp_path: Path):
    dirs = prepare_document_output_dirs(tmp_path, "poliza_001")
    assert dirs["root"].exists()
    assert dirs["original"].exists()
    assert dirs["docling"].exists()
    assert dirs["paddleocr"].exists()


def test_copy_original_pdf(synthetic_pdf: Path, tmp_path: Path):
    orig_dir = tmp_path / "original"
    orig_dir.mkdir(parents=True)
    copied = copy_original_pdf(synthetic_pdf, orig_dir)

    assert copied.exists()
    assert copied.stat().st_size == synthetic_pdf.stat().st_size
    # Asegurar que el archivo fuente sigue existiendo intacto
    assert synthetic_pdf.exists()


def test_find_pdf_files(synthetic_pdf: Path, tmp_path: Path):
    # Encontrar por archivo único
    single = find_pdf_files(synthetic_pdf)
    assert len(single) == 1
    assert single[0] == synthetic_pdf

    # Encontrar por directorio
    found = find_pdf_files(tmp_path)
    assert len(found) >= 1
    assert synthetic_pdf in found


def test_inspect_pdf_pages(synthetic_pdf: Path):
    doc_type, reports = inspect_pdf_pages(synthetic_pdf, min_chars_native=20)
    assert doc_type in ("native", "scanned", "hybrid")
    assert len(reports) == 1
    assert reports[0]["page_number"] == 1
    assert get_pdf_page_count(synthetic_pdf) == 1
