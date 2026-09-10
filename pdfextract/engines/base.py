"""
Interfaces y clases base para motores de extracción documental (Plugin Architecture).
Permite incorporar fácilmente nuevos motores (Docling, PaddleOCR-VL, MinerU, etc.)
manteniendo un contrato de interfaz uniforme y desacoplado.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Optional

from pdfextract.core.models import DocumentModel


@dataclass
class ExtractionResult:
    """
    Contenedor estándar del resultado de extracción de un motor.
    """
    engine_name: str
    document: DocumentModel
    processing_time_seconds: float
    status: str = "success"  # "success" o "error"
    error_message: Optional[str] = None
    raw_output: Dict[str, Any] = field(default_factory=dict)

    @property
    def is_success(self) -> bool:
        return self.status == "success"


class BaseExtractionEngine(ABC):
    """
    Interfaz abstracta común para todos los motores de extracción.
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """Nombre identificador único del motor (ej. 'docling', 'paddleocr')."""
        pass

    @abstractmethod
    def is_available(self) -> bool:
        """Verifica si las dependencias y modelos del motor están instalados y disponibles."""
        pass

    @abstractmethod
    def extract(self, pdf_path: Path) -> ExtractionResult:
        """
        Ejecuta el proceso completo de extracción sobre el archivo PDF indicado.
        
        Args:
            pdf_path: Ruta al archivo PDF original.
            
        Returns:
            ExtractionResult con el DocumentModel canónico y metadatos de ejecución.
        """
        pass
