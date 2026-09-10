"""
Sistema de logging estructurado y profesional para el motor de extracción.
"""

import logging
import sys
from pathlib import Path
from typing import Optional

_DEFAULT_FORMAT = "[%(asctime)s] [%(levelname)s] [%(name)s] %(message)s"
_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"


def setup_logger(
    level: str = "INFO",
    log_file: Optional[Path] = None,
    name: Optional[str] = None,
) -> logging.Logger:
    """
    Configura y retorna el logger raíz o un logger nombrado.
    
    Args:
        level: Nivel de severidad ('DEBUG', 'INFO', 'WARNING', 'ERROR').
        log_file: Ruta opcional donde persistir los logs en disco.
        name: Nombre del logger. Si es None, configura el logger raíz.
    """
    numeric_level = getattr(logging, level.upper(), logging.INFO)
    logger = logging.getLogger(name)
    logger.setLevel(numeric_level)

    # Evitar duplicación de handlers si ya ha sido configurado
    if logger.handlers:
        return logger

    formatter = logging.Formatter(fmt=_DEFAULT_FORMAT, datefmt=_DATE_FORMAT)

    # Handler para consola (stdout)
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(numeric_level)
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)

    # Handler opcional para archivo
    if log_file:
        log_file.parent.mkdir(parents=True, exist_ok=True)
        file_handler = logging.FileHandler(log_file, encoding="utf-8")
        file_handler.setLevel(numeric_level)
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)

    return logger


def get_logger(name: str) -> logging.Logger:
    """
    Obtiene un logger hijo configurado con la jerarquía estándar.
    """
    return logging.getLogger(name)
