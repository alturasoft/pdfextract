"""
Orquestador de extracción a nivel de documento individual.
Asegura la preservación del PDF original, ejecuta los motores de forma aislada,
coordina las exportaciones (TXT, MD, JSON), gestiona fallos generando error.log
y produce el informe de auditoría processing_metadata.json.
"""

import json
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from pdfextract.core.config import AppConfig
from pdfextract.core.logger import get_logger
from pdfextract.core.system_info import get_system_environment
from pdfextract.engines.base import BaseExtractionEngine, ExtractionResult
from pdfextract.engines.docling_engine import DoclingEngine
from pdfextract.engines.paddleocr_engine import PaddleOCRVLEngine
from pdfextract.evaluation.benchmark_runner import BenchmarkRunner
from pdfextract.exporters.json_exporter import JsonExporter
from pdfextract.exporters.markdown_exporter import MarkdownExporter
from pdfextract.exporters.txt_exporter import TxtExporter
from pdfextract.postprocess.rules import (
    TextRulesPipeline,
    create_default_text_rules_pipeline,
)
from pdfextract.postprocess.table_postprocessor import TablePostprocessor
from pdfextract.utils.file_utils import (
    calculate_sha256,
    copy_original_pdf,
    normalize_document_id,
    prepare_document_output_dirs,
)
from pdfextract.utils.pdf_utils import inspect_pdf_pages

logger = get_logger("DocumentProcessor")


class DocumentProcessor:
    """
    Procesador documental individual con aislamiento estricto entre motores.
    """

    def __init__(
        self,
        config: AppConfig,
        docling_engine: Optional[BaseExtractionEngine] = None,
        paddleocr_engine: Optional[BaseExtractionEngine] = None,
        table_postprocessor: Optional[TablePostprocessor] = None,
        text_rules_pipeline: Optional[TextRulesPipeline] = None,
    ):
        self.config = config
        self.docling_engine = docling_engine or DoclingEngine(config.engines.docling)
        self.paddleocr_engine = paddleocr_engine or PaddleOCRVLEngine(config.engines.paddleocr)
        self.table_postprocessor = table_postprocessor or TablePostprocessor(config.table_postprocessing)
        self.text_rules_pipeline = text_rules_pipeline or create_default_text_rules_pipeline(
            config=config.text_rules,
            enabled=config.text_rules.enabled,
        )
        self.benchmark_runner = BenchmarkRunner()

        # Inicializar exportadores
        self.txt_exporter = TxtExporter()
        self.md_exporter = MarkdownExporter()
        self.json_exporter = JsonExporter()

    def _execute_engine_safe(self, engine: BaseExtractionEngine, pdf_path: Path) -> ExtractionResult:
        """Ejecuta un motor capturando cualquier excepción inesperada para evitar detener el pipeline."""
        try:
            return engine.extract(pdf_path)
        except Exception as e:
            logger.error(f"Error crítico no controlado en motor '{engine.name}': {e}", exc_info=True)
            from pdfextract.core.models import DocumentMetadata, DocumentModel
            fallback_doc = DocumentModel(
                metadata=DocumentMetadata(
                    document_id=normalize_document_id(pdf_path),
                    filename=pdf_path.name,
                    engine_name=engine.name,
                    status="error",
                    error_message=str(e),
                )
            )
            return ExtractionResult(
                engine_name=engine.name,
                document=fallback_doc,
                processing_time_seconds=0.0,
                status="error",
                error_message=str(e),
            )

    def _export_engine_results(
        self,
        result: ExtractionResult,
        engine_dir: Path,
        base_filename: str,
    ) -> Dict[str, Optional[str]]:
        """
        Exporta las salidas obligatorias (TXT, MD, JSON) o genera error.log si falló.
        """
        exported_files: Dict[str, Optional[str]] = {
            "txt": None,
            "md": None,
            "json": None,
            "error_log": None,
        }

        if result.is_success:
            if self.config.output.save_txt:
                txt_path = self.txt_exporter.export(result, engine_dir, base_filename)
                exported_files["txt"] = str(txt_path)

            if self.config.output.save_markdown:
                md_path = self.md_exporter.export(result, engine_dir, base_filename)
                exported_files["md"] = str(md_path)

            if self.config.output.save_json:
                json_path = self.json_exporter.export(result, engine_dir, base_filename)
                exported_files["json"] = str(json_path)
        else:
            # En caso de error, generar error.log en la carpeta del motor
            error_log_path = engine_dir / "error.log"
            error_content = (
                f"ERROR EN MOTOR: {result.engine_name}\n"
                f"FECHA: {datetime.now(timezone.utc).isoformat()}\n"
                f"MENSAJE: {result.error_message or 'Error desconocido'}\n"
            )
            with open(error_log_path, "w", encoding="utf-8") as f:
                f.write(error_content)
            exported_files["error_log"] = str(error_log_path)
            logger.warning(f"Generado log de error para '{result.engine_name}' en: {error_log_path}")

        return exported_files

    def process(
        self,
        pdf_path: Path,
        custom_output_dir: Optional[Path] = None,
        parallel_override: Optional[bool] = None,
        enabled_engines: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """
        Procesa de forma completa un archivo PDF individual.
        
        Args:
            pdf_path: Ruta al archivo PDF original.
            custom_output_dir: Ruta alternativa para resultados (opcional).
            parallel_override: Forzar ejecución en paralelo o secuencial (opcional).
            enabled_engines: Lista de nombres de motores a ejecutar (ej. ['docling', 'paddleocr']).
        """
        if not pdf_path.exists():
            raise FileNotFoundError(f"El archivo PDF no existe: {pdf_path}")

        base_out = custom_output_dir or Path(self.config.output.output_dir)
        doc_id = normalize_document_id(pdf_path)
        dirs = prepare_document_output_dirs(base_out, doc_id)

        logger.info(f"Procesando documento: {pdf_path.name} (ID: {doc_id})")

        # 1. Copiar y preservar el PDF original
        if self.config.output.save_original:
            saved_pdf = copy_original_pdf(pdf_path, dirs["original"])
            logger.debug(f"Copia original preservada en: {saved_pdf}")

        # 2. Análisis previo del documento
        doc_type, page_reports = inspect_pdf_pages(
            pdf_path,
            min_chars_native=self.config.document_analysis.min_chars_native_page,
        )
        logger.info(f"Tipo documental detectado: {doc_type.upper()} ({len(page_reports)} páginas)")

        # 3. Determinar motores a ejecutar
        engines_to_run: List[BaseExtractionEngine] = []
        target_engine_names = enabled_engines or ["docling", "paddleocr"]

        if "docling" in target_engine_names and self.config.engines.docling.enabled:
            engines_to_run.append(self.docling_engine)

        if "paddleocr" in target_engine_names and self.config.engines.paddleocr.enabled:
            engines_to_run.append(self.paddleocr_engine)

        # 4. Decidir estrategia de ejecución (paralela o secuencial)
        is_parallel = (
            parallel_override
            if parallel_override is not None
            else self.config.processing.parallel
        )

        results: Dict[str, ExtractionResult] = {}

        if is_parallel and len(engines_to_run) > 1:
            logger.info(f"Ejecutando motores en paralelo ({len(engines_to_run)} tareas)...")
            with ThreadPoolExecutor(max_workers=min(len(engines_to_run), self.config.processing.max_workers)) as executor:
                futures = {
                    executor.submit(self._execute_engine_safe, eng, pdf_path): eng.name
                    for eng in engines_to_run
                }
                for fut in futures:
                    eng_name = futures[fut]
                    try:
                        results[eng_name] = fut.result()
                    except Exception as e:
                        logger.error(f"Fallo en hilo de ejecución para {eng_name}: {e}")
        else:
            logger.info("Ejecutando motores secuencialmente (protección de recursos/VRAM)...")
            for eng in engines_to_run:
                results[eng.name] = self._execute_engine_safe(eng, pdf_path)

        # 5. Aplicar reglas de postprocesamiento de texto y exportar resultados
        engine_summaries: Dict[str, Any] = {}
        for eng_name, res in results.items():
            if res.is_success and self.text_rules_pipeline:
                self.text_rules_pipeline.clean_document(res.document, engine_name=eng_name)

            target_dir = dirs.get(eng_name, dirs["root"] / eng_name)
            exported = self._export_engine_results(res, target_dir, doc_id)

            engine_summaries[eng_name] = {
                "status": res.status,
                "processing_time_seconds": res.processing_time_seconds,
                "pages_detected": len(res.document.pages),
                "tables_count": len(res.document.tables),
                "texts_count": len(res.document.texts),
                "output_files": exported,
                "error_message": res.error_message,
            }

        # 6. Postprocesamiento Inteligente y Corrección de Tablas
        postprocess_res = None
        postprocess_time = 0.0
        if self.config.table_postprocessing.enabled:
            logger.info("Iniciando fase de postprocesamiento y corrección de tablas...")
            t_start = time.perf_counter()
            d_res = results.get("docling")
            p_res = results.get("paddleocr")
            d_doc = d_res.document if d_res and d_res.is_success else None
            p_doc = p_res.document if p_res and p_res.is_success else None

            if d_doc is not None or p_doc is not None:
                postprocess_res = self.table_postprocessor.postprocess(
                    pdf_path=pdf_path,
                    docling_doc=d_doc,
                    paddle_doc=p_doc,
                )
                postprocess_time = round(time.perf_counter() - t_start, 3)

                # Aplicar reglas de texto generales al documento postprocesado
                if self.text_rules_pipeline:
                    self.text_rules_pipeline.clean_document(postprocess_res.document, engine_name="postprocessed")

                post_extract_res = ExtractionResult(
                    engine_name="postprocessed",
                    document=postprocess_res.document,
                    processing_time_seconds=postprocess_time,
                    status="success",
                )

                post_dir = dirs["postprocessed"]
                post_exported = self._export_engine_results(post_extract_res, post_dir, doc_id)

                # Guardar auditoría de decisiones si está habilitado
                if self.config.table_postprocessing.save_audit_log:
                    audit_file = post_dir / "table_postprocessing_audit.json"
                    audit_data = [rec.to_dict() for rec in postprocess_res.audit_records]
                    with open(audit_file, "w", encoding="utf-8") as f:
                        json.dump(audit_data, f, ensure_ascii=False, indent=2)
                    post_exported["audit_log"] = str(audit_file)
                    logger.info(f"Registro de auditoría de tablas guardado en: {audit_file}")

                engine_summaries["postprocessed"] = {
                    "status": "success",
                    "processing_time_seconds": postprocess_time,
                    "pages_detected": len(postprocess_res.document.pages),
                    "tables_count": len(postprocess_res.document.tables),
                    "texts_count": len(postprocess_res.document.texts),
                    "tables_corrected": postprocess_res.tables_corrected,
                    "tables_unchanged": postprocess_res.tables_unchanged,
                    "tables_rejected": postprocess_res.tables_rejected,
                    "output_files": post_exported,
                    "error_message": None,
                }

                # 7. Ejecutar reporte comparativo de benchmarking
                benchmark_rep = self.benchmark_runner.evaluate(
                    document_name=pdf_path.name,
                    docling_doc=d_doc,
                    paddle_doc=p_doc,
                    postprocessed_res=postprocess_res,
                    docling_time=d_res.processing_time_seconds if d_res else 0.0,
                    paddle_time=p_res.processing_time_seconds if p_res else 0.0,
                    postprocess_time=postprocess_time,
                )
                bench_txt = benchmark_rep.format_text_report()
                logger.info("\n" + bench_txt)

                # Guardar reporte de benchmark en disco
                bench_txt_path = dirs["root"] / "benchmark_report.txt"
                with open(bench_txt_path, "w", encoding="utf-8") as f:
                    f.write(bench_txt)

        # 8. Generar processing_metadata.json consolidado
        metadata_file = dirs["root"] / "processing_metadata.json"
        processing_metadata = {
            "document": {
                "document_id": doc_id,
                "filename": pdf_path.name,
                "file_size_bytes": pdf_path.stat().st_size,
                "file_hash_sha256": calculate_sha256(pdf_path),
                "total_pages": len(page_reports),
                "document_type": doc_type,
            },
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "system_environment": get_system_environment(),
            "engines": engine_summaries,
            "table_postprocessing_summary": (
                postprocess_res.to_summary_dict() if postprocess_res else None
            ),
        }

        with open(metadata_file, "w", encoding="utf-8") as f:
            json.dump(processing_metadata, f, ensure_ascii=False, indent=2)

        logger.info(f"Metadatos de procesamiento guardados en: {metadata_file}")

        return processing_metadata
