"""
Módulo de reglas de postprocesamiento de texto para motores de extracción.
"""

from typing import Any, Optional

from app.postprocess.rules.base import BaseTextRule, RuleTarget
from app.postprocess.rules.docling_rules import (
    DoclingHeaderCleanRule,
    DoclingKeyValueJoinRule,
    DoclingMarkdownArtifactsRule,
)
from app.postprocess.rules.general_rules import (
    CleanWhitespaceRule,
    NormalizeTypographyRule,
)
from app.postprocess.rules.header_footer_rules import HeaderFooterRemovalRule
from app.postprocess.rules.paddleocr_rules import (
    PaddleOCRDehyphenationRule,
    PaddleOCRSpeckleCleanupRule,
)
from app.postprocess.rules.registry import TextRulesPipeline


def create_default_text_rules_pipeline(
    enabled: bool = True,
    config: Optional[Any] = None,
) -> TextRulesPipeline:
    """
    Crea e inicializa un TextRulesPipeline con las reglas por defecto registradas.
    """
    pipeline = TextRulesPipeline(enabled=enabled, config=config)

    # 1. Reglas Generales
    pipeline.register(HeaderFooterRemovalRule())
    pipeline.register(CleanWhitespaceRule())
    pipeline.register(NormalizeTypographyRule())

    # 2. Reglas Docling
    pipeline.register(DoclingKeyValueJoinRule())      # prioridad 25: primero reconstruir pares clave-valor
    pipeline.register(DoclingMarkdownArtifactsRule())  # prioridad 30
    pipeline.register(DoclingHeaderCleanRule())        # prioridad 40

    # 3. Reglas PaddleOCR
    pipeline.register(PaddleOCRDehyphenationRule())
    pipeline.register(PaddleOCRSpeckleCleanupRule())

    return pipeline


__all__ = [
    "BaseTextRule",
    "RuleTarget",
    "TextRulesPipeline",
    "HeaderFooterRemovalRule",
    "CleanWhitespaceRule",
    "NormalizeTypographyRule",
    "DoclingKeyValueJoinRule",
    "DoclingMarkdownArtifactsRule",
    "DoclingHeaderCleanRule",
    "PaddleOCRDehyphenationRule",
    "PaddleOCRSpeckleCleanupRule",
    "create_default_text_rules_pipeline",
]
