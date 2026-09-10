"""
Motor de extracción e inteligencia documental basado en Docling (IBM Granite).
Especializado en análisis de layout, jerarquía de lectura, OCR adaptativo y
reconstrucción de alta precisión para tablas complejas de seguros.
"""

import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.core.config import DoclingEngineConfig
from app.core.logger import get_logger
from app.core.models import (
    BoundingBox,
    Cell,
    DocumentMetadata,
    DocumentModel,
    Page,
    RAGChunk,
    Table,
    TextElement,
)
from app.core.system_info import get_installed_version
from app.engines.base import BaseExtractionEngine, ExtractionResult
from app.utils.file_utils import calculate_sha256, normalize_document_id

logger = get_logger("DoclingEngine")


class DoclingEngine(BaseExtractionEngine):
    """
    Implementación del motor de extracción utilizando la biblioteca Docling.
    """

    def __init__(self, config: Optional[DoclingEngineConfig] = None):
        self.config = config or DoclingEngineConfig()
        self._version = get_installed_version("docling")

    @property
    def name(self) -> str:
        return "docling"

    def is_available(self) -> bool:
        """Comprueba si Docling está instalado en el entorno."""
        try:
            import docling
            return True
        except ImportError:
            return False

    def _build_converter(self, is_native_document: bool = False):
        """Configura e inicializa el DocumentConverter con las opciones deseadas."""
        from docling.datamodel.base_models import InputFormat
        from docling.datamodel.pipeline_options import (
            PdfPipelineOptions,
            TableFormerMode,
            TableStructureOptions,
        )
        from docling.document_converter import DocumentConverter, PdfFormatOption

        pipeline_options = PdfPipelineOptions()

        # Configuración de OCR: evitar OCR innecesario en documentos nativos (Regla 4 del prompt)
        if self.config.force_ocr:
            pipeline_options.do_ocr = True
        elif is_native_document:
            pipeline_options.do_ocr = False
        else:
            pipeline_options.do_ocr = self.config.ocr_enabled

        if hasattr(pipeline_options, "force_backend_text"):
            pipeline_options.force_backend_text = not self.config.force_ocr

        # Configuración profunda de tablas
        pipeline_options.do_table_structure = self.config.do_table_structure
        table_mode = TableFormerMode.ACCURATE if self.config.table_mode == "accurate" else TableFormerMode.FAST
        pipeline_options.table_structure_options = TableStructureOptions(mode=table_mode)

        converter = DocumentConverter(
            format_options={
                InputFormat.PDF: PdfFormatOption(pipeline_options=pipeline_options)
            }
        )
        return converter

    def _convert_bbox(self, docling_bbox: Any, page_num: int) -> Optional[BoundingBox]:
        """Convierte una caja delimitadora de Docling al modelo canónico BoundingBox."""
        if not docling_bbox:
            return None

        try:
            origin_name = "TOP_LEFT"
            if hasattr(docling_bbox, "coord_origin"):
                origin_name = getattr(docling_bbox.coord_origin, "name", str(docling_bbox.coord_origin))

            return BoundingBox(
                x0=float(docling_bbox.l),
                y0=float(docling_bbox.t),
                x1=float(docling_bbox.r),
                y1=float(docling_bbox.b),
                page=page_num,
                coord_origin=origin_name,
            )
        except Exception as e:
            logger.debug(f"No se pudo parsear el bbox de Docling: {e}")
            return None

    def _map_to_canonical_model(
        self,
        docling_doc: Any,
        pdf_path: Path,
        processing_time: float,
    ) -> DocumentModel:
        """
        Mapea el árbol nativo de DoclingDocument a nuestro DocumentModel canónico.
        """
        doc_id = normalize_document_id(pdf_path)
        sha256_hash = calculate_sha256(pdf_path)
        file_size = pdf_path.stat().st_size

        # 1. Metadatos de ejecución
        total_pages = len(docling_doc.pages) if hasattr(docling_doc, "pages") else 1
        metadata = DocumentMetadata(
            document_id=doc_id,
            filename=pdf_path.name,
            file_size_bytes=file_size,
            file_hash_sha256=sha256_hash,
            total_pages=total_pages,
            engine_name=self.name,
            engine_version=self._version,
            processing_time_seconds=round(processing_time, 2),
            status="success",
        )

        # 2. Extracción de textos con orden de lectura y coordenadas
        canonical_texts: List[TextElement] = []
        raw_texts = getattr(docling_doc, "texts", [])

        for idx, item in enumerate(raw_texts):
            text_val = getattr(item, "text", "")
            if not text_val.strip():
                continue

            raw_label = getattr(item, "label", "paragraph")
            label_str = getattr(raw_label, "value", str(raw_label)).lower()

            # Normalizar tipo documental
            if "title" in label_str:
                elem_type = "title"
            elif "header" in label_str or "heading" in label_str:
                elem_type = "section_header"
            elif "list" in label_str:
                elem_type = "list_item"
            elif "caption" in label_str:
                elem_type = "caption"
            elif "footnote" in label_str:
                elem_type = "footnote"
            else:
                elem_type = "paragraph"

            # Coordenadas y página de procedencia (provenance)
            page_no = 1
            bbox_obj = None
            if hasattr(item, "prov") and item.prov:
                first_prov = item.prov[0]
                page_no = getattr(first_prov, "page_no", 1)
                bbox_obj = self._convert_bbox(getattr(first_prov, "bbox", None), page_no)

            elem_id = f"text_{idx:04d}"
            canonical_texts.append(
                TextElement(
                    element_id=elem_id,
                    type=elem_type,
                    text=text_val,
                    bbox=bbox_obj,
                    page=page_no,
                    reading_order=idx,
                )
            )

        # 3. Extracción de tablas estructuradas (celdas, rowspan, colspan, headers)
        canonical_tables: List[Table] = []
        raw_tables = getattr(docling_doc, "tables", [])

        for t_idx, t_item in enumerate(raw_tables):
            table_id = f"table_{t_idx:03d}"
            data = getattr(t_item, "data", None)
            if not data or not hasattr(data, "grid"):
                continue

            # Determinar páginas que abarca la tabla
            pages_involved = set()
            if hasattr(t_item, "prov") and t_item.prov:
                for p in t_item.prov:
                    pages_involved.add(getattr(p, "page_no", 1))

            page_start = min(pages_involved) if pages_involved else 1
            page_end = max(pages_involved) if pages_involved else page_start
            is_multipage = (page_end > page_start)

            # Bounding box global de la tabla
            table_bbox = None
            if hasattr(t_item, "prov") and t_item.prov:
                table_bbox = self._convert_bbox(getattr(t_item.prov[0], "bbox", None), page_start)

            # Matriz de celdas
            table_rows: List[List[Cell]] = []
            extracted_headers: List[str] = []

            for r_idx, row in enumerate(data.grid):
                canonical_row: List[Cell] = []
                for c_idx, cell in enumerate(row):
                    cell_text = getattr(cell, "text", "")
                    row_span = getattr(cell, "row_span", 1)
                    col_span = getattr(cell, "col_span", 1)
                    is_col_header = getattr(cell, "column_header", False)
                    is_row_header = getattr(cell, "row_header", False)
                    is_hdr = bool(is_col_header or is_row_header or r_idx == 0)

                    cell_bbox = self._convert_bbox(getattr(cell, "bbox", None), page_start)

                    canonical_cell = Cell(
                        text=cell_text,
                        row_index=r_idx,
                        col_index=c_idx,
                        row_span=row_span,
                        col_span=col_span,
                        is_header=is_hdr,
                        bbox=cell_bbox,
                    )
                    canonical_row.append(canonical_cell)

                    if r_idx == 0:
                        extracted_headers.append(cell_text.strip())

                table_rows.append(canonical_row)

            caption = ""
            if hasattr(t_item, "caption_text"):
                caption = t_item.caption_text(docling_doc) or ""

            canonical_tables.append(
                Table(
                    table_id=table_id,
                    page_start=page_start,
                    page_end=page_end,
                    num_rows=len(table_rows),
                    num_cols=len(table_rows[0]) if table_rows else 0,
                    headers=extracted_headers,
                    rows=table_rows,
                    bbox=table_bbox,
                    caption=caption or None,
                    is_multipage=is_multipage,
                )
            )

        # 4. Estructuración por páginas
        canonical_pages: List[Page] = []
        doc_pages_dict = getattr(docling_doc, "pages", {})

        for p_no in range(1, total_pages + 1):
            page_obj = doc_pages_dict.get(p_no)
            width, height = 0.0, 0.0
            if page_obj and hasattr(page_obj, "size"):
                width = float(getattr(page_obj.size, "width", 0.0))
                height = float(getattr(page_obj.size, "height", 0.0))

            # Filtrar elementos y tablas pertenecientes a esta página
            page_elements = [e for e in canonical_texts if e.page == p_no]
            page_tables = [t for t in canonical_tables if t.page_start <= p_no <= t.page_end]
            page_text_consolidated = "\n".join(e.text for e in page_elements)

            canonical_pages.append(
                Page(
                    page_number=p_no,
                    width=width,
                    height=height,
                    is_scanned=False,  # Evaluado contextualmente
                    has_native_text=len(page_text_consolidated.strip()) > 50,
                    elements=page_elements,
                    tables=page_tables,
                    raw_text=page_text_consolidated,
                )
            )

        # 5. Generación de chunks RAG semánticos con trazabilidad
        rag_chunks: List[RAGChunk] = []
        current_section = "General"
        current_chunk_texts: List[str] = []
        current_bboxes: List[BoundingBox] = []
        chunk_start_page = 1

        for elem in canonical_texts:
            if elem.type in ("title", "section_header"):
                if current_chunk_texts:
                    chunk_text = " ".join(current_chunk_texts)
                    rag_chunks.append(
                        RAGChunk(
                            chunk_id=f"{doc_id}_chunk_{len(rag_chunks)+1:03d}",
                            document_id=doc_id,
                            section=current_section,
                            page_start=chunk_start_page,
                            page_end=elem.page,
                            chunk_type="text",
                            text=chunk_text,
                            bboxes=current_bboxes[:],
                            token_estimate=len(chunk_text.split()),
                        )
                    )
                    current_chunk_texts = []
                    current_bboxes = []
                current_section = elem.text.strip()
                chunk_start_page = elem.page
            else:
                current_chunk_texts.append(elem.text)
                if elem.bbox:
                    current_bboxes.append(elem.bbox)

        if current_chunk_texts:
            chunk_text = " ".join(current_chunk_texts)
            rag_chunks.append(
                RAGChunk(
                    chunk_id=f"{doc_id}_chunk_{len(rag_chunks)+1:03d}",
                    document_id=doc_id,
                    section=current_section,
                    page_start=chunk_start_page,
                    page_end=total_pages,
                    chunk_type="text",
                    text=chunk_text,
                    bboxes=current_bboxes,
                    token_estimate=len(chunk_text.split()),
                )
            )

        # Chunks específicos para tablas
        for tbl in canonical_tables:
            tbl_text = f"Tabla de póliza ({tbl.caption or 'Sin título'}):\n"
            tbl_text += " | ".join(tbl.headers) + "\n"
            for row in tbl.rows:
                tbl_text += " | ".join(c.text for c in row) + "\n"

            tbl_bboxes = [tbl.bbox] if tbl.bbox else []
            rag_chunks.append(
                RAGChunk(
                    chunk_id=f"{doc_id}_chunk_{len(rag_chunks)+1:03d}",
                    document_id=doc_id,
                    section=current_section,
                    page_start=tbl.page_start,
                    page_end=tbl.page_end,
                    chunk_type="table",
                    text=tbl_text.strip(),
                    bboxes=tbl_bboxes,
                    token_estimate=len(tbl_text.split()),
                )
            )

        # 6. Salida cruda completa del motor para evitar cualquier pérdida de datos
        raw_dict = {}
        try:
            raw_dict = docling_doc.export_to_dict()
        except Exception as e:
            logger.debug(f"No se pudo serializar export_to_dict de Docling: {e}")

        # Añadir exportaciones nativas adicionales
        try:
            raw_dict["markdown_text"] = docling_doc.export_to_markdown()
        except Exception:
            pass

        try:
            raw_dict["plain_text"] = docling_doc.export_to_text()
        except Exception:
            pass

        return DocumentModel(
            metadata=metadata,
            pages=canonical_pages,
            sections=[],
            texts=canonical_texts,
            tables=canonical_tables,
            rag_chunks=rag_chunks,
            raw_engine_data=raw_dict,
        )

    def extract(self, pdf_path: Path) -> ExtractionResult:
        """
        Ejecuta la extracción documental completa con Docling.
        Garantiza tolerancia a fallos devolviendo un ExtractionResult con error sin romper el pipeline.
        """
        logger.info(f"[{self.name.upper()}] Iniciando extracción para: {pdf_path.name}")
        start_time = time.perf_counter()

        if not pdf_path.exists():
            return ExtractionResult(
                engine_name=self.name,
                document=DocumentModel(
                    metadata=DocumentMetadata(
                        document_id=normalize_document_id(pdf_path),
                        filename=pdf_path.name,
                        engine_name=self.name,
                        status="error",
                        error_message=f"Archivo no encontrado: {pdf_path}",
                    )
                ),
                processing_time_seconds=0.0,
                status="error",
                error_message=f"Archivo no encontrado: {pdf_path}",
            )

        try:
            from app.utils.pdf_utils import inspect_pdf_pages
            doc_type, _ = inspect_pdf_pages(pdf_path)
            is_native = (doc_type == "native")

            converter = self._build_converter(is_native_document=is_native)
            conv_result = converter.convert(str(pdf_path))
            docling_doc = conv_result.document
            elapsed = time.perf_counter() - start_time

            canonical_doc = self._map_to_canonical_model(
                docling_doc=docling_doc,
                pdf_path=pdf_path,
                processing_time=elapsed,
            )

            logger.info(
                f"[{self.name.upper()}] Finalizado con éxito en {elapsed:.2f}s "
                f"({len(canonical_doc.pages)} páginas, {len(canonical_doc.tables)} tablas)"
            )

            return ExtractionResult(
                engine_name=self.name,
                document=canonical_doc,
                processing_time_seconds=round(elapsed, 2),
                status="success",
                raw_output=canonical_doc.raw_engine_data,
            )

        except Exception as e:
            elapsed = time.perf_counter() - start_time
            error_msg = f"Error durante la extracción con Docling: {str(e)}"
            logger.error(f"[{self.name.upper()}] {error_msg}", exc_info=True)

            fallback_doc = DocumentModel(
                metadata=DocumentMetadata(
                    document_id=normalize_document_id(pdf_path),
                    filename=pdf_path.name,
                    engine_name=self.name,
                    engine_version=self._version,
                    processing_time_seconds=round(elapsed, 2),
                    status="error",
                    error_message=error_msg,
                )
            )

            return ExtractionResult(
                engine_name=self.name,
                document=fallback_doc,
                processing_time_seconds=round(elapsed, 2),
                status="error",
                error_message=error_msg,
            )
