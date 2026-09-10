"""
Interfaz abstracta común para los exportadores de representación documental (TXT, Markdown, JSON).
Garantiza que ningún exportador esté acoplado a un motor específico.
"""

from abc import ABC, abstractmethod
from pathlib import Path
from pdfextract.engines.base import ExtractionResult


class BaseExporter(ABC):
    """
    Exportador abstracto que transforma el DocumentModel canónico o el ExtractionResult
    en un formato específico de salida.
    """

    @property
    @abstractmethod
    def format_name(self) -> str:
        """Extensión o nombre del formato (ej. 'txt', 'md', 'json')."""
        pass

    @abstractmethod
    def export(self, result: ExtractionResult, output_dir: Path, base_filename: str) -> Path:
        """
        Exporta el resultado documental al directorio especificado.
        
        Args:
            result: Resultado canónico generado por un motor de extracción.
            output_dir: Directorio de destino del motor (ej. output/poliza_001/docling/).
            base_filename: Nombre base sin extensión (ej. 'poliza_001').
            
        Returns:
            Ruta completa del archivo generado.
        """
        pass
