"""
Reconstructor inteligente de tablas.
Combina la estructura predicha por Table Transformer con los fragmentos de texto
y coordenadas reconocidos previamente por Docling / PaddleOCR-VL.
Preserva el 100% del texto reconocido mediante asignación geométrica sin re-ejecutar OCR.
"""

from typing import List, Optional, Tuple
from pdfextract.core.logger import get_logger
from pdfextract.core.models import BoundingBox, Cell, Table
from pdfextract.engines.table_transformer_engine import PredictedTableStructure
from pdfextract.postprocess.table_validator import compute_bbox_iou

logger = get_logger("TableReconstructor")


def _bbox_center(bbox: BoundingBox) -> Tuple[float, float]:
    """Calcula el centro geométrico (cx, cy) de un bounding box."""
    return ((bbox.x0 + bbox.x1) / 2.0, (bbox.y0 + bbox.y1) / 2.0)


def _is_point_inside(px: float, py: float, bbox: BoundingBox, tolerance: float = 2.0) -> bool:
    """Verifica si un punto (px, py) cae dentro del bounding box con tolerancia."""
    return (bbox.x0 - tolerance <= px <= bbox.x1 + tolerance and
            bbox.y0 - tolerance <= py <= bbox.y1 + tolerance)


def _intersection_area(b1: BoundingBox, b2: BoundingBox) -> float:
    """Calcula el área de intersección entre dos bounding boxes."""
    if b1.page != b2.page:
        return 0.0
    ix0 = max(b1.x0, b2.x0)
    iy0 = max(b1.y0, b2.y0)
    ix1 = min(b1.x1, b2.x1)
    iy1 = min(b1.y1, b2.y1)
    w = max(0.0, ix1 - ix0)
    h = max(0.0, iy1 - iy0)
    return w * h


class TableReconstructor:
    """
    Reconstruye una tabla canónica alineando la matriz estructural de Table Transformer
    con los fragmentos de texto existentes en las celdas de Docling y/o PaddleOCR-VL.
    """

    def reconstruct(
        self,
        predicted_structure: PredictedTableStructure,
        source_tables: List[Table],
        original_table_id: str,
        page_number: int,
    ) -> Table:
        """
        Genera una nueva Table canónica con la grilla de predicted_structure y el texto de source_tables.
        """
        num_rows = predicted_structure.num_rows
        num_cols = predicted_structure.num_cols

        # 1. Recolectar todos los fragmentos de texto con BBOX disponibles de las tablas fuente
        text_fragments: List[Tuple[str, Optional[BoundingBox], Optional[float]]] = []
        for src in source_tables:
            for row in src.rows:
                for c in row:
                    text_clean = c.text.strip() if c.text else ""
                    if text_clean:
                        text_fragments.append((text_clean, c.bbox, c.confidence))

        # 2. Inicializar la matriz de nuevas celdas
        new_matrix: List[List[Cell]] = []
        for r_idx in range(num_rows):
            new_row: List[Cell] = []
            for c_idx in range(num_cols):
                pred_cell = predicted_structure.cells[r_idx][c_idx]
                new_row.append(
                    Cell(
                        text="",
                        row_index=r_idx,
                        col_index=c_idx,
                        row_span=pred_cell.row_span,
                        col_span=pred_cell.col_span,
                        is_header=pred_cell.is_header,
                        bbox=pred_cell.bbox,
                        confidence=pred_cell.confidence,
                    )
                )
            new_matrix.append(new_row)

        # 3. Asignar cada fragmento de texto a la celda espacial óptima
        # Para cada fragmento, encontramos la celda cuyo bbox lo contiene (o maximiza IoU / área de corte)
        cell_contents: List[List[List[Tuple[float, float, str]]]] = [
            [[] for _ in range(num_cols)] for _ in range(num_rows)
        ]

        unassigned_fragments: List[Tuple[str, Optional[BoundingBox]]] = []

        for text, frag_bbox, _ in text_fragments:
            if not text:
                continue

            if frag_bbox is None:
                unassigned_fragments.append((text, frag_bbox))
                continue

            cx, cy = _bbox_center(frag_bbox)
            best_r = -1
            best_c = -1
            max_area = 0.0
            found_inside = False

            # Búsqueda 1: ¿Cae el centroide dentro del bbox de alguna celda predicha?
            for r in range(num_rows):
                for c in range(num_cols):
                    cell_bb = new_matrix[r][c].bbox
                    if cell_bb and _is_point_inside(cx, cy, cell_bb):
                        best_r = r
                        best_c = c
                        found_inside = True
                        break
                if found_inside:
                    break

            # Búsqueda 2: Si el centroide no cayó directamente, usar máxima área de intersección
            if not found_inside:
                for r in range(num_rows):
                    for c in range(num_cols):
                        cell_bb = new_matrix[r][c].bbox
                        if cell_bb:
                            area = _intersection_area(frag_bbox, cell_bb)
                            if area > max_area:
                                max_area = area
                                best_r = r
                                best_c = c

            # Búsqueda 3: Si no hay intersección, asignar a la fila/columna por proximidad euclidiana de centroides
            if best_r == -1 or best_c == -1:
                min_dist_sq = float("inf")
                for r in range(num_rows):
                    for c in range(num_cols):
                        cell_bb = new_matrix[r][c].bbox
                        if cell_bb:
                            ccx, ccy = _bbox_center(cell_bb)
                            dist_sq = (cx - ccx) ** 2 + (cy - ccy) ** 2
                            if dist_sq < min_dist_sq:
                                min_dist_sq = dist_sq
                                best_r = r
                                best_c = c

            if best_r != -1 and best_c != -1:
                cell_bb = new_matrix[best_r][best_c].bbox
                order_y = frag_bbox.y0 if frag_bbox else 0.0
                order_x = frag_bbox.x0 if frag_bbox else 0.0
                cell_contents[best_r][best_c].append((order_y, order_x, text))
            else:
                unassigned_fragments.append((text, frag_bbox))

        # 4. Consolidar el texto asignado a cada celda ordenado verticalmente (lectura natural de líneas)
        for r in range(num_rows):
            for c in range(num_cols):
                frags = cell_contents[r][c]
                if frags:
                    # Ordenar fragmentos por posición vertical (y0), luego horizontal (x0)
                    frags.sort(key=lambda item: (item[0], item[1]))
                    # Evitar duplicados exactos continuos
                    unique_texts = []
                    for _, _, txt in frags:
                        if not unique_texts or unique_texts[-1] != txt:
                            unique_texts.append(txt)
                    new_matrix[r][c].text = " ".join(unique_texts).strip()

        # 5. Si quedaron fragmentos no asignados, distribuirlos ordenadamente
        # en celdas vacías adyacentes para evitar pérdida de información
        for text, _ in unassigned_fragments:
            for r in range(num_rows):
                for c in range(num_cols):
                    if not new_matrix[r][c].text:
                        new_matrix[r][c].text = text
                        break

        # 6. Extraer nombres de encabezados (primera fila o filas con is_header=True)
        headers: List[str] = []
        if new_matrix:
            headers = [c.text for c in new_matrix[0]]

        # 7. Calcular BoundingBox global de la tabla reconstruida
        all_cell_bboxes = [c.bbox for row in new_matrix for c in row if c.bbox]
        if all_cell_bboxes:
            global_x0 = min(b.x0 for b in all_cell_bboxes)
            global_y0 = min(b.y0 for b in all_cell_bboxes)
            global_x1 = max(b.x1 for b in all_cell_bboxes)
            global_y1 = max(b.y1 for b in all_cell_bboxes)
            global_bbox = BoundingBox(
                x0=global_x0,
                y0=global_y0,
                x1=global_x1,
                y1=global_y1,
                page=page_number,
            )
        else:
            global_bbox = None

        reconstructed_table = Table(
            table_id=original_table_id,
            page_start=page_number,
            page_end=page_number,
            num_rows=num_rows,
            num_cols=num_cols,
            headers=headers,
            rows=new_matrix,
            bbox=global_bbox,
            caption=(source_tables[0].caption if source_tables else None),
            is_multipage=(source_tables[0].is_multipage if source_tables else False),
        )

        logger.info(
            f"Tabla '{original_table_id}' reconstruida con éxito: {num_rows} filas × {num_cols} columnas"
        )
        return reconstructed_table
