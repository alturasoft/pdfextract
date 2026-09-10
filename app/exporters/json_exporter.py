"""
Exportador a formato JSON (.json).
Serializa el modelo maestro DocumentModel conservando estructura documental completa,
tablas (filas, columnas, celdas combinadas, encabezados), coordenadas espaciales (bbox),
orden de lectura, bloques semánticos RAG y metadatos de auditoría.
"""

import json
from pathlib import Path

from app.engines.base import ExtractionResult
from app.exporters.base import BaseExporter


class JsonExporter(BaseExporter):
    """
    Exportador de la representación JSON de máxima fidelidad y riqueza estructural.
    """

    @property
    def format_name(self) -> str:
        return "json"

    def export(self, result: ExtractionResult, output_dir: Path, base_filename: str) -> Path:
        """
        Genera el archivo .json estructurado en el directorio de salida.
        """
        output_dir.mkdir(parents=True, exist_ok=True)
        target_path = output_dir / f"{base_filename}.json"

        # Serialización canónica a dict usando el modelo Pydantic
        doc_dict = result.document.model_dump(mode="json")

        # Organización jerárquica clara para auditoría y consumo por sistemas externos
        structured_output = {
            "document": {
                "document_id": doc_dict["metadata"]["document_id"],
                "filename": doc_dict["metadata"]["filename"],
                "total_pages": doc_dict["metadata"]["total_pages"],
                "file_hash_sha256": doc_dict["metadata"]["file_hash_sha256"],
                "file_size_bytes": doc_dict["metadata"]["file_size_bytes"],
            },
            "extraction": {
                "engine": result.engine_name,
                "engine_version": doc_dict["metadata"]["engine_version"],
                "processing_time_seconds": doc_dict["metadata"]["processing_time_seconds"],
                "created_at": doc_dict["metadata"]["created_at"],
                "status": doc_dict["metadata"]["status"],
                "error_message": doc_dict["metadata"]["error_message"],
            },
            "pages": doc_dict.get("pages", []),
            "sections": doc_dict.get("sections", []),
            "texts": doc_dict.get("texts", []),
            "tables": doc_dict.get("tables", []),
            "rag_chunks": doc_dict.get("rag_chunks", []),
            "raw_engine_data": doc_dict.get("raw_engine_data", {}),
        }

        with open(target_path, "w", encoding="utf-8") as f:
            json.dump(structured_output, f, ensure_ascii=False, indent=2)

        return target_path
