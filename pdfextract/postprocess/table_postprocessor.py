"""
Orquestador principal de Postprocesamiento Inteligente y Corrección de Tablas.
Coordina TableValidator, TableConsensusEngine, TableTransformerEngine y TableReconstructor.
Genera un DocumentModel corregido y el registro de auditoría auditable y trazable.
"""

from copy import deepcopy
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from pdfextract.core.config import TablePostprocessingConfig
from pdfextract.core.logger import get_logger
from pdfextract.core.models import DocumentMetadata, DocumentModel, Page, Table
from pdfextract.engines.table_transformer_engine import TableTransformerEngine
from pdfextract.postprocess.table_consensus import TableComparisonResult, TableConsensusEngine
from pdfextract.postprocess.table_reconstructor import TableReconstructor
from pdfextract.postprocess.table_validator import (
    TableValidationReport,
    TableValidator,
    ValidationStatus,
)

logger = get_logger("TablePostprocessor")


@dataclass
class TableAuditRecord:
    page: int
    table_id: str
    original_engine: str
    original_structure: Dict[str, Any]
    detected_problem: str
    confidence_before: float
    table_transformer_result: Optional[Dict[str, Any]]
    final_structure: Dict[str, Any]
    confidence_after: float
    correction_applied: bool
    details: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "page": self.page,
            "table_id": self.table_id,
            "original_engine": self.original_engine,
            "original_structure": self.original_structure,
            "detected_problem": self.detected_problem,
            "confidence_before": round(self.confidence_before, 4),
            "table_transformer_result": self.table_transformer_result,
            "final_structure": self.final_structure,
            "confidence_after": round(self.confidence_after, 4),
            "correction_applied": self.correction_applied,
            "details": self.details,
        }


@dataclass
class PostprocessingResult:
    document: DocumentModel
    audit_records: List[TableAuditRecord]
    tables_analyzed: int
    tables_corrected: int
    tables_unchanged: int
    tables_rejected: int

    def to_summary_dict(self) -> Dict[str, Any]:
        return {
            "tables_analyzed": self.tables_analyzed,
            "tables_corrected": self.tables_corrected,
            "tables_unchanged": self.tables_unchanged,
            "tables_rejected": self.tables_rejected,
            "audit_records_count": len(self.audit_records),
        }


class TablePostprocessor:
    """
    Orquestador de postprocesamiento selectivo para tablas complejas de seguros.
    """

    def __init__(
        self,
        config: Optional[TablePostprocessingConfig] = None,
        validator: Optional[TableValidator] = None,
        consensus_engine: Optional[TableConsensusEngine] = None,
        transformer_engine: Optional[TableTransformerEngine] = None,
        reconstructor: Optional[TableReconstructor] = None,
    ):
        self.config = config or TablePostprocessingConfig()
        self.validator = validator or TableValidator(self.config.validator)
        self.consensus_engine = consensus_engine or TableConsensusEngine(
            self.config.consensus, self.validator
        )
        self.transformer_engine = transformer_engine or TableTransformerEngine(
            self.config.table_transformer
        )
        self.reconstructor = reconstructor or TableReconstructor()

    def postprocess(
        self,
        pdf_path: Path,
        docling_doc: Optional[DocumentModel] = None,
        paddle_doc: Optional[DocumentModel] = None,
    ) -> PostprocessingResult:
        """
        Ejecuta el postprocesamiento comparativo y selectivo entre ambos modelos.
        """
        if docling_doc is None and paddle_doc is None:
            raise ValueError("Al menos un DocumentModel (Docling o PaddleOCR) debe ser suministrado.")

        # Tomar como documento base el de mayor número de elementos o docling por defecto
        base_doc = docling_doc if docling_doc is not None else paddle_doc
        assert base_doc is not None

        # Clonar para no alterar el original
        final_doc = deepcopy(base_doc)
        final_doc.metadata.engine_name = "postprocessed"

        audit_records: List[TableAuditRecord] = []
        tables_analyzed = 0
        tables_corrected = 0
        tables_unchanged = 0
        tables_rejected = 0

        # Determinar páginas totales a evaluar
        max_pages = max(
            len(docling_doc.pages) if docling_doc else 0,
            len(paddle_doc.pages) if paddle_doc else 0,
            1,
        )

        final_tables_all: List[Table] = []

        for p_num in range(1, max_pages + 1):
            d_tables = []
            p_tables = []

            if docling_doc:
                for pg in docling_doc.pages:
                    if pg.page_number == p_num:
                        d_tables = pg.tables
                        break

            if paddle_doc:
                for pg in paddle_doc.pages:
                    if pg.page_number == p_num:
                        p_tables = pg.tables
                        break

            # Si no hay tablas en esta página para ningún motor
            if not d_tables and not p_tables:
                continue

            # Emparejar tablas y evaluar consenso
            matched_pairs = self.consensus_engine.match_and_compare_page_tables(
                d_tables, p_tables, page_number=p_num
            )

            page_final_tables: List[Table] = []

            for d_tbl, p_tbl, comp_res in matched_pairs:
                tables_analyzed += 1
                preferred_tbl = d_tbl if (comp_res.preferred_engine == "docling" and d_tbl) else (p_tbl or d_tbl)
                table_id = preferred_tbl.table_id if preferred_tbl else f"table_p{p_num}_{tables_analyzed}"

                # Confianza inicial
                conf_before = 0.0
                if comp_res.preferred_engine == "docling" and comp_res.docling_validation:
                    conf_before = comp_res.docling_validation.confidence_score
                elif comp_res.paddle_validation:
                    conf_before = comp_res.paddle_validation.confidence_score
                elif comp_res.docling_validation:
                    conf_before = comp_res.docling_validation.confidence_score

                orig_struct = {
                    "num_rows": preferred_tbl.num_rows if preferred_tbl else 0,
                    "num_cols": preferred_tbl.num_cols if preferred_tbl else 0,
                    "headers": preferred_tbl.headers if preferred_tbl else [],
                }

                # Evaluar si requiere corrección
                if not comp_res.requires_correction:
                    # TABLA CONFIABLE: Conservar resultado original
                    assert preferred_tbl is not None
                    page_final_tables.append(preferred_tbl)
                    tables_unchanged += 1
                    audit_records.append(
                        TableAuditRecord(
                            page=p_num,
                            table_id=table_id,
                            original_engine=comp_res.preferred_engine or "docling",
                            original_structure=orig_struct,
                            detected_problem="Ninguno (Alta confianza y/o consenso)",
                            confidence_before=conf_before,
                            table_transformer_result=None,
                            final_structure=orig_struct,
                            confidence_after=conf_before,
                            correction_applied=False,
                            details=comp_res.to_dict(),
                        )
                    )
                    continue

                # TABLA SOSPECHOSA / DISCREPANTE -> Evaluar corrección especializada
                logger.info(
                    f"Tabla '{table_id}' en página {p_num} requiere corrección. "
                    f"Motivos: {', '.join(comp_res.discrepancy_reasons)}"
                )

                # 1. Intentar desempacado semántico aditivo de tablas clave-valor colapsadas
                unpacked_table = None
                if preferred_tbl and preferred_tbl.num_cols == 2:
                    try:
                        unpacked_candidate = self.reconstructor.unpack_collapsed_key_value_table(preferred_tbl)
                        if unpacked_candidate is not None:
                            val_rep = self.validator.validate(unpacked_candidate)
                            if val_rep.confidence_score >= conf_before:
                                unpacked_table = unpacked_candidate
                                conf_after = val_rep.confidence_score
                                logger.info(
                                    f"Tabla '{table_id}' normalizada como formulario clave-valor "
                                    f"(confianza: {conf_before:.3f} -> {conf_after:.3f})"
                                )
                    except Exception as e:
                        logger.debug(f"Fallo en desempacado clave-valor para '{table_id}': {e}")

                if unpacked_table is not None:
                    page_final_tables.append(unpacked_table)
                    tables_corrected += 1
                    audit_records.append(
                        TableAuditRecord(
                            page=p_num,
                            table_id=table_id,
                            original_engine=comp_res.preferred_engine or "docling",
                            original_structure=orig_struct,
                            detected_problem="Celdas multiclave o formulario colapsado",
                            confidence_before=conf_before,
                            table_transformer_result=None,
                            final_structure={
                                "num_rows": unpacked_table.num_rows,
                                "num_cols": unpacked_table.num_cols,
                                "headers": unpacked_table.headers,
                            },
                            confidence_after=conf_after,
                            correction_applied=True,
                            details={"method": "unpack_collapsed_key_value_table", **comp_res.to_dict()},
                        )
                    )
                    continue

                # 2. Si no es tabla clave-valor colapsada, ejecutar Table Transformer
                candidate_sources = [t for t in [d_tbl, p_tbl] if t is not None]
                table_bbox = preferred_tbl.bbox if preferred_tbl else None

                tatr_structure = None
                if self.config.table_transformer.enabled:
                    try:
                        tatr_structure = self.transformer_engine.predict_structure(
                            pdf_path=pdf_path,
                            page_number=p_num,
                            table_bbox=table_bbox,
                        )
                    except Exception as e:
                        logger.warning(f"Fallo al ejecutar Table Transformer: {e}")
                        tatr_structure = None

                correction_success = False
                reconstructed_table = None
                conf_after = conf_before

                if tatr_structure is not None:
                    tatr_info = {
                        "num_rows": tatr_structure.num_rows,
                        "num_cols": tatr_structure.num_cols,
                        "average_confidence": round(tatr_structure.average_confidence, 3),
                    }
                    try:
                        reconstructed_table = self.reconstructor.reconstruct(
                            predicted_structure=tatr_structure,
                            source_tables=candidate_sources,
                            original_table_id=table_id,
                            page_number=p_num,
                        )
                        # Validar tabla reconstruida
                        rec_report = self.validator.validate(reconstructed_table)
                        conf_after = rec_report.confidence_score

                        # Aplicar si mejora o iguala la confianza previa sin ser de baja calidad (LOW)
                        # Nunca degradar una tabla que ya tenía mayor confianza previa
                        if conf_after >= conf_before and rec_report.validation_status != ValidationStatus.LOW:
                            correction_success = True
                            page_final_tables.append(reconstructed_table)
                            tables_corrected += 1
                        else:
                            # Rechazar corrección si degrada o no supera la confianza previa
                            logger.info(
                                f"Corrección rechazada para '{table_id}': confianza post ({conf_after:.3f}) <= previa ({conf_before:.3f})"
                            )
                            page_final_tables.append(preferred_tbl)
                            tables_rejected += 1
                    except Exception as e:
                        logger.error(f"Error reconstruyendo tabla '{table_id}': {e}", exc_info=True)
                        page_final_tables.append(preferred_tbl)
                        tables_rejected += 1
                else:
                    tatr_info = None
                    page_final_tables.append(preferred_tbl)
                    tables_rejected += 1

                final_chosen = reconstructed_table if correction_success else preferred_tbl
                final_struct = {
                    "num_rows": final_chosen.num_rows if final_chosen else 0,
                    "num_cols": final_chosen.num_cols if final_chosen else 0,
                    "headers": final_chosen.headers if final_chosen else [],
                }

                audit_records.append(
                    TableAuditRecord(
                        page=p_num,
                        table_id=table_id,
                        original_engine=comp_res.preferred_engine or "docling",
                        original_structure=orig_struct,
                        detected_problem="; ".join(comp_res.discrepancy_reasons),
                        confidence_before=conf_before,
                        table_transformer_result=tatr_info,
                        final_structure=final_struct,
                        confidence_after=conf_after,
                        correction_applied=correction_success,
                        details={
                            "consensus": comp_res.to_dict(),
                            "rejected": not correction_success,
                        },
                    )
                )

            # Actualizar tablas en la página de final_doc
            for pg in final_doc.pages:
                if pg.page_number == p_num:
                    pg.tables = page_final_tables
                    break

            final_tables_all.extend(page_final_tables)

        # Actualizar lista plana de tablas en final_doc
        final_doc.tables = final_tables_all

        logger.info(
            f"Postprocesamiento finalizado: analizadas={tables_analyzed}, "
            f"corregidas={tables_corrected}, conservadas={tables_unchanged}, rechazadas={tables_rejected}"
        )

        return PostprocessingResult(
            document=final_doc,
            audit_records=audit_records,
            tables_analyzed=tables_analyzed,
            tables_corrected=tables_corrected,
            tables_unchanged=tables_unchanged,
            tables_rejected=tables_rejected,
        )
