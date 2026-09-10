"""
Registro y orquestador (Pipeline) para la ejecución de reglas de postprocesamiento de texto.
Administra el ciclo de vida, filtrado por motor y aplicación jerárquica de reglas.
"""

from copy import deepcopy
from typing import Any, Dict, List, Optional, Type, Union

from pdfextract.core.logger import get_logger
from pdfextract.core.models import DocumentModel
from pdfextract.postprocess.rules.base import BaseTextRule, RuleTarget

logger = get_logger("TextRulesPipeline")


class TextRulesPipeline:
    """
    Pipeline de ejecución secuencial y extensible de reglas de texto.
    """

    def __init__(self, enabled: bool = True, config: Optional[Any] = None):
        self.config = config
        self.enabled = config.enabled if config is not None else enabled
        self._rules: Dict[str, BaseTextRule] = {}

    def register(self, rule: Union[BaseTextRule, Type[BaseTextRule]]) -> BaseTextRule:
        """
        Registra una nueva regla en el pipeline.
        Acepta una instancia o la clase de la regla.
        """
        rule_instance = rule() if isinstance(rule, type) else rule
        if not isinstance(rule_instance, BaseTextRule):
            raise TypeError(f"La regla debe heredar de BaseTextRule, recibido: {type(rule_instance)}")

        self._rules[rule_instance.rule_id] = rule_instance
        logger.debug(
            f"Regla registrada: '{rule_instance.rule_id}' "
            f"[{rule_instance.target.value}] (Prioridad: {rule_instance.priority})"
        )
        return rule_instance

    def unregister(self, rule_id: str) -> Optional[BaseTextRule]:
        """Elimina una regla registrada por su identificador."""
        return self._rules.pop(rule_id, None)

    def get_rule(self, rule_id: str) -> Optional[BaseTextRule]:
        """Obtiene una regla por su identificador."""
        return self._rules.get(rule_id)

    def get_all_rules(self) -> List[BaseTextRule]:
        """Retorna todas las reglas registradas ordenadas por prioridad."""
        return sorted(self._rules.values(), key=lambda r: r.priority)

    def get_rules_for_engine(
        self,
        engine_name: str,
        include_general: bool = True,
    ) -> List[BaseTextRule]:
        """
        Obtiene las reglas activas aplicables a un motor específico.
        
        Args:
            engine_name: Nombre del motor ('docling', 'paddleocr', 'postprocessed', etc.).
            include_general: Si es True, incluye las reglas con target GENERAL.
            
        Returns:
            Lista ordenada de reglas aplicables según su prioridad.
        """
        normalized_engine = engine_name.lower().strip()
        applicable_rules: List[BaseTextRule] = []

        for rule in self._rules.values():
            if not rule.enabled:
                continue

            # Verificar flags de configuración si existen
            if self.config is not None:
                if rule.target == RuleTarget.DOCLING and not getattr(self.config, "docling_enabled", True):
                    continue
                if rule.target == RuleTarget.PADDLEOCR and not getattr(self.config, "paddleocr_enabled", True):
                    continue
                if rule.target == RuleTarget.GENERAL and not getattr(self.config, "general_enabled", True):
                    continue

            # Reglas específicas de motor
            if rule.target == RuleTarget.DOCLING and normalized_engine == "docling":
                applicable_rules.append(rule)
            elif rule.target == RuleTarget.PADDLEOCR and normalized_engine == "paddleocr":
                applicable_rules.append(rule)
            # Reglas generales
            elif rule.target == RuleTarget.GENERAL and include_general:
                applicable_rules.append(rule)

        return sorted(applicable_rules, key=lambda r: r.priority)

    def clean_text(self, text: str, engine_name: str = "general") -> str:
        """
        Aplica las reglas aplicables para el motor indicado sobre una cadena de texto.
        """
        if not self.enabled or not text:
            return text

        rules = self.get_rules_for_engine(engine_name)
        result = text
        for rule in rules:
            result = rule.apply(result)

        return result

    def clean_document(
        self,
        document: DocumentModel,
        engine_name: str,
        in_place: bool = True,
    ) -> DocumentModel:
        """
        Aplica las reglas aplicables para el motor sobre la totalidad de un DocumentModel.
        
        Args:
            document: DocumentModel de entrada.
            engine_name: Nombre del motor fuente ('docling', 'paddleocr', 'postprocessed').
            in_place: Si es True, muta el documento; de lo contrario, opera sobre una copia.
        """
        if not self.enabled:
            return document

        target_doc = document if in_place else deepcopy(document)
        rules = self.get_rules_for_engine(engine_name)

        if not rules:
            return target_doc

        logger.info(
            f"Aplicando {len(rules)} reglas de texto para motor '{engine_name}' "
            f"en documento '{document.metadata.document_id}'"
        )

        for rule in rules:
            target_doc = rule.apply_to_document(target_doc)

        # Aplicar también las reglas sobre exportaciones nativas si están en raw_engine_data
        if target_doc.raw_engine_data and isinstance(target_doc.raw_engine_data, dict):
            if "markdown_text" in target_doc.raw_engine_data and isinstance(target_doc.raw_engine_data["markdown_text"], str):
                target_doc.raw_engine_data["markdown_text"] = self.clean_text(
                    target_doc.raw_engine_data["markdown_text"], engine_name=engine_name
                )
            if "plain_text" in target_doc.raw_engine_data and isinstance(target_doc.raw_engine_data["plain_text"], str):
                target_doc.raw_engine_data["plain_text"] = self.clean_text(
                    target_doc.raw_engine_data["plain_text"], engine_name=engine_name
                )

        return target_doc
