"""
Módulo core: configuración, modelos canónicos, logging y monitor de sistema.
"""

from app.core.config import AppConfig, load_config
from app.core.logger import get_logger, setup_logger
from app.core.models import (
    BoundingBox,
    Cell,
    Table,
    TextElement,
    Page,
    DocumentMetadata,
    RAGChunk,
    DocumentModel,
)

__all__ = [
    "AppConfig",
    "load_config",
    "get_logger",
    "setup_logger",
    "BoundingBox",
    "Cell",
    "Table",
    "TextElement",
    "Page",
    "DocumentMetadata",
    "RAGChunk",
    "DocumentModel",
]
