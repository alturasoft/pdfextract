"""
Módulo de exportadores documentales desacoplados.
"""

from pdfextract.exporters.base import BaseExporter
from pdfextract.exporters.txt_exporter import TxtExporter
from pdfextract.exporters.markdown_exporter import MarkdownExporter
from pdfextract.exporters.json_exporter import JsonExporter

__all__ = [
    "BaseExporter",
    "TxtExporter",
    "MarkdownExporter",
    "JsonExporter",
]
