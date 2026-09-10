"""
Exportador a texto plano (.txt).
Genera una representación legible del documento preservando orden de lectura,
separación lógica de párrafos, encabezados, tablas formateadas y saltos de página.
"""

from pathlib import Path
from typing import List

from pdfextract.core.models import Cell, DocumentModel, Table
from pdfextract.engines.base import ExtractionResult
from pdfextract.exporters.base import BaseExporter


class TxtExporter(BaseExporter):
    """
    Exportador de texto plano estructurado.
    """

    @property
    def format_name(self) -> str:
        return "txt"

    def _format_table_as_text(self, table: Table) -> str:
        """Formatea una tabla en texto plano alineado con caracteres visuales."""
        if not table.rows:
            return ""

        # Extraer filas como listas de strings
        str_rows: List[List[str]] = []
        for row in table.rows:
            str_rows.append([cell.text.replace("\n", " ").strip() for cell in row])

        if not str_rows:
            return ""

        # Calcular anchos de columnas
        num_cols = max(len(r) for r in str_rows)
        col_widths = [0] * num_cols
        for row in str_rows:
            for c_idx, cell_str in enumerate(row):
                if c_idx < num_cols:
                    col_widths[c_idx] = max(col_widths[c_idx], len(cell_str))

        # Ajustar ancho mínimo y máximo por legibilidad
        col_widths = [max(min(w, 50), 4) for w in col_widths]

        lines = []
        separator = "+-" + "-+-".join("-" * w for w in col_widths) + "-+"

        if table.caption:
            lines.append(f"[TABLA: {table.caption}]")
        lines.append(separator)

        for r_idx, row in enumerate(str_rows):
            row_cells = []
            for c_idx in range(num_cols):
                val = row[c_idx] if c_idx < len(row) else ""
                w = col_widths[c_idx]
                row_cells.append(val[:w].ljust(w))
            lines.append("| " + " | ".join(row_cells) + " |")

            # Separador tras el encabezado
            if r_idx == 0 and (table.headers or any(c.is_header for c in table.rows[0])):
                lines.append(separator)

        lines.append(separator)
        return "\n".join(lines)

    def export(self, result: ExtractionResult, output_dir: Path, base_filename: str) -> Path:
        """
        Genera el archivo .txt en el directorio de salida.
        """
        output_dir.mkdir(parents=True, exist_ok=True)
        target_path = output_dir / f"{base_filename}.txt"

        doc = result.document
        lines: List[str] = []

        # Encabezado del documento
        lines.append("=" * 80)
        lines.append(f"DOCUMENTO: {doc.metadata.filename}")
        lines.append(f"MOTOR DE EXTRACCIÓN: {result.engine_name.upper()}")
        lines.append(f"TOTAL DE PÁGINAS: {doc.metadata.total_pages}")
        lines.append(f"FECHA DE EXTRACCIÓN: {doc.metadata.created_at}")
        lines.append("=" * 80)
        lines.append("")

        if doc.pages:
            for page in doc.pages:
                lines.append(f"--- [PÁGINA {page.page_number}] ---")
                lines.append("")

                # Elementos de la página ordenados por lectura
                sorted_elements = sorted(page.elements, key=lambda e: e.reading_order)
                for elem in sorted_elements:
                    text = elem.text.strip()
                    if not text:
                        continue

                    if elem.type in ("title", "section_header"):
                        lines.append("")
                        lines.append(f"## {text.upper()}")
                        lines.append("")
                    elif elem.type == "list_item":
                        lines.append(f"  * {text}")
                    else:
                        lines.append(text)
                        lines.append("")

                # Tablas asociadas a esta página
                for table in page.tables:
                    lines.append("")
                    lines.append(self._format_table_as_text(table))
                    lines.append("")

                lines.append("")
        else:
            # Si no hay páginas mapeadas, volcar textos y tablas globales
            for elem in sorted(doc.texts, key=lambda e: e.reading_order):
                lines.append(elem.text)
                lines.append("")

            for table in doc.tables:
                lines.append(self._format_table_as_text(table))
                lines.append("")

        content = "\n".join(lines).strip() + "\n"
        with open(target_path, "w", encoding="utf-8") as f:
            f.write(content)

        return target_path
