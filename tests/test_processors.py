"""
Pruebas de orquestación, concurrencia y tolerancia a fallos.
"""

from pathlib import Path
import pytest

from pdfextract.core.config import AppConfig
from pdfextract.processors.document_processor import DocumentProcessor
from pdfextract.processors.parallel_processor import BatchProcessor
from tests.conftest import MockFailingEngine, MockSuccessEngine


def test_document_processor_success(synthetic_pdf: Path, tmp_path: Path):
    """Prueba el flujo exitoso completo con copia original y metadatos."""
    config = AppConfig()
    engine_docling = MockSuccessEngine("docling")
    engine_paddle = MockSuccessEngine("paddleocr")

    processor = DocumentProcessor(
        config=config,
        docling_engine=engine_docling,
        paddleocr_engine=engine_paddle,
    )

    summary = processor.process(
        pdf_path=synthetic_pdf,
        custom_output_dir=tmp_path,
        parallel_override=False,
    )

    doc_id = synthetic_pdf.stem
    doc_dir = tmp_path / doc_id

    # 1. Verificar preservación del original
    assert (doc_dir / "original" / synthetic_pdf.name).exists()

    # 2. Verificar resultados de docling
    assert (doc_dir / "docling" / f"{doc_id}.txt").exists()
    assert (doc_dir / "docling" / f"{doc_id}.md").exists()
    assert (doc_dir / "docling" / f"{doc_id}.json").exists()

    # 3. Verificar resultados de paddleocr
    assert (doc_dir / "paddleocr" / f"{doc_id}.txt").exists()
    assert (doc_dir / "paddleocr" / f"{doc_id}.md").exists()
    assert (doc_dir / "paddleocr" / f"{doc_id}.json").exists()

    # 4. Verificar processing_metadata.json
    metadata_file = doc_dir / "processing_metadata.json"
    assert metadata_file.exists()
    assert summary["document"]["document_id"] == doc_id
    assert summary["engines"]["docling"]["status"] == "success"
    assert summary["engines"]["paddleocr"]["status"] == "success"


def test_error_isolation_fault_tolerance(synthetic_pdf: Path, tmp_path: Path):
    """
    Verifica que el fallo en un motor NO detenga al otro y genere error.log.
    """
    config = AppConfig()
    engine_success = MockSuccessEngine("docling")
    engine_fail = MockFailingEngine("paddleocr")

    processor = DocumentProcessor(
        config=config,
        docling_engine=engine_success,
        paddleocr_engine=engine_fail,
    )

    summary = processor.process(
        pdf_path=synthetic_pdf,
        custom_output_dir=tmp_path,
        parallel_override=False,
    )

    doc_id = synthetic_pdf.stem
    doc_dir = tmp_path / doc_id

    # El motor exitoso debe haber generado todos sus archivos
    assert (doc_dir / "docling" / f"{doc_id}.json").exists()
    assert summary["engines"]["docling"]["status"] == "success"

    # El motor fallido debe haber generado error.log sin romper el proceso
    error_log = doc_dir / "paddleocr" / "error.log"
    assert error_log.exists()
    assert "Simulated crash" in error_log.read_text(encoding="utf-8")
    assert summary["engines"]["paddleocr"]["status"] == "error"

    # Los metadatos de auditoría deben registrar ambos estados
    assert (doc_dir / "processing_metadata.json").exists()


def test_batch_processor(synthetic_pdf: Path, tmp_path: Path):
    """Prueba el procesamiento en lote sobre un directorio."""
    config = AppConfig()
    engine_mock = MockSuccessEngine("docling")
    doc_proc = DocumentProcessor(config=config, docling_engine=engine_mock)
    batch_proc = BatchProcessor(config=config, document_processor=doc_proc)

    results = batch_proc.process_all(
        input_target=synthetic_pdf.parent,
        custom_output_dir=tmp_path,
        enabled_engines=["docling"],
    )

    assert len(results) >= 1
    assert any(r["document"]["filename"] == synthetic_pdf.name for r in results)
