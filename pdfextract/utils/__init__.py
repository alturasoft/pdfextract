"""
Módulo de utilidades generales para archivos y PDFs.
"""

from pdfextract.utils.file_utils import (
    calculate_sha256,
    normalize_document_id,
    find_pdf_files,
    prepare_document_output_dirs,
    copy_original_pdf,
)
from pdfextract.utils.pdf_utils import inspect_pdf_pages, get_pdf_page_count

__all__ = [
    "calculate_sha256",
    "normalize_document_id",
    "find_pdf_files",
    "prepare_document_output_dirs",
    "copy_original_pdf",
    "inspect_pdf_pages",
    "get_pdf_page_count",
]
