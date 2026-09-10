"""
Motor de extracción e inteligencia documental basado en PaddleOCR / PP-Structure.
Integra detección de layout (PicoDet), reconocimiento y reconstrucción de tablas complejas (SLANet)
y OCR de alta resolución (PP-OCR), generando modelos canónicos, coordenadas espaciales y Markdown estructurado.
"""

import importlib
import importlib.util
import re
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
from bs4 import BeautifulSoup
from PIL import Image

from app.core.config import PaddleOCREngineConfig
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

logger = get_logger("PaddleOCREngine")


class PaddleOCRVLEngine(BaseExtractionEngine):
    """
    Implementación del motor PaddleOCR / PP-Structure para análisis documental estructurado.
    """

    def __init__(self, config: Optional[PaddleOCREngineConfig] = None):
        self.config = config or PaddleOCREngineConfig()
        self._ocr_engine = None
        self._layout_engine = None
        self._table_engine = None
        self._version = get_installed_version("rapidocr")
        if self._version == "not_installed":
            self._version = get_installed_version("paddleocr")
        if self._version == "not_installed":
            self._version = "2.8"

    @property
    def name(self) -> str:
        return "paddleocr"

    def is_available(self) -> bool:
        """Comprueba disponibilidad de rapidocr, rapid_table, rapid_layout o paddleocr."""
        for pkg in ["rapidocr", "rapid_table", "rapid_layout", "paddleocr", "pypdfium2"]:
            try:
                if importlib.util.find_spec(pkg) is not None:
                    return True
            except Exception:
                pass
        return False

    def _determine_device(self) -> str:
        """Determina el dispositivo óptimo (CUDA si está disponible y configurado, sino CPU)."""
        if self.config.device != "auto":
            return self.config.device

        try:
            import torch
            if torch.cuda.is_available():
                return "cuda"
        except Exception:
            pass

        return "cpu"

    def _get_page_dimensions(self, pdf_path: Path) -> List[Tuple[float, float]]:
        """Obtiene las dimensiones (ancho, alto) en puntos de cada página."""
        try:
            import pypdfium2 as pdfium
            pdf = pdfium.PdfDocument(str(pdf_path))
            return [page.get_size() for page in pdf]
        except Exception:
            from pypdf import PdfReader
            reader = PdfReader(str(pdf_path))
            dims = []
            for page in reader.pages:
                box = page.mediabox
                dims.append((float(box.width), float(box.height)))
            return dims

    def _render_page_image(self, pdf_path: Path, page_index: int, dpi: int = 150) -> Image.Image:
        """Renderiza una página específica a imagen PIL para OCR y análisis visual."""
        import pypdfium2 as pdfium
        pdf = pdfium.PdfDocument(str(pdf_path))
        page = pdf[page_index]
        scale = dpi / 72.0
        return page.render(scale=scale).to_pil().convert("RGB")

    def _init_engines(self):
        """Inicializa los motores de OCR, Layout y Reconstrucción de Tablas (PP-Structure)."""
        # 1. Motor OCR
        if self._ocr_engine is None:
            try:
                from rapidocr import RapidOCR
                self._ocr_engine = RapidOCR()
                logger.debug(f"[{self.name.upper()}] Motor RapidOCR inicializado.")
            except Exception as e:
                logger.debug(f"RapidOCR no disponible: {e}")
                try:
                    paddle_mod = importlib.import_module("paddleocr")
                    PaddleOCRClass = getattr(paddle_mod, "PaddleOCR")
                    use_gpu = (self._determine_device() == "cuda")
                    self._ocr_engine = PaddleOCRClass(use_angle_cls=True, lang=self.config.lang, use_gpu=use_gpu)
                except Exception as pe:
                    logger.warning(f"[{self.name.upper()}] No se pudo inicializar motor OCR: {pe}")

        # 2. Motor de Layout (PicoDet / PP-Structure Layout)
        if self._layout_engine is None and self.config.use_layout:
            try:
                from rapid_layout import RapidLayout
                self._layout_engine = RapidLayout()
                logger.debug(f"[{self.name.upper()}] Motor RapidLayout (PicoDet) inicializado.")
            except Exception as e:
                logger.debug(f"RapidLayout no disponible: {e}")

        # 3. Motor de Tablas (SLANet / PP-Structure Table)
        if self._table_engine is None and self.config.use_table:
            try:
                from rapid_table import RapidTable
                self._table_engine = RapidTable()
                logger.debug(f"[{self.name.upper()}] Motor RapidTable (SLANet) inicializado.")
            except Exception as e:
                logger.debug(f"RapidTable no disponible: {e}")

    def _parse_html_table(
        self,
        html_str: str,
        page_num: int,
        table_idx: int,
        table_bbox: Optional[BoundingBox] = None,
    ) -> Optional[Tuple[Table, str]]:
        """
        Parsea tablas en formato HTML generadas por SLANet / PP-Structure
        y genera simultáneamente el modelo canónico Table y la representación Markdown.
        """
        try:
            soup = BeautifulSoup(html_str, "html.parser")
            table_tag = soup.find("table")
            if not table_tag:
                return None

            tr_tags = table_tag.find_all("tr")
            if not tr_tags:
                return None

            table_rows: List[List[Cell]] = []
            extracted_headers: List[str] = []
            valid_rows_count = 0

            for r_idx, tr in enumerate(tr_tags):
                cells_in_row: List[Cell] = []
                th_td_tags = tr.find_all(["th", "td"])

                row_has_content = False
                for c_idx, cell_tag in enumerate(th_td_tags):
                    cell_text = cell_tag.get_text(separator=" ", strip=True)
                    if cell_text:
                        row_has_content = True

                    r_span = int(cell_tag.get("rowspan", 1))
                    c_span = int(cell_tag.get("colspan", 1))
                    is_header = (cell_tag.name == "th" or r_idx == 0)

                    cells_in_row.append(
                        Cell(
                            text=cell_text,
                            row_index=valid_rows_count,
                            col_index=c_idx,
                            row_span=r_span,
                            col_span=c_span,
                            is_header=is_header,
                        )
                    )

                    if is_header and valid_rows_count == 0 and cell_text:
                        extracted_headers.append(cell_text)

                if cells_in_row and row_has_content:
                    table_rows.append(cells_in_row)
                    valid_rows_count += 1

            if not table_rows:
                return None

            num_cols = max(len(r) for r in table_rows)
            if num_cols == 0:
                return None

            # Generar sintaxis Markdown (| col1 | col2 |)
            md_lines: List[str] = []
            # Cabecera Markdown
            first_row_cells = [c.text.replace("|", "\\|").replace("\n", " ").strip() for c in table_rows[0]]
            while len(first_row_cells) < num_cols:
                first_row_cells.append("")
            # Asegurar encabezados no vacíos
            for i, h in enumerate(first_row_cells):
                if not h:
                    first_row_cells[i] = f"Columna {i+1}"

            md_lines.append("| " + " | ".join(first_row_cells) + " |")
            md_lines.append("| " + " | ".join(["---"] * num_cols) + " |")

            for row in table_rows[1:]:
                row_vals = [c.text.replace("|", "\\|").replace("\n", " ").strip() for c in row]
                while len(row_vals) < num_cols:
                    row_vals.append("")
                md_lines.append("| " + " | ".join(row_vals) + " |")

            table_md = "\n".join(md_lines)

            canonical_table = Table(
                table_id=f"paddle_tbl_{page_num}_{table_idx:02d}",
                page_start=page_num,
                page_end=page_num,
                num_rows=len(table_rows),
                num_cols=num_cols,
                headers=first_row_cells,
                rows=table_rows,
                bbox=table_bbox,
                caption=f"Tabla {table_idx} (Página {page_num})",
                is_multipage=False,
            )

            return canonical_table, table_md

        except Exception as e:
            logger.debug(f"Error parseando tabla HTML en página {page_num}: {e}")
            return None

    def _ocr_page(
        self,
        pdf_path: Path,
        page_index: int,
        page_w: float,
        page_h: float,
        dpi: int = 150,
    ) -> Tuple[List[TextElement], List[Table], str, str]:
        """
        Ejecuta análisis de layout, OCR y reconstrucción de tablas sobre una página renderizada.
        Retorna (elements, tables, raw_text, markdown_text).
        """
        self._init_engines()
        pil_img = self._render_page_image(pdf_path, page_index, dpi=dpi)
        img_arr = np.array(pil_img)
        scale = dpi / 72.0
        page_num = page_index + 1

        elements: List[TextElement] = []
        tables: List[Table] = []
        table_bboxes_px: List[Tuple[float, float, float, float]] = []
        page_md_blocks: List[Tuple[float, str]] = []  # (y_pos, markdown_str)

        # ----------------------------------------------------------------------
        # 1. Detección y Reconstrucción de Tablas vía PP-Structure (Layout + Table)
        # ----------------------------------------------------------------------
        if self._layout_engine is not None and self._table_engine is not None:
            try:
                layout_res = self._layout_engine(img_arr)
                if hasattr(layout_res, "boxes") and layout_res.boxes is not None and hasattr(layout_res, "class_names"):
                    tbl_counter = 0
                    for box, label, score in zip(layout_res.boxes, layout_res.class_names, layout_res.scores or []):
                        if label == "table" and float(score) >= 0.45:
                            x0_px, y0_px, x1_px, y1_px = [float(v) for v in box]
                            # Margen de seguridad para recorte
                            crop_x0 = max(0, int(x0_px - 4))
                            crop_y0 = max(0, int(y0_px - 4))
                            crop_x1 = min(img_arr.shape[1], int(x1_px + 4))
                            crop_y1 = min(img_arr.shape[0], int(y1_px + 4))

                            if crop_x1 - crop_x0 > 30 and crop_y1 - crop_y0 > 20:
                                table_crop = img_arr[crop_y0:crop_y1, crop_x0:crop_x1]
                                tbl_res = self._table_engine(table_crop)

                                if hasattr(tbl_res, "pred_htmls") and tbl_res.pred_htmls:
                                    html_code = tbl_res.pred_htmls[0]
                                    tbl_bbox = BoundingBox(
                                        x0=round(x0_px / scale, 2),
                                        y0=round(y0_px / scale, 2),
                                        x1=round(x1_px / scale, 2),
                                        y1=round(y1_px / scale, 2),
                                        page=page_num,
                                        coord_origin="TOP_LEFT",
                                    )
                                    parsed_res = self._parse_html_table(html_code, page_num, tbl_counter + 1, tbl_bbox)
                                    if parsed_res:
                                        tbl_obj, tbl_md = parsed_res
                                        tables.append(tbl_obj)
                                        table_bboxes_px.append((x0_px, y0_px, x1_px, y1_px))
                                        page_md_blocks.append((y0_px / scale, "\n" + tbl_md + "\n"))
                                        tbl_counter += 1
            except Exception as e:
                logger.debug(f"[{self.name.upper()}] Error en pipeline de tablas página {page_num}: {e}")

        # ----------------------------------------------------------------------
        # 2. OCR Textual con PP-OCR (RapidOCR)
        # ----------------------------------------------------------------------
        raw_boxes = None
        raw_txts = None
        raw_scores = None

        if self._ocr_engine is not None:
            try:
                ocr_res = self._ocr_engine(img_arr)
                if hasattr(ocr_res, "boxes") and ocr_res.boxes is not None:
                    raw_boxes = ocr_res.boxes
                    raw_txts = ocr_res.txts
                    raw_scores = ocr_res.scores
                elif isinstance(ocr_res, tuple) and len(ocr_res) > 0 and ocr_res[0] is not None:
                    if isinstance(ocr_res[0], (list, tuple, np.ndarray)):
                        raw_boxes = [item[0] for item in ocr_res if len(item) > 0]
                        raw_txts = [item[1][0] if isinstance(item[1], (list, tuple)) else item[1] for item in ocr_res if len(item) > 1]
                        raw_scores = [float(item[1][1]) if isinstance(item[1], (list, tuple)) and len(item[1]) > 1 else 0.95 for item in ocr_res if len(item) > 1]
            except Exception as e:
                logger.error(f"[{self.name.upper()}] Error ejecutando OCR en página {page_num}: {e}")

        if raw_boxes is None or len(raw_boxes) == 0 or raw_txts is None or len(raw_txts) == 0:
            md_output = "\n\n".join([b[1] for b in sorted(page_md_blocks, key=lambda x: x[0])])
            return elements, tables, "", md_output

        # Procesar detecciones y clasificar elementos fuera de tablas
        detected_items = []
        scores_list = list(raw_scores) if raw_scores is not None else [0.95] * len(raw_boxes)

        for box, txt, score in zip(raw_boxes, raw_txts, scores_list):
            txt_clean = str(txt).strip()
            if not txt_clean:
                continue

            pts = np.array(box)
            min_x_px = float(np.min(pts[:, 0]))
            max_x_px = float(np.max(pts[:, 0]))
            min_y_px = float(np.min(pts[:, 1]))
            max_y_px = float(np.max(pts[:, 1]))

            cx_px = (min_x_px + max_x_px) / 2.0
            cy_px = (min_y_px + max_y_px) / 2.0

            # Verificar si el texto está contenido dentro de una tabla detectada
            inside_table = False
            for tx0, ty0, tx1, ty1 in table_bboxes_px:
                if (tx0 - 5 <= cx_px <= tx1 + 5) and (ty0 - 5 <= cy_px <= ty1 + 5):
                    inside_table = True
                    break

            min_x = min_x_px / scale
            max_x = max_x_px / scale
            min_y = min_y_px / scale
            max_y = max_y_px / scale

            detected_items.append({
                "text": txt_clean,
                "score": float(score),
                "x0": min_x,
                "y0": min_y,
                "x1": max_x,
                "y1": max_y,
                "inside_table": inside_table,
            })

        # Ordenar elementos textuales de arriba a abajo y de izquierda a derecha
        detected_items.sort(key=lambda item: (round(item["y0"] / 8.0) * 8, item["x0"]))

        page_raw_lines: List[str] = []
        for r_idx, item in enumerate(detected_items):
            txt = item["text"]
            page_raw_lines.append(txt)

            # Clasificación de estructura documental
            is_title = False
            is_header = False

            if item["y0"] < 120 and len(txt) < 80 and (txt.isupper() or "POLIZA" in txt.upper() or "CONDICION" in txt.upper()):
                elem_type = "title"
                is_title = True
            elif (len(txt) < 60 and txt.isupper()) or txt.startswith("#") or txt.endswith(":"):
                elem_type = "section_header"
                is_header = True
            elif txt.startswith(("-", "*", "•")) or re.match(r"^\d+[\.\)]", txt):
                elem_type = "list_item"
            else:
                elem_type = "paragraph"

            elements.append(
                TextElement(
                    element_id=f"paddletxt_{page_num}_{r_idx:03d}",
                    type=elem_type,
                    text=txt,
                    bbox=BoundingBox(
                        x0=round(item["x0"], 2),
                        y0=round(item["y0"], 2),
                        x1=round(item["x1"], 2),
                        y1=round(item["y1"], 2),
                        page=page_num,
                        coord_origin="TOP_LEFT",
                    ),
                    page=page_num,
                    reading_order=r_idx,
                    confidence=round(item["score"], 4),
                )
            )

            # Solo agregar al flujo Markdown si NO está dentro de una tabla ya parseada
            if not item["inside_table"]:
                if is_title:
                    md_text = f"## {txt}\n"
                elif is_header:
                    md_text = f"### {txt}\n"
                elif elem_type == "list_item":
                    md_text = f"- {txt.lstrip('-*• ').strip()}"
                else:
                    md_text = txt

                page_md_blocks.append((item["y0"], md_text))

        # ----------------------------------------------------------------------
        # 3. Consolidación de Markdown en Orden Espacial Natural
        # ----------------------------------------------------------------------
        page_md_blocks.sort(key=lambda b: b[0])
        page_md_content = "\n\n".join([b[1] for b in page_md_blocks if b[1].strip()])

        raw_page_text = "\n".join(page_raw_lines)
        return elements, tables, raw_page_text, page_md_content

    def extract(self, pdf_path: Path) -> ExtractionResult:
        """
        Ejecuta la extracción documental con OCR, Layout y Tablas (PP-Structure).
        """
        logger.info(f"[{self.name.upper()}] Iniciando extracción estructurada para: {pdf_path.name}")
        start_time = time.perf_counter()

        doc_id = normalize_document_id(pdf_path)
        sha256_hash = calculate_sha256(pdf_path)
        file_size = pdf_path.stat().st_size

        if not pdf_path.exists():
            error_msg = f"Archivo no encontrado: {pdf_path}"
            return ExtractionResult(
                engine_name=self.name,
                document=DocumentModel(
                    metadata=DocumentMetadata(
                        document_id=doc_id,
                        filename=pdf_path.name,
                        engine_name=self.name,
                        status="error",
                        error_message=error_msg,
                    )
                ),
                processing_time_seconds=0.0,
                status="error",
                error_message=error_msg,
            )

        try:
            page_dimensions = self._get_page_dimensions(pdf_path)
            total_pages = len(page_dimensions)
            logger.info(f"[{self.name.upper()}] {total_pages} páginas detectadas para análisis.")

            canonical_pages: List[Page] = []
            canonical_texts: List[TextElement] = []
            canonical_tables: List[Table] = []
            rag_chunks: List[RAGChunk] = []
            all_page_md: List[str] = []

            for p_idx, (w_pts, h_pts) in enumerate(page_dimensions):
                p_num = p_idx + 1
                logger.info(f"[{self.name.upper()}] Procesando página {p_num}/{total_pages} (Layout + Tablas + OCR)...")

                elements, tables, raw_text, md_text = self._ocr_page(pdf_path, p_idx, w_pts, h_pts)

                canonical_texts.extend(elements)
                canonical_tables.extend(tables)

                # Formatear separador de página en Markdown
                page_md_header = f"<!-- Página {p_num} -->\n"
                all_page_md.append(page_md_header + md_text)

                canonical_pages.append(
                    Page(
                        page_number=p_num,
                        width=w_pts,
                        height=h_pts,
                        is_scanned=True,
                        has_native_text=False,
                        elements=elements,
                        tables=tables,
                        raw_text=raw_text,
                    )
                )

                # Chunks para RAG de texto y tablas
                if md_text.strip():
                    rag_chunks.append(
                        RAGChunk(
                            chunk_id=f"{doc_id}_paddle_chunk_{p_num:03d}",
                            document_id=doc_id,
                            section=f"Página {p_num}",
                            page_start=p_num,
                            page_end=p_num,
                            chunk_type="text",
                            text=md_text.strip(),
                            bboxes=[e.bbox for e in elements if e.bbox],
                            token_estimate=len(md_text.split()),
                        )
                    )

            elapsed = time.perf_counter() - start_time

            # Raw output estructurado con Markdown de alta riqueza
            markdown_full_document = "\n\n---\n\n".join(all_page_md)
            raw_output = {
                "engine": "paddleocr-ppstructure",
                "model_version": self._version,
                "device": self._determine_device(),
                "markdown_text": markdown_full_document,
                "pages_data": [
                    {
                        "page": p.page_number,
                        "text": p.raw_text,
                        "elements_count": len(p.elements),
                        "tables_count": len(p.tables),
                    }
                    for p in canonical_pages
                ],
            }

            metadata = DocumentMetadata(
                document_id=doc_id,
                filename=pdf_path.name,
                file_size_bytes=file_size,
                file_hash_sha256=sha256_hash,
                total_pages=total_pages,
                engine_name="paddleocr",
                engine_version=self._version,
                processing_time_seconds=round(elapsed, 2),
                status="success",
            )

            canonical_doc = DocumentModel(
                metadata=metadata,
                pages=canonical_pages,
                sections=[],
                texts=canonical_texts,
                tables=canonical_tables,
                rag_chunks=rag_chunks,
                raw_engine_data=raw_output,
            )

            logger.info(
                f"[{self.name.upper()}] Finalizado con éxito en {elapsed:.2f}s "
                f"({len(canonical_pages)} páginas, {len(canonical_texts)} textos, {len(canonical_tables)} tablas estructuradas)"
            )

            return ExtractionResult(
                engine_name=self.name,
                document=canonical_doc,
                processing_time_seconds=round(elapsed, 2),
                status="success",
                raw_output=raw_output,
            )

        except Exception as e:
            elapsed = time.perf_counter() - start_time
            error_msg = f"Error durante la extracción con PaddleOCR-PPStructure: {str(e)}"
            logger.error(f"[{self.name.upper()}] {error_msg}", exc_info=True)

            fallback_doc = DocumentModel(
                metadata=DocumentMetadata(
                    document_id=doc_id,
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
