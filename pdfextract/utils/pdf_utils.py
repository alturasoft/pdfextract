"""
Utilidades para análisis e inspección previa de archivos PDF.
Determina si un documento es nativo, escaneado o híbrido mediante análisis por página.
"""

from pathlib import Path
from typing import Any, Dict, List, Tuple


def inspect_pdf_pages(pdf_path: Path, min_chars_native: int = 50) -> Tuple[str, List[Dict[str, Any]]]:
    """
    Inspecciona página por página un archivo PDF para detectar texto digital embebido.
    
    Args:
        pdf_path: Ruta al archivo PDF.
        min_chars_native: Umbral mínimo de caracteres para clasificar una página como nativa.
        
    Returns:
        Tupla de (doc_type, page_reports):
        - doc_type: 'native', 'scanned' o 'hybrid'
        - page_reports: Lista de diccionarios con el análisis detallado por página.
    """
    page_reports: List[Dict[str, Any]] = []

    try:
        from pypdf import PdfReader
        reader = PdfReader(str(pdf_path))
        total_pages = len(reader.pages)

        scanned_count = 0
        native_count = 0

        for idx, page in enumerate(reader.pages, start=1):
            extracted_text = (page.extract_text() or "").strip()
            char_count = len(extracted_text)
            has_native = char_count >= min_chars_native

            if has_native:
                native_count += 1
            else:
                scanned_count += 1

            page_reports.append({
                "page_number": idx,
                "has_native_text": has_native,
                "is_scanned": not has_native,
                "char_count": char_count,
            })

        if scanned_count == 0:
            doc_type = "native"
        elif native_count == 0:
            doc_type = "scanned"
        else:
            doc_type = "hybrid"

    except Exception:
        # Modo de contingencia en caso de que pypdf no pueda abrir el archivo
        doc_type = "hybrid"
        page_reports = [{
            "page_number": 1,
            "has_native_text": True,
            "is_scanned": False,
            "char_count": 0,
        }]

    return doc_type, page_reports


def get_pdf_page_count(pdf_path: Path) -> int:
    """Retorna el número total de páginas de un PDF."""
    try:
        from pypdf import PdfReader
        reader = PdfReader(str(pdf_path))
        return len(reader.pages)
    except Exception:
        return 1
