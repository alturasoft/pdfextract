"""
Exportador a formato Markdown (.md).
Preserva jerarquía de encabezados, listas, orden de lectura y cuadros de coberturas/primas
como tablas en formato GFM (GitHub Flavored Markdown).
"""

from pathlib import Path
from typing import List

from app.core.models import DocumentModel, Table
from app.engines.base import ExtractionResult
from app.exporters.base import BaseExporter


class MarkdownExporter(BaseExporter):
    """
    Exportador de documentos a Markdown estructurado para inspección y preparación RAG.
    """

    @property
    def format_name(self) -> str:
        return "md"

    def _format_table_as_markdown(self, table: Table) -> str:
        """Convierte una estructura Table a sintaxis de tabla Markdown (GFM)."""
        if not table.rows:
            return ""

        md_lines: List[str] = []
        if table.caption:
            md_lines.append(f"**Tabla: {table.caption}**\n")

        # Determinar encabezados
        first_row = table.rows[0]
        has_header = table.headers or any(c.is_header for c in first_row)

        if table.headers:
            header_cells = [h.replace("|", "\\|").replace("\n", " ").strip() for h in table.headers]
        else:
            header_cells = [c.text.replace("|", "\\|").replace("\n", " ").strip() for c in first_row]

        num_cols = len(header_cells)
        if num_cols == 0:
            return ""

        # Fila de encabezado
        md_lines.append("| " + " | ".join(header_cells) + " |")
        md_lines.append("| " + " | ".join(["---"] * num_cols) + " |")

        # Filas de datos
        start_idx = 1 if (has_header and not table.headers) else 0
        for row in table.rows[start_idx:]:
            row_vals = []
            for col_i in range(num_cols):
                if col_i < len(row):
                    cell_text = row[col_i].text.replace("|", "\\|").replace("\n", " ").strip()
                    row_vals.append(cell_text)
                else:
                    row_vals.append("")
            md_lines.append("| " + " | ".join(row_vals) + " |")

        return "\n".join(md_lines)

    def export(self, result: ExtractionResult, output_dir: Path, base_filename: str) -> Path:
        """
        Genera el archivo .md en el directorio de salida.
        """
        output_dir.mkdir(parents=True, exist_ok=True)
        target_path = output_dir / f"{base_filename}.md"

        # Si el motor produjo un markdown nativo directo de alta calidad, evaluamos su uso
        native_md = result.raw_output.get("markdown_text")

        if native_md and isinstance(native_md, str) and len(native_md.strip()) > 0:
            # Añadir cabecera informativa de trazabilidad
            header = (
                f"<!-- Documento: {result.document.metadata.filename} -->\n"
                f"<!-- Motor: {result.engine_name} | Páginas: {result.document.metadata.total_pages} -->\n\n"
            )
            content = header + native_md.strip() + "\n"
        else:
            # Sintetizar Markdown fiel desde el DocumentModel
            doc = result.document
            lines: List[str] = [
                f"# {doc.metadata.filename}\n",
                f"> **Motor de extracción**: {result.engine_name.upper()}  ",
                f"> **Total páginas**: {doc.metadata.total_pages}  ",
                f"> **Integridad SHA-256**: `{doc.metadata.file_hash_sha256}`\n",
                "---\n",
            ]

            if doc.pages:
                for page in doc.pages:
                    lines.append(f"\n<!-- Página {page.page_number} -->\n")
                    sorted_elements = sorted(page.elements, key=lambda e: e.reading_order)

                    for elem in sorted_elements:
                        text = elem.text.strip()
                        if not text:
                            continue

                        if elem.type == "title":
                            lines.append(f"# {text}\n")
                        elif elem.type == "section_header":
                            lines.append(f"## {text}\n")
                        elif elem.type == "list_item":
                            lines.append(f"- {text}")
                        else:
                            lines.append(f"{text}\n")

                    for table in page.tables:
                        lines.append("\n" + self._format_table_as_markdown(table) + "\n")
            else:
                for elem in sorted(doc.texts, key=lambda e: e.reading_order):
                    lines.append(f"{elem.text}\n")
                for table in doc.tables:
                    lines.append("\n" + self._format_table_as_markdown(table) + "\n")

            content = "\n".join(lines).strip() + "\n"

        with open(target_path, "w", encoding="utf-8") as f:
            f.write(content)

        return target_path
