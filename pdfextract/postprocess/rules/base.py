"""
Clases base y contratos para el sistema de reglas de postprocesamiento de texto.
Permite clasificar reglas por motor específico ('docling', 'paddleocr') o 'general'.
"""

from abc import ABC, abstractmethod
from copy import deepcopy
from enum import Enum
from typing import Any, Dict, Optional

from pdfextract.core.models import Cell, DocumentModel, Page, Table, TextElement


class RuleTarget(str, Enum):
    """Alcance u objetivo al que aplica la regla."""
    GENERAL = "general"
    DOCLING = "docling"
    PADDLEOCR = "paddleocr"


class BaseTextRule(ABC):
    """
    Clase base para todas las reglas de postprocesamiento de texto.
    """

    rule_id: str
    name: str
    description: str = ""
    target: RuleTarget = RuleTarget.GENERAL
    enabled: bool = True
    priority: int = 100  # Menor número indica mayor prioridad de ejecución

    def __init__(self, enabled: Optional[bool] = None, priority: Optional[int] = None):
        if enabled is not None:
            self.enabled = enabled
        if priority is not None:
            self.priority = priority

    @abstractmethod
    def apply(self, text: str) -> str:
        """
        Aplica la regla sobre una cadena de texto individual.
        
        Args:
            text: Texto de entrada.
            
        Returns:
            Texto procesado / normalizado.
        """
        pass

    def apply_to_element(self, element: TextElement) -> TextElement:
        """Aplica la regla sobre un TextElement individual."""
        if not self.enabled or not element.text:
            return element
        element.text = self.apply(element.text)
        return element

    def apply_to_cell(self, cell: Cell) -> Cell:
        """Aplica la regla sobre una celda de tabla."""
        if not self.enabled or not cell.text:
            return cell
        cell.text = self.apply(cell.text)
        return cell

    def apply_to_table(self, table: Table) -> Table:
        """Aplica la regla sobre los encabezados y celdas de una tabla."""
        if not self.enabled:
            return table

        if table.headers:
            table.headers = [self.apply(h) if h else h for h in table.headers]

        if table.caption:
            table.caption = self.apply(table.caption)

        for row in table.rows:
            for cell in row:
                self.apply_to_cell(cell)

        return table

    def apply_to_page(self, page: Page) -> Page:
        """Aplica la regla sobre todos los elementos de una página."""
        if not self.enabled:
            return page

        for elem in page.elements:
            self.apply_to_element(elem)

        for table in page.tables:
            self.apply_to_table(table)

        if page.raw_text:
            page.raw_text = self.apply(page.raw_text)

        return page

    def apply_to_document(self, document: DocumentModel) -> DocumentModel:
        """
        Aplica la regla sobre la totalidad de un DocumentModel (páginas, tablas, bloques).
        """
        if not self.enabled:
            return document

        # Modifica sobre el documento directamente
        for page in document.pages:
            self.apply_to_page(page)

        for table in document.tables:
            self.apply_to_table(table)

        return document
