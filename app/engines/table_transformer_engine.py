"""
Motor especializado Microsoft Table Transformer (TATR) para reconocimiento de estructura de tablas.
Utiliza 'microsoft/table-transformer-structure-recognition' exclusivamente sobre el recorte de la tabla
para detectar filas, columnas, encabezados y celdas combinadas sin rehacer el OCR de texto.
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from PIL import Image

from app.core.config import TableTransformerConfig
from app.core.logger import get_logger
from app.core.models import BoundingBox

logger = get_logger("TableTransformerEngine")


@dataclass
class PredictedCell:
    row_idx: int
    col_idx: int
    bbox: BoundingBox
    row_span: int = 1
    col_span: int = 1
    is_header: bool = False
    confidence: float = 1.0


@dataclass
class PredictedTableStructure:
    num_rows: int
    num_cols: int
    row_bboxes: List[BoundingBox]
    col_bboxes: List[BoundingBox]
    cells: List[List[PredictedCell]]
    average_confidence: float = 0.0
    raw_detections: List[Dict[str, Any]] = field(default_factory=list)


class TableTransformerEngine:
    """
    Wrapper para Microsoft Table Transformer Structure Recognition.
    Carga diferida (lazy loading) para proteger RAM/VRAM.
    """

    def __init__(self, config: Optional[TableTransformerConfig] = None):
        self.config = config or TableTransformerConfig()
        self._model = None
        self._processor = None
        self._device = None

    def _ensure_loaded(self):
        """Inicializa el modelo y procesador bajo demanda."""
        if self._model is not None:
            return

        import torch
        from transformers import AutoImageProcessor, TableTransformerForObjectDetection

        if self.config.device == "auto":
            device_str = "cuda" if torch.cuda.is_available() else "cpu"
        else:
            device_str = self.config.device

        self._device = torch.device(device_str)
        logger.info(f"Cargando Table Transformer '{self.config.model_name}' en {self._device}...")

        self._processor = AutoImageProcessor.from_pretrained(self.config.model_name)
        self._model = TableTransformerForObjectDetection.from_pretrained(self.config.model_name)
        self._model.to(self._device)
        self._model.eval()
        logger.info("Table Transformer cargado exitosamente.")

    def render_and_crop_table(
        self,
        pdf_path: Path,
        page_number: int,
        table_bbox: Optional[BoundingBox] = None,
        padding: float = 8.0,
    ) -> Tuple[Image.Image, float, float, float, float]:
        """
        Renderiza la página del PDF usando pypdfium2 y recorta el área de la tabla.
        Devuelve (imagen_recortada, crop_x0, crop_y0, scale_x, scale_y).
        """
        import pypdfium2 as pdfium

        doc = pdfium.PdfDocument(str(pdf_path))
        # page_number es 1-indexado
        page_idx = max(0, min(page_number - 1, len(doc) - 1))
        page = doc[page_idx]

        page_w = page.get_width()
        page_h = page.get_height()

        # Renderizar a resolución estándar de análisis (150 DPI ~ escala 2.08)
        scale = 2.0
        bitmap = page.render(scale=scale)
        pil_img = bitmap.to_pil()

        img_w, img_h = pil_img.size
        scale_x = img_w / page_w
        scale_y = img_h / page_h

        if table_bbox is None:
            return pil_img, 0.0, 0.0, scale_x, scale_y

        # Convertir bbox en puntos a píxeles en la imagen
        px0 = max(0.0, (table_bbox.x0 - padding) * scale_x)
        py0 = max(0.0, (table_bbox.y0 - padding) * scale_y)
        px1 = min(float(img_w), (table_bbox.x1 + padding) * scale_x)
        py1 = min(float(img_h), (table_bbox.y1 + padding) * scale_y)

        if px1 <= px0 or py1 <= py0:
            return pil_img, 0.0, 0.0, scale_x, scale_y

        cropped = pil_img.crop((int(px0), int(py0), int(px1), int(py1)))
        return cropped, px0, py0, scale_x, scale_y

    def predict_structure(
        self,
        pdf_path: Path,
        page_number: int,
        table_bbox: Optional[BoundingBox] = None,
    ) -> Optional[PredictedTableStructure]:
        """
        Ejecuta Table Transformer sobre el recorte de la tabla y devuelve la estructura predicha.
        """
        try:
            self._ensure_loaded()
        except Exception as e:
            logger.error(f"No se pudo cargar Table Transformer: {e}", exc_info=True)
            return None

        import torch

        # 1. Obtener imagen recortada de la tabla
        cropped_img, crop_px0, crop_py0, scale_x, scale_y = self.render_and_crop_table(
            pdf_path, page_number, table_bbox
        )

        crop_w, crop_h = cropped_img.size
        if crop_w < 10 or crop_h < 10:
            logger.warning("Recorte de tabla inválido o demasiado pequeño.")
            return None

        # 2. Inferencia con Table Transformer
        try:
            inputs = self._processor(images=cropped_img, return_tensors="pt").to(self._device)
            with torch.no_grad():
                outputs = self._model(**inputs)

            # Post-procesar detecciones con tamaño original de la imagen recortada
            target_sizes = torch.tensor([[crop_h, crop_w]], device=self._device)
            results = self._processor.post_process_object_detection(
                outputs, threshold=self.config.threshold, target_sizes=target_sizes
            )[0]
        except Exception as e:
            logger.error(f"Error durante inferencia de Table Transformer: {e}", exc_info=True)
            return None

        scores = results["scores"].tolist()
        labels = results["labels"].tolist()
        boxes = results["boxes"].tolist()

        # Mapeo de etiquetas del modelo
        id2label = self._model.config.id2label

        detected_rows: List[Tuple[float, float, float, float, float]] = []  # (y0, x0, y1, x1, score)
        detected_cols: List[Tuple[float, float, float, float, float]] = []  # (x0, y0, x1, y1, score)
        detected_headers: List[Tuple[float, float, float, float]] = []
        raw_detections = []

        for score, label_id, box in zip(scores, labels, boxes):
            label_name = id2label.get(label_id, str(label_id)).lower()
            bx0, by0, bx1, by1 = box
            raw_detections.append({
                "label": label_name,
                "score": round(score, 3),
                "box": [round(bx0, 1), round(by0, 1), round(bx1, 1), round(by1, 1)],
            })

            # Convertir coordenadas locales del recorte a coordenadas globales de la página PDF en puntos
            pdf_x0 = (crop_px0 + bx0) / scale_x
            pdf_y0 = (crop_py0 + by0) / scale_y
            pdf_x1 = (crop_px0 + bx1) / scale_x
            pdf_y1 = (crop_py0 + by1) / scale_y

            if "row" in label_name:
                detected_rows.append((pdf_y0, pdf_x0, pdf_y1, pdf_x1, score))
            elif "column" in label_name:
                detected_cols.append((pdf_x0, pdf_y0, pdf_x1, pdf_y1, score))
            elif "header" in label_name:
                detected_headers.append((pdf_x0, pdf_y0, pdf_x1, pdf_y1))

        if not detected_rows or not detected_cols:
            logger.warning(
                f"Table Transformer no detectó suficientes filas ({len(detected_rows)}) o columnas ({len(detected_cols)})"
            )
            return None

        # 3. Ordenar filas de arriba hacia abajo y columnas de izquierda a derecha
        detected_rows.sort(key=lambda r: r[0])  # Ordenar por y0
        detected_cols.sort(key=lambda c: c[0])  # Ordenar por x0

        # Crear BoundingBox canónicos para filas y columnas
        row_bboxes: List[BoundingBox] = []
        for ry0, rx0, ry1, rx1, _ in detected_rows:
            row_bboxes.append(BoundingBox(x0=rx0, y0=ry0, x1=rx1, y1=ry1, page=page_number))

        col_bboxes: List[BoundingBox] = []
        for cx0, cy0, cx1, cy1, _ in detected_cols:
            col_bboxes.append(BoundingBox(x0=cx0, y0=cy0, x1=cx1, y1=cy1, page=page_number))

        num_rows = len(row_bboxes)
        num_cols = len(col_bboxes)

        # 4. Construir matriz canónica de celdas por intersección espacial de filas y columnas
        grid_cells: List[List[PredictedCell]] = []
        for r_idx, r_box in enumerate(row_bboxes):
            current_row: List[PredictedCell] = []
            for c_idx, c_box in enumerate(col_bboxes):
                # La celda es la intersección espacial de la fila y la columna
                cell_x0 = c_box.x0
                cell_x1 = c_box.x1
                cell_y0 = r_box.y0
                cell_y1 = r_box.y1

                # Determinar si es encabezado (primera fila o intersección con detected_headers)
                is_header = r_idx == 0
                if not is_header and detected_headers:
                    for hx0, hy0, hx1, hy1 in detected_headers:
                        if cell_y0 >= hy0 - 2.0 and cell_y1 <= hy1 + 2.0:
                            is_header = True
                            break

                pred_cell = PredictedCell(
                    row_idx=r_idx,
                    col_idx=c_idx,
                    bbox=BoundingBox(
                        x0=cell_x0,
                        y0=cell_y0,
                        x1=cell_x1,
                        y1=cell_y1,
                        page=page_number,
                    ),
                    row_span=1,
                    col_span=1,
                    is_header=is_header,
                    confidence=1.0,
                )
                current_row.append(pred_cell)
            grid_cells.append(current_row)

        avg_conf = sum(scores) / len(scores) if scores else 0.0

        return PredictedTableStructure(
            num_rows=num_rows,
            num_cols=num_cols,
            row_bboxes=row_bboxes,
            col_bboxes=col_bboxes,
            cells=grid_cells,
            average_confidence=avg_conf,
            raw_detections=raw_detections,
        )
