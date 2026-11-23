"""
pdfextract: Motor de Extracción y Análisis Documental.
Integración dual de Docling y PaddleOCR-VL 1.6 especializado en pólizas y documentos complejos.
"""

from pathlib import Path
from typing import Any, Dict, List, Optional, Union

from pdfextract.core.config import AppConfig, load_config
from pdfextract.core.models import (
    BoundingBox,
    Cell,
    DocumentMetadata,
    DocumentModel,
    Page,
    Table,
    TextElement,
)
from pdfextract.engines.base import BaseExtractionEngine, ExtractionResult
from pdfextract.processors.document_processor import DocumentProcessor
from pdfextract.processors.parallel_processor import BatchProcessor

__version__ = "1.0.2"


def extract_pdf(
    input_path: Union[str, Path],
    output_dir: Optional[Union[str, Path]] = None,
    engine: Optional[str] = None,
    parallel: Optional[bool] = None,
    config: Optional[Union[AppConfig, str, Path]] = None,
) -> Dict[str, Any]:
    """
    Extrae contenido estructurado de un archivo PDF individual en una sola llamada.

    Args:
        input_path: Ruta al archivo PDF a procesar.
        output_dir: Directorio de salida opcional para guardar artefactos (TXT, MD, JSON).
        engine: Motor específico a ejecutar ('docling', 'paddleocr' o None para ambos).
        parallel: Ejecutar motores simultáneamente (True) o secuencialmente (False).
        config: Objeto AppConfig o ruta a un archivo YAML personalizado.

    Returns:
        Diccionario con la metadata de procesamiento, modelos generados y rutas de salida.
    """
    input_path = Path(input_path)
    if not input_path.exists():
        raise FileNotFoundError(f"No se encontró el archivo PDF: {input_path}")

    # Resolver configuración
    if isinstance(config, AppConfig):
        app_config = config
    elif isinstance(config, (str, Path)):
        app_config = load_config(Path(config))
    else:
        app_config = load_config()

    custom_out = Path(output_dir) if output_dir else None
    enabled_engines = [engine.lower()] if engine else None

    processor = DocumentProcessor(config=app_config)
    return processor.process(
        pdf_path=input_path,
        custom_output_dir=custom_out,
        parallel_override=parallel,
        enabled_engines=enabled_engines,
    )


def extract_batch(
    input_target: Union[str, Path],
    output_dir: Optional[Union[str, Path]] = None,
    engine: Optional[str] = None,
    parallel: Optional[bool] = None,
    config: Optional[Union[AppConfig, str, Path]] = None,
) -> List[Dict[str, Any]]:
    """
    Procesa una carpeta completa de archivos PDF o un archivo individual.

    Args:
        input_target: Ruta a un PDF individual o a una carpeta con PDFs.
        output_dir: Directorio de salida opcional.
        engine: Motor específico ('docling', 'paddleocr' o None para ambos).
        parallel: Ejecutar motores en paralelo (True) o secuencial (False).
        config: Objeto AppConfig o ruta a YAML.

    Returns:
        Lista de diccionarios con el resultado de cada PDF procesado.
    """
    input_target = Path(input_target)
    if not input_target.exists():
        raise FileNotFoundError(f"No se encontró la ruta: {input_target}")

    if isinstance(config, AppConfig):
        app_config = config
    elif isinstance(config, (str, Path)):
        app_config = load_config(Path(config))
    else:
        app_config = load_config()

    custom_out = Path(output_dir) if output_dir else None
    enabled_engines = [engine.lower()] if engine else None

    batch_processor = BatchProcessor(config=app_config)
    return batch_processor.process_all(
        input_target=input_target,
        custom_output_dir=custom_out,
        parallel_override=parallel,
        enabled_engines=enabled_engines,
    )


__all__ = [
    "__version__",
    "extract_pdf",
    "extract_batch",
    "DocumentProcessor",
    "BatchProcessor",
    "AppConfig",
    "load_config",
    "DocumentModel",
    "DocumentMetadata",
    "Page",
    "Table",
    "Cell",
    "TextElement",
    "BoundingBox",
    "ExtractionResult",
    "BaseExtractionEngine",
]
