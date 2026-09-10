"""
Módulo de Postprocesamiento Inteligente y Corrección de Tablas.
"""

from pdfextract.postprocess.table_validator import (
    TableValidator,
    TableValidationReport,
    ValidationStatus,
    ValidationIssue,
    compute_bbox_iou,
)
from pdfextract.postprocess.table_consensus import (
    TableConsensusEngine,
    TableComparisonResult,
)
from pdfextract.postprocess.table_reconstructor import (
    TableReconstructor,
)
from pdfextract.postprocess.table_postprocessor import (
    TablePostprocessor,
    TableAuditRecord,
    PostprocessingResult,
)

from pdfextract.postprocess.rules import (
    BaseTextRule,
    RuleTarget,
    TextRulesPipeline,
    create_default_text_rules_pipeline,
)

__all__ = [
    "TableValidator",
    "TableValidationReport",
    "ValidationStatus",
    "ValidationIssue",
    "compute_bbox_iou",
    "TableConsensusEngine",
    "TableComparisonResult",
    "TableReconstructor",
    "TablePostprocessor",
    "TableAuditRecord",
    "PostprocessingResult",
    "BaseTextRule",
    "RuleTarget",
    "TextRulesPipeline",
    "create_default_text_rules_pipeline",
]
