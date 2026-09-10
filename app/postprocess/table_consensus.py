"""
Motor de Consenso entre motores de extracción de tablas (Docling vs PaddleOCR-VL).
Evalúa la concordancia estructural, geométrica y de contenido entre tablas equivalentes
para detectar discrepancias y determinar si se requiere corrección especializada.
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from app.core.config import TableConsensusConfig
from app.core.logger import get_logger
from app.core.models import BoundingBox, Table
from app.postprocess.table_validator import (
    TableValidationReport,
    TableValidator,
    ValidationStatus,
    compute_bbox_iou,
)

logger = get_logger("TableConsensus")


@dataclass
class TableComparisonResult:
    docling_table_id: Optional[str]
    paddle_table_id: Optional[str]
    page: int
    agreement_score: float
    structure_score: float
    geometry_score: float
    content_score: float
    requires_correction: bool
    discrepancy_reasons: List[str] = field(default_factory=list)
    preferred_engine: Optional[str] = None
    docling_validation: Optional[TableValidationReport] = None
    paddle_validation: Optional[TableValidationReport] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "docling_table_id": self.docling_table_id,
            "paddle_table_id": self.paddle_table_id,
            "page": self.page,
            "agreement_score": round(self.agreement_score, 4),
            "structure_score": round(self.structure_score, 4),
            "geometry_score": round(self.geometry_score, 4),
            "content_score": round(self.content_score, 4),
            "requires_correction": self.requires_correction,
            "discrepancy_reasons": self.discrepancy_reasons,
            "preferred_engine": self.preferred_engine,
            "docling_confidence": (
                round(self.docling_validation.confidence_score, 4)
                if self.docling_validation
                else None
            ),
            "paddle_confidence": (
                round(self.paddle_validation.confidence_score, 4)
                if self.paddle_validation
                else None
            ),
        }


def _extract_table_words(table: Table) -> set:
    """Extrae conjunto de palabras alfanuméricas de una tabla para similitud de contenido."""
    words = set()
    for row in table.rows:
        for cell in row:
            if cell.text:
                for token in cell.text.lower().split():
                    clean = "".join(c for c in token if c.isalnum())
                    if len(clean) > 1:
                        words.add(clean)
    return words


class TableConsensusEngine:
    """
    Compara tablas homólogas entre dos motores para cuantificar el grado de consenso.
    """

    def __init__(
        self,
        config: Optional[TableConsensusConfig] = None,
        validator: Optional[TableValidator] = None,
    ):
        self.config = config or TableConsensusConfig()
        self.validator = validator or TableValidator()

    def compare_tables(
        self,
        docling_table: Optional[Table],
        paddle_table: Optional[Table],
        page_number: int = 1,
    ) -> TableComparisonResult:
        """
        Compara dos tablas candidatas a ser la misma tabla en una página.
        """
        discrepancy_reasons: List[str] = []

        # Caso 1: Solo un motor detectó la tabla
        if docling_table is None and paddle_table is None:
            return TableComparisonResult(
                docling_table_id=None,
                paddle_table_id=None,
                page=page_number,
                agreement_score=1.0,
                structure_score=1.0,
                geometry_score=1.0,
                content_score=1.0,
                requires_correction=False,
            )

        if docling_table is None and paddle_table is not None:
            p_report = self.validator.validate(paddle_table)
            requires_corr = p_report.validation_status != ValidationStatus.HIGH
            if requires_corr:
                discrepancy_reasons.append("Tabla detectada solo por PaddleOCR con confianza no alta")
            return TableComparisonResult(
                docling_table_id=None,
                paddle_table_id=paddle_table.table_id,
                page=page_number,
                agreement_score=0.5,
                structure_score=0.5,
                geometry_score=0.5,
                content_score=0.5,
                requires_correction=requires_corr,
                discrepancy_reasons=discrepancy_reasons,
                preferred_engine="paddleocr",
                paddle_validation=p_report,
            )

        if paddle_table is None and docling_table is not None:
            d_report = self.validator.validate(docling_table)
            requires_corr = d_report.validation_status != ValidationStatus.HIGH
            if requires_corr:
                discrepancy_reasons.append("Tabla detectada solo por Docling con confianza no alta")
            return TableComparisonResult(
                docling_table_id=docling_table.table_id,
                paddle_table_id=None,
                page=page_number,
                agreement_score=0.5,
                structure_score=0.5,
                geometry_score=0.5,
                content_score=0.5,
                requires_correction=requires_corr,
                discrepancy_reasons=discrepancy_reasons,
                preferred_engine="docling",
                docling_validation=d_report,
            )

        assert docling_table is not None and paddle_table is not None

        # Caso 2: Ambos motores detectaron tabla -> Comparación profunda
        d_report = self.validator.validate(docling_table)
        p_report = self.validator.validate(paddle_table)

        # 1. Puntuación estructural (columnas y filas)
        cols_diff = abs(docling_table.num_cols - paddle_table.num_cols)
        rows_diff = abs(docling_table.num_rows - paddle_table.num_rows)
        max_cols = max(docling_table.num_cols, paddle_table.num_cols, 1)
        max_rows = max(docling_table.num_rows, paddle_table.num_rows, 1)

        col_agreement = max(0.0, 1.0 - (cols_diff / max_cols))
        row_agreement = max(0.0, 1.0 - (rows_diff / max_rows))

        if cols_diff > 0:
            discrepancy_reasons.append(
                f"Discrepancia en columnas: Docling={docling_table.num_cols} vs PaddleOCR={paddle_table.num_cols}"
            )
        if rows_diff > 1:  # Permitir tolerancia de 1 fila por encabezados
            discrepancy_reasons.append(
                f"Discrepancia en filas: Docling={docling_table.num_rows} vs PaddleOCR={paddle_table.num_rows}"
            )

        structure_score = (
            col_agreement * (self.config.weight_columns / (self.config.weight_columns + self.config.weight_rows))
            + row_agreement * (self.config.weight_rows / (self.config.weight_columns + self.config.weight_rows))
        )

        # 2. Puntuación geométrica (IoU de bounding box de la tabla)
        if docling_table.bbox and paddle_table.bbox:
            geometry_score = compute_bbox_iou(docling_table.bbox, paddle_table.bbox)
            if geometry_score < self.config.min_table_overlap_iou:
                discrepancy_reasons.append(
                    f"Baja superposición espacial entre motores (IoU={geometry_score:.2f})"
                )
        else:
            geometry_score = 0.8  # Si falta bbox en alguno, neutral

        # 3. Puntuación de contenido (Jaccard token overlap)
        words_d = _extract_table_words(docling_table)
        words_p = _extract_table_words(paddle_table)
        if words_d and words_p:
            inter = len(words_d.intersection(words_p))
            union = len(words_d.union(words_p))
            content_score = inter / union if union > 0 else 1.0
        elif not words_d and not words_p:
            content_score = 1.0
        else:
            content_score = 0.4
            discrepancy_reasons.append("Uno de los motores extrajo celdas mayoritariamente vacías")

        # Puntuación global de acuerdo
        agreement_score = (
            self.config.weight_columns * col_agreement
            + self.config.weight_rows * row_agreement
            + self.config.weight_geometry * geometry_score
            + self.config.weight_content * content_score
        )
        agreement_score = max(0.0, min(1.0, agreement_score))

        # Determinar motor preferido basado en confianza individual
        if d_report.confidence_score >= p_report.confidence_score:
            preferred_engine = "docling"
        else:
            preferred_engine = "paddleocr"

        # Regla de decisión para requerir corrección:
        # 1. Ambos son HIGH y hay acuerdo razonable -> NO requiere corrección
        # 2. Discrepancia crítica de columnas (diferencia >= 2 o col_agreement < 0.7) -> SÍ requiere corrección
        # 3. Acuerdo por debajo del umbral -> SÍ requiere corrección
        # 4. Ambos motores tienen LOW o MEDIUM confidence -> SÍ requiere corrección
        requires_correction = False

        if cols_diff >= 2:
            requires_correction = True
            discrepancy_reasons.append("Discrepancia crítica en cantidad de columnas (>= 2)")
        elif agreement_score < self.config.min_agreement_score:
            requires_correction = True
            discrepancy_reasons.append(
                f"Puntuación de consenso ({agreement_score:.2f}) inferior al umbral ({self.config.min_agreement_score:.2f})"
            )
        elif d_report.validation_status == ValidationStatus.LOW and p_report.validation_status == ValidationStatus.LOW:
            requires_correction = True
            discrepancy_reasons.append("Ambos motores obtuvieron baja confianza individual (LOW)")
        elif (d_report.validation_status == ValidationStatus.LOW or p_report.validation_status == ValidationStatus.LOW) and agreement_score < 0.85:
            requires_correction = True
            discrepancy_reasons.append("Al menos un motor tiene baja confianza con consenso moderado")

        return TableComparisonResult(
            docling_table_id=docling_table.table_id,
            paddle_table_id=paddle_table.table_id,
            page=page_number,
            agreement_score=agreement_score,
            structure_score=structure_score,
            geometry_score=geometry_score,
            content_score=content_score,
            requires_correction=requires_correction,
            discrepancy_reasons=discrepancy_reasons,
            preferred_engine=preferred_engine,
            docling_validation=d_report,
            paddle_validation=p_report,
        )

    def match_and_compare_page_tables(
        self,
        docling_tables: List[Table],
        paddle_tables: List[Table],
        page_number: int,
    ) -> List[Tuple[Optional[Table], Optional[Table], TableComparisonResult]]:
        """
        Empareja espacialmente las tablas de una página y genera el análisis de consenso.
        """
        matched_pairs: List[Tuple[Optional[Table], Optional[Table], TableComparisonResult]] = []
        used_paddle_indices = set()

        for d_tbl in docling_tables:
            best_p_tbl: Optional[Table] = None
            best_iou = -1.0
            best_p_idx = -1

            for p_idx, p_tbl in enumerate(paddle_tables):
                if p_idx in used_paddle_indices:
                    continue
                if d_tbl.bbox and p_tbl.bbox:
                    iou = compute_bbox_iou(d_tbl.bbox, p_tbl.bbox)
                    if iou > best_iou:
                        best_iou = iou
                        best_p_tbl = p_tbl
                        best_p_idx = p_idx

            # Si encontramos coincidencia espacial por encima del umbral
            if best_p_tbl is not None and best_iou >= self.config.min_table_overlap_iou:
                used_paddle_indices.add(best_p_idx)
                res = self.compare_tables(d_tbl, best_p_tbl, page_number)
                matched_pairs.append((d_tbl, best_p_tbl, res))
            elif len(paddle_tables) == 1 and len(docling_tables) == 1 and 0 not in used_paddle_indices:
                # Si solo hay una tabla en cada motor para la página, emparejar directamente
                used_paddle_indices.add(0)
                res = self.compare_tables(d_tbl, paddle_tables[0], page_number)
                matched_pairs.append((d_tbl, paddle_tables[0], res))
            else:
                # Docling sin homólogo claro en Paddle
                res = self.compare_tables(d_tbl, None, page_number)
                matched_pairs.append((d_tbl, None, res))

        # Tablas de PaddleOCR que no fueron emparejadas con Docling
        for p_idx, p_tbl in enumerate(paddle_tables):
            if p_idx not in used_paddle_indices:
                res = self.compare_tables(None, p_tbl, page_number)
                matched_pairs.append((None, p_tbl, res))

        return matched_pairs
