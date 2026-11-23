"""
Punto de entrada principal (CLI) del Motor Comparativo de Extracción Documental.
Permite procesar pólizas de seguros de forma individual o por lotes con Docling y PaddleOCR-VL 1.6.

Ejemplos de uso:
  python main.py --input ./input/test_poliza.pdf
  python main.py --input ./input/ --output ./output/
  python main.py --input ./input/poliza.pdf --parallel
  python main.py --input ./input/poliza.pdf --engine docling
"""

import argparse
import sys
from pathlib import Path
from typing import List, Optional

from pdfextract import __version__
from pdfextract.core.config import load_config
from pdfextract.core.logger import get_logger, setup_logger
from pdfextract.processors.parallel_processor import BatchProcessor


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Motor Comparativo de Extracción Documental de Pólizas (Docling vs PaddleOCR-VL 1.6)",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )

    parser.add_argument(
        "-i", "--input",
        required=True,
        type=str,
        help="Ruta al archivo PDF individual o directorio que contiene PDFs a procesar.",
    )

    parser.add_argument(
        "-o", "--output",
        type=str,
        default=None,
        help="Directorio base de salida para los resultados estructurados (por defecto: config.yaml).",
    )

    parser.add_argument(
        "-c", "--config",
        type=str,
        default=None,
        help="Ruta a un archivo de configuración personalizado (YAML).",
    )

    parser.add_argument(
        "--parallel",
        action="store_true",
        default=None,
        help="Forzar ejecución simultánea de ambos motores en paralelo.",
    )

    parser.add_argument(
        "--no-parallel",
        action="store_false",
        dest="parallel",
        help="Forzar ejecución secuencial para reducir el consumo de memoria/VRAM.",
    )

    parser.add_argument(
        "-e", "--engine",
        type=str,
        choices=["all", "docling", "paddleocr"],
        default="all",
        help="Seleccionar qué motor ejecutar ('all', 'docling', 'paddleocr').",
    )

    parser.add_argument(
        "--postprocess",
        action="store_true",
        default=None,
        help="Forzar habilitación del postprocesamiento y corrección de tablas con Table Transformer.",
    )

    parser.add_argument(
        "--no-postprocess",
        action="store_false",
        dest="postprocess",
        default=None,
        help="Deshabilitar el postprocesamiento de tablas.",
    )

    parser.add_argument(
        "-v", "--version",
        action="version",
        version=f"%(prog)s {__version__}",
        help="Muestra la versión del sistema.",
    )

    return parser.parse_args()


def main() -> int:
    args = parse_arguments()

    # 1. Cargar configuración
    config_path = Path(args.config) if args.config else None
    config = load_config(config_path)

    if args.postprocess is not None:
        config.table_postprocessing.enabled = args.postprocess

    # 2. Configurar sistema de logging
    setup_logger(level=config.logging.level)
    logger = get_logger("CLI")

    logger.info("=" * 80)
    logger.info(f"MOTOR COMPARATIVO DE EXTRACCIÓN DOCUMENTAL v{__version__}")
    logger.info("Docling + PaddleOCR-VL 1.6 | Especializado en Pólizas de Seguros")
    logger.info("=" * 80)

    input_path = Path(args.input)
    if not input_path.exists():
        logger.error(f"La ruta de entrada no existe: {input_path}")
        return 1

    output_dir = Path(args.output) if args.output else Path(config.output.output_dir)

    # Determinar motores habilitados respetando la configuración activa
    if args.engine == "all":
        enabled_engines = [
            e for e in ["docling", "paddleocr"]
            if getattr(getattr(config.engines, e, None), "enabled", True)
        ]
        if not enabled_engines:
            enabled_engines = ["docling"]
    else:
        enabled_engines = [args.engine]

    logger.info(f"Ruta de entrada: {input_path.resolve()}")
    logger.info(f"Directorio de salida: {output_dir.resolve()}")
    logger.info(f"Motores activos: {', '.join(e.upper() for e in enabled_engines)}")
    logger.info(f"Modo de ejecución: {'PARALELO' if (args.parallel if args.parallel is not None else config.processing.parallel) else 'SECUENCIAL'}")
    logger.info(f"Postprocesamiento de tablas: {'ACTIVADO' if config.table_postprocessing.enabled else 'DESACTIVADO'}")

    # 3. Inicializar orquestador de lotes y procesar
    batch_processor = BatchProcessor(config)
    try:
        results = batch_processor.process_all(
            input_target=input_path,
            custom_output_dir=output_dir,
            parallel_override=args.parallel,
            enabled_engines=enabled_engines,
        )

        # 4. Imprimir resumen de extracción
        logger.info("-" * 80)
        logger.info("RESUMEN GENERAL DEL PROCESAMIENTO:")
        for r in results:
            doc_meta = r.get("document", {})
            doc_name = doc_meta.get("filename", "Desconocido")
            doc_type = doc_meta.get("document_type", "N/A")
            pages = doc_meta.get("total_pages", 0)
            logger.info(f"• Documento: {doc_name} | Tipo: {doc_type.upper()} | Páginas: {pages}")

            for eng_name, stats in r.get("engines", {}).items():
                status = stats.get("status", "unknown")
                time_sec = stats.get("processing_time_seconds", 0.0)
                tables = stats.get("tables_count", 0)
                texts = stats.get("texts_count", 0)
                logger.info(
                    f"    - [{eng_name.upper()}]: Estado={status.upper()} | "
                    f"Tiempo={time_sec}s | Tablas={tables} | Textos={texts}"
                )

            tp_summary = r.get("table_postprocessing_summary")
            if tp_summary:
                logger.info(
                    f"    - [POSTPROCESADO TABLAS]: Analizadas={tp_summary.get('tables_analyzed', 0)} | "
                    f"Corregidas={tp_summary.get('tables_corrected', 0)} | "
                    f"Conservadas={tp_summary.get('tables_unchanged', 0)} | "
                    f"Rechazadas={tp_summary.get('tables_rejected', 0)}"
                )

        logger.info("=" * 80)
        logger.info("Procesamiento completado con éxito. Resultados disponibles en disco.")
        return 0

    except Exception as e:
        logger.error(f"Fallo durante la ejecución: {e}", exc_info=True)
        return 1


if __name__ == "__main__":
    sys.exit(main())
