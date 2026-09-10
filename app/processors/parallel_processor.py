"""
Procesador de lotes y gestor de concurrencia a nivel de múltiples documentos.
Permite procesar carpetas enteras de pólizas de seguros de forma secuencial o concurrente.
"""

from pathlib import Path
from typing import Any, Dict, List, Optional

from app.core.config import AppConfig
from app.core.logger import get_logger
from app.processors.document_processor import DocumentProcessor
from app.utils.file_utils import find_pdf_files

logger = get_logger("BatchProcessor")


class BatchProcessor:
    """
    Gestiona el procesamiento en lote de colecciones de documentos PDF.
    """

    def __init__(self, config: AppConfig, document_processor: Optional[DocumentProcessor] = None):
        self.config = config
        self.document_processor = document_processor or DocumentProcessor(config)

    def process_all(
        self,
        input_target: Path,
        custom_output_dir: Optional[Path] = None,
        parallel_override: Optional[bool] = None,
        enabled_engines: Optional[List[str]] = None,
    ) -> List[Dict[str, Any]]:
        """
        Descubre todos los archivos PDF en la ruta objetivo y los procesa uno a uno.
        
        Args:
            input_target: Archivo PDF único o directorio con múltiples PDFs.
            custom_output_dir: Directorio de salida opcional.
            parallel_override: Flag para forzar ejecución paralela o secuencial.
            enabled_engines: Lista opcional de motores específicos.
            
        Returns:
            Lista de diccionarios con el processing_metadata de cada documento procesado.
        """
        pdf_files = find_pdf_files(input_target)
        total_files = len(pdf_files)

        if total_files == 0:
            logger.warning(f"No se encontraron archivos PDF en: {input_target}")
            return []

        logger.info(f"Iniciando procesamiento de {total_files} documento(s) PDF...")
        batch_results: List[Dict[str, Any]] = []

        for idx, pdf_path in enumerate(pdf_files, start=1):
            logger.info(f"[{idx}/{total_files}] Iniciando procesamiento de: {pdf_path.name}")
            try:
                doc_summary = self.document_processor.process(
                    pdf_path=pdf_path,
                    custom_output_dir=custom_output_dir,
                    parallel_override=parallel_override,
                    enabled_engines=enabled_engines,
                )
                batch_results.append(doc_summary)
            except Exception as e:
                logger.error(f"Error procesando {pdf_path.name}: {e}", exc_info=True)
                batch_results.append({
                    "document": {"filename": pdf_path.name, "status": "error", "error": str(e)},
                    "engines": {},
                })

        logger.info(f"Procesamiento en lote finalizado ({len(batch_results)}/{total_files} procesados).")
        return batch_results
