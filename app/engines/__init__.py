"""
Módulo de motores de extracción documental.
"""

from app.engines.base import BaseExtractionEngine, ExtractionResult
from app.engines.docling_engine import DoclingEngine
from app.engines.paddleocr_engine import PaddleOCRVLEngine

__all__ = [
    "BaseExtractionEngine",
    "ExtractionResult",
    "DoclingEngine",
    "PaddleOCRVLEngine",
]
