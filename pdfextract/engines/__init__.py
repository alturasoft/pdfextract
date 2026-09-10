"""
Módulo de motores de extracción documental.
"""

from pdfextract.engines.base import BaseExtractionEngine, ExtractionResult
from pdfextract.engines.docling_engine import DoclingEngine
from pdfextract.engines.paddleocr_engine import PaddleOCRVLEngine

__all__ = [
    "BaseExtractionEngine",
    "ExtractionResult",
    "DoclingEngine",
    "PaddleOCRVLEngine",
]
