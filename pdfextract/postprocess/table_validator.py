"""
Validador individual de tablas extraídas.
Analiza la coherencia estructural, geométrica y de contenido para asignar un
confidence_score (0.0 a 1.0) y un validation_status (HIGH, MEDIUM, LOW).
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

from pdfextract.core.config import TableValidatorConfig
from pdfextract.core.logger import get_logger
from pdfextract.core.models import BoundingBox, Cell, Table

logger = get_logger("TableValidator")


class ValidationStatus(str, Enum):
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"


@dataclass
class ValidationIssue:
    category: str  # "structure", "geometry", "content"
    severity: str  # "warning", "critical"
    description: str
    penalty: float


@dataclass
class TableValidationReport:
    table_id: str
    confidence_score: float
    validation_status: ValidationStatus
    num_rows: int
    num_cols: int
    total_cells: int
    empty_cells_count: int
    empty_cell_ratio: float
    issues: List[ValidationIssue] = field(default_factory=list)
    metrics: Dict[str, Any] = field(default_factory=dict)

    @property
    def is_reliable(self) -> bool:
        return self.validation_status == ValidationStatus.HIGH

    def to_dict(self) -> Dict[str, Any]:
        return {
            "table_id": self.table_id,
            "confidence_score": round(self.confidence_score, 4),
            "validation_status": self.validation_status.value,
            "num_rows": self.num_rows,
            "num_cols": self.num_cols,
            "total_cells": self.total_cells,
            "empty_cells_count": self.empty_cells_count,
            "empty_cell_ratio": round(self.empty_cell_ratio, 4),
            "issues_count": len(self.issues),
            "issues": [
                {
                    "category": issue.category,
                    "severity": issue.severity,
                    "description": issue.description,
                    "penalty": round(issue.penalty, 4),
                }
                for issue in self.issues
            ],
            "metrics": self.metrics,
        }


def compute_bbox_iou(b1: BoundingBox, b2: BoundingBox) -> float:
    """Calcula la Intersección sobre Unión (IoU) entre dos bounding boxes."""
    if b1.page != b2.page:
        return 0.0

    ix0 = max(b1.x0, b2.x0)
    iy0 = max(b1.y0, b2.y0)
    ix1 = min(b1.x1, b2.x1)
    iy1 = min(b1.y1, b2.y1)

    inter_w = max(0.0, ix1 - ix0)
    inter_h = max(0.0, iy1 - iy0)
    inter_area = inter_w * inter_h

    if inter_area <= 0.0:
        return 0.0

    area1 = max(0.0, (b1.x1 - b1.x0) * (b1.y1 - b1.y0))
    area2 = max(0.0, (b2.x1 - b2.x0) * (b2.y1 - b2.y0))
    union_area = area1 + area2 - inter_area

    if union_area <= 0.0:
        return 0.0

    return inter_area / union_area


class TableValidator:
    """
    Analiza exhaustivamente cada tabla individual para determinar su integridad.
    """

    def __init__(self, config: Optional[TableValidatorConfig] = None):
        self.config = config or TableValidatorConfig()

    def validate(self, table: Table) -> TableValidationReport:
        """
        Ejecuta la validación multidimensional de la tabla.
        """
        issues: List[ValidationIssue] = []
        score = 1.0

        total_cells = sum(len(row) for row in table.rows)
        empty_cells = 0
        all_cells: List[Cell] = []

        for row in table.rows:
            for cell in row:
                all_cells.append(cell)
                if not cell.text or not cell.text.strip():
                    empty_cells += 1

        empty_ratio = (empty_cells / total_cells) if total_cells > 0 else 1.0

        # -------------------------------------------------------------
        # 1. Validación Estructural
        # -------------------------------------------------------------
        irregular_rows = 0
        invalid_spans = 0
        if table.num_rows <= 0 or table.num_cols <= 0 or total_cells == 0:
            issues.append(
                ValidationIssue(
                    category="structure",
                    severity="critical",
                    description=f"Tabla sin dimensiones válidas: {table.num_rows}x{table.num_cols}, celdas={total_cells}",
                    penalty=0.6,
                )
            )
            score -= 0.6
        else:
            # Regularidad de filas
            expected_cols = table.num_cols
            for r_idx, row in enumerate(table.rows):
                row_cols_span = sum(c.col_span for c in row)
                if row_cols_span != expected_cols and len(row) != expected_cols:
                    irregular_rows += 1

            if irregular_rows > 0:
                irreg_ratio = irregular_rows / table.num_rows
                penalty = min(0.35, 0.15 + 0.20 * irreg_ratio)
                issues.append(
                    ValidationIssue(
                        category="structure",
                        severity="warning" if irreg_ratio < 0.5 else "critical",
                        description=f"{irregular_rows}/{table.num_rows} filas tienen número de columnas inconsistente",
                        penalty=penalty,
                    )
                )
                score -= penalty

            # Ratio de celdas vacías
            if empty_ratio > self.config.max_empty_cell_ratio:
                penalty = min(0.30, (empty_ratio - self.config.max_empty_cell_ratio) * 0.8)
                issues.append(
                    ValidationIssue(
                        category="structure",
                        severity="warning",
                        description=f"Ratio de celdas vacías elevado: {empty_ratio:.1%} (máx tolerado: {self.config.max_empty_cell_ratio:.1%})",
                        penalty=penalty,
                    )
                )
                score -= penalty

            # Validar límites de rowspan y colspan
            for cell in all_cells:
                if cell.row_span < 1 or cell.col_span < 1:
                    invalid_spans += 1
                elif (cell.row_index + cell.row_span > table.num_rows) or (cell.col_index + cell.col_span > table.num_cols):
                    invalid_spans += 1

            if invalid_spans > 0:
                penalty = min(0.30, 0.10 + 0.05 * invalid_spans)
                issues.append(
                    ValidationIssue(
                        category="structure",
                        severity="critical",
                        description=f"{invalid_spans} celdas exceden los límites de la matriz con rowspan/colspan",
                        penalty=penalty,
                    )
                )
                score -= penalty

        # -------------------------------------------------------------
        # 2. Validación Geométrica
        # -------------------------------------------------------------
        table_bbox = table.bbox
        invalid_bboxes = 0
        out_of_bounds = 0
        cells_with_bbox = [c for c in all_cells if c.bbox is not None]

        # Armonizar orientación de table_bbox si viene invertido (BOTTOM_LEFT)
        effective_table_bbox = table_bbox
        if effective_table_bbox is not None and effective_table_bbox.y1 < effective_table_bbox.y0:
            effective_table_bbox = BoundingBox(
                x0=effective_table_bbox.x0,
                y0=effective_table_bbox.y1,
                x1=effective_table_bbox.x1,
                y1=effective_table_bbox.y0,
                page=effective_table_bbox.page,
                coord_origin="TOP_LEFT",
            )

        for cell in cells_with_bbox:
            bbox = cell.bbox
            assert bbox is not None
            # Bbox degenerate
            if bbox.x1 <= bbox.x0 or bbox.y1 <= bbox.y0 or bbox.x0 < 0 or bbox.y0 < 0:
                invalid_bboxes += 1

            # Fuera de la tabla
            if effective_table_bbox is not None:
                if (bbox.x0 < effective_table_bbox.x0 - 5.0 or bbox.x1 > effective_table_bbox.x1 + 5.0 or
                        bbox.y0 < effective_table_bbox.y0 - 5.0 or bbox.y1 > effective_table_bbox.y1 + 5.0):
                    out_of_bounds += 1

        if invalid_bboxes > 0:
            penalty = min(0.30, 0.05 * invalid_bboxes)
            issues.append(
                ValidationIssue(
                    category="geometry",
                    severity="critical",
                    description=f"{invalid_bboxes} celdas tienen coordenadas BBOX degeneradas o negativas",
                    penalty=penalty,
                )
            )
            score -= penalty

        if out_of_bounds > 0:
            penalty = min(0.25, 0.05 * out_of_bounds)
            issues.append(
                ValidationIssue(
                    category="geometry",
                    severity="warning",
                    description=f"{out_of_bounds} celdas sobrepasan los límites espaciales de la tabla",
                    penalty=penalty,
                )
            )
            score -= penalty

        # Superposiciones anómalas entre celdas distintas (IoU excesivo)
        overlapping_pairs = 0
        for i in range(len(cells_with_bbox)):
            c1 = cells_with_bbox[i]
            assert c1.bbox is not None
            for j in range(i + 1, min(i + 15, len(cells_with_bbox))):
                c2 = cells_with_bbox[j]
                assert c2.bbox is not None
                if c1.row_index != c2.row_index or c1.col_index != c2.col_index:
                    iou = compute_bbox_iou(c1.bbox, c2.bbox)
                    if iou > self.config.max_overlap_iou:
                        overlapping_pairs += 1

        if overlapping_pairs > 0:
            penalty = min(0.35, 0.08 * overlapping_pairs)
            issues.append(
                ValidationIssue(
                    category="geometry",
                    severity="critical",
                    description=f"{overlapping_pairs} pares de celdas presentan solapamiento espacial excesivo (IoU > {self.config.max_overlap_iou})",
                    penalty=penalty,
                )
            )
            score -= penalty

        # -------------------------------------------------------------
        # 3. Validación de Contenido
        # -------------------------------------------------------------
        excessively_long_cells = 0
        for cell in all_cells:
            if len(cell.text) > 500:
                excessively_long_cells += 1

        if excessively_long_cells > 0:
            penalty = min(0.20, 0.05 * excessively_long_cells)
            issues.append(
                ValidationIssue(
                    category="content",
                    severity="warning",
                    description=f"{excessively_long_cells} celdas contienen textos desproporcionadamente extensos (>500 chars)",
                    penalty=penalty,
                )
            )
            score -= penalty

        # Normalizar score a [0.0, 1.0]
        final_score = max(0.0, min(1.0, score))

        # Determinar status según umbrales configurados
        if final_score >= self.config.high_threshold:
            status = ValidationStatus.HIGH
        elif final_score >= self.config.low_threshold:
            status = ValidationStatus.MEDIUM
        else:
            status = ValidationStatus.LOW

        report = TableValidationReport(
            table_id=table.table_id,
            confidence_score=final_score,
            validation_status=status,
            num_rows=table.num_rows,
            num_cols=table.num_cols,
            total_cells=total_cells,
            empty_cells_count=empty_cells,
            empty_cell_ratio=empty_ratio,
            issues=issues,
            metrics={
                "irregular_rows": irregular_rows,
                "invalid_spans": invalid_spans,
                "invalid_bboxes": invalid_bboxes,
                "out_of_bounds": out_of_bounds,
                "overlapping_pairs": overlapping_pairs,
                "excessively_long_cells": excessively_long_cells,
            },
        )

        logger.debug(
            f"Validación tabla '{table.table_id}': score={final_score:.3f} | status={status.value} | issues={len(issues)}"
        )
        return report
