"""
Exportador a formato Markdown (.md).
Preserva jerarquía de encabezados, listas, orden de lectura y cuadros de coberturas/primas
como tablas en formato GFM (GitHub Flavored Markdown).
"""

from pathlib import Path
from typing import List, Tuple

from pdfextract.core.models import DocumentModel, Table
from pdfextract.engines.base import ExtractionResult
from pdfextract.exporters.base import BaseExporter


class MarkdownExporter(BaseExporter):
    """
    Exportador de documentos a Markdown estructurado para inspección y preparación RAG.
    """

    @property
    def format_name(self) -> str:
        return "md"

    def _format_table_as_markdown(self, table: Table) -> str:
        """
        Convierte una estructura Table a sintaxis de tabla Markdown (GFM) canónica.
        
        Características clave para RAG y fidelidad:
        1. Expande celdas combinadas (rowspan y colspan) replicando el valor en cada posición
           de la cuadrícula, garantizando que cada fila del chunk sea semánticamente autocontenida.
        2. Detecta títulos combinados que ocupan la fila 0 completa y los promueve a título (caption)
           en lugar de duplicar encabezados ficticios.
        3. Escapa pipes (|) y unifica saltos de línea a <br> para respetar la sintaxis GFM.
        """
        if not table.rows:
            return ""

        # Determinar dimensiones reales de la cuadrícula
        num_rows = len(table.rows)
        base_cols = table.num_cols if table.num_cols > 0 else (len(table.headers) if table.headers else 0)
        num_cols = base_cols
        for r_idx, row in enumerate(table.rows):
            for cell in row:
                num_cols = max(num_cols, cell.col_index + 1)
        if base_cols > 0:
            num_cols = max(base_cols, num_cols)

        if num_cols == 0:
            return ""

        # Construir matriz bidimensional vacía
        grid: List[List[str]] = [["" for _ in range(num_cols)] for _ in range(num_rows)]
        is_header_row = [False] * num_rows

        # Poblar matriz expandiendo row_span verticalmente para mantener autocontenidos los chunks RAG,
        # pero evitando duplicación horizontal redundante en col_span que contamina las columnas.
        for r_idx, row in enumerate(table.rows):
            covered_until = -1
            for cell in row:
                raw_text = cell.text if cell.text else ""
                clean_cell = raw_text.replace("|", "\\|").replace("\r\n", "<br>").replace("\n", "<br>").strip()

                r_start = cell.row_index if cell.row_index < num_rows else r_idx
                c_start = cell.col_index
                if c_start >= num_cols:
                    continue

                # Si esta celda ya está dentro de un rango col_span cubierto horizontalmente en esta fila,
                # no duplicamos el contenido para evitar columnas redundantes en GFM.
                if c_start < covered_until:
                    continue

                r_span = max(1, cell.row_span)
                max_c_span = num_cols - c_start
                c_span = min(max(1, cell.col_span), max_c_span)
                covered_until = c_start + c_span

                # Replicar verticalmente a lo largo de r_span para autocontención RAG
                for dr in range(r_span):
                    r_target = r_start + dr
                    while len(grid) <= r_target:
                        grid.append(["" for _ in range(num_cols)])
                        is_header_row.append(False)
                    grid[r_target][c_start] = clean_cell
                    if cell.is_header:
                        is_header_row[r_target] = True

        caption_text = table.caption.strip() if table.caption else ""
        start_data_idx = 0
        header_cells: List[str] = []

        # 1. Detectar si la fila 0 es un título que abarca todas las columnas (ej. 'CONDICION DE PAGO')
        if len(grid) > 1 and num_cols > 1:
            row0_non_empty = [c for c in grid[0] if c]
            is_single_title = (len(row0_non_empty) == 1 and bool(row0_non_empty[0]))
            is_repeated_title = bool(row0_non_empty and len(set(row0_non_empty)) == 1 and len(row0_non_empty) >= max(2, num_cols // 2))
            if is_single_title or is_repeated_title:
                title_cand = row0_non_empty[0]
                row1_distinct = len(set(c for c in grid[1] if c))
                # Si la fila 1 tiene múltiples columnas distintas o es la última fila de encabezados
                if row1_distinct > 1 or len(grid) == 2:
                    if not caption_text:
                        caption_text = title_cand
                    header_cells = grid[1]
                    start_data_idx = 2

        # 2. Si no se detectó título promovido, buscar encabezados en table.headers o en fila 0
        if not header_cells:
            if table.headers and len(table.headers) == num_cols and len(set(table.headers)) > 1:
                clean_headers: List[str] = []
                prev_h = None
                for h in table.headers:
                    h_clean = h.replace("|", "\\|").replace("\n", " ").strip()
                    if h_clean and h_clean == prev_h:
                        clean_headers.append("")
                    else:
                        clean_headers.append(h_clean)
                        prev_h = h_clean
                header_cells = clean_headers
                # Si la fila 0 de la cuadrícula coincide con los encabezados, los datos comienzan en fila 1
                if grid and grid[0] and (grid[0] == header_cells or (grid[0][0] and grid[0][0] == header_cells[0])):
                    start_data_idx = 1
                else:
                    start_data_idx = 0
            elif grid:
                header_cells = grid[0]
                start_data_idx = 1

        # 3. Si los encabezados siguen vacíos o son todos idénticos, generar nombres por defecto
        if not header_cells or len(set(header_cells)) <= 1:
            if len(set(header_cells)) == 1 and header_cells[0]:
                if not caption_text:
                    caption_text = header_cells[0]
            header_cells = [f"Columna {c + 1}" for c in range(num_cols)]
            start_data_idx = 0

        # Normalizar celdas vacías en la cabecera
        header_cells = [h if h.strip() else f"Columna {c + 1}" for c, h in enumerate(header_cells)]

        md_lines: List[str] = []
        if caption_text:
            md_lines.append(f"**Tabla: {caption_text}**\n")

        # Fila de encabezado
        md_lines.append("| " + " | ".join(header_cells) + " |")
        md_lines.append("| " + " | ".join(["---"] * num_cols) + " |")

        # Filas de datos
        for r in range(start_data_idx, len(grid)):
            row_vals = grid[r]
            if not any(v.strip() for v in row_vals):
                continue
            md_lines.append("| " + " | ".join(row_vals) + " |")

        return "\n".join(md_lines)

    def export(
        self,
        result: ExtractionResult,
        output_dir: Path,
        base_filename: str,
        prefer_synthesized: bool = True,
    ) -> Path:
        """
        Genera el archivo .md en el directorio de salida.
        
        Args:
            result: Resultado de extracción con DocumentModel y datos brutos.
            output_dir: Directorio destino.
            base_filename: Nombre base para el archivo .md.
            prefer_synthesized: Si es True (por defecto), sintetiza el Markdown a partir
                del DocumentModel limpio y canónico, aplicando la expansión de celdas
                combinadas y las reglas de texto. Si es False y existe markdown_text nativo,
                lo utiliza como fallback.
        """
        output_dir.mkdir(parents=True, exist_ok=True)
        target_path = output_dir / f"{base_filename}.md"

        native_md = result.raw_output.get("markdown_text")

        if not prefer_synthesized and native_md and isinstance(native_md, str) and len(native_md.strip()) > 0:
            header = (
                f"<!-- Documento: {result.document.metadata.filename} -->\n"
                f"<!-- Motor: {result.engine_name} | Páginas: {result.document.metadata.total_pages} -->\n\n"
            )
            content = header + native_md.strip() + "\n"
        else:
            # Sintetizar Markdown fiel desde el DocumentModel estructurado
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

                    # Intercalar textos y tablas según su posición espacial en la página.
                    # Cuantizamos y0 en bandas (tolerancia de 4 puntos) para agrupar elementos
                    # que pertenecen a la misma línea horizontal y ordenarlos de izquierda a derecha (x0),
                    # garantizando que las etiquetas queden unidas a sus respectivos valores.
                    page_blocks: List[Tuple[float, float, str]] = []

                    for elem in page.elements:
                        text = elem.text.strip()
                        if not text:
                            continue

                        y0_pos = elem.bbox.y0 if (elem.bbox and elem.bbox.y0 is not None) else float(elem.reading_order * 10)
                        x0_pos = elem.bbox.x0 if (elem.bbox and elem.bbox.x0 is not None) else 0.0
                        y_band = round(y0_pos / 4.0) * 4.0

                        if elem.type == "title":
                            blk_text = f"# {text}\n"
                        elif elem.type == "section_header":
                            blk_text = f"## {text}\n"
                        elif elem.type == "list_item":
                            blk_text = f"- {text}"
                        else:
                            blk_text = f"{text}\n"

                        page_blocks.append((y_band, x0_pos, blk_text))

                    for t_idx, table in enumerate(page.tables):
                        tbl_md = self._format_table_as_markdown(table)
                        if not tbl_md:
                            continue

                        t_y0 = 9999.0
                        if table.bbox and table.bbox.y0 is not None:
                            t_y0 = table.bbox.y0
                        elif table.rows and table.rows[0] and table.rows[0][0].bbox and table.rows[0][0].bbox.y0 is not None:
                            t_y0 = table.rows[0][0].bbox.y0

                        y_band = round(t_y0 / 4.0) * 4.0
                        page_blocks.append((y_band, 0.0, "\n" + tbl_md + "\n"))

                    # Ordenar por banda vertical y posición horizontal de izquierda a derecha
                    page_blocks.sort(key=lambda b: (b[0], b[1]))

                    for _, _, block_content in page_blocks:
                        lines.append(block_content)
            else:
                doc_blocks: List[Tuple[float, float, str]] = []
                for elem in doc.texts:
                    text = elem.text.strip()
                    if not text:
                        continue
                    y0_pos = elem.bbox.y0 if (elem.bbox and elem.bbox.y0 is not None) else float(elem.reading_order * 10)
                    x0_pos = elem.bbox.x0 if (elem.bbox and elem.bbox.x0 is not None) else 0.0
                    y_band = round(y0_pos / 4.0) * 4.0
                    doc_blocks.append((y_band, x0_pos, f"{text}\n"))

                for t_idx, table in enumerate(doc.tables):
                    tbl_md = self._format_table_as_markdown(table)
                    if not tbl_md:
                        continue
                    t_y0 = 9999.0
                    if table.bbox and table.bbox.y0 is not None:
                        t_y0 = table.bbox.y0
                    elif table.rows and table.rows[0] and table.rows[0][0].bbox and table.rows[0][0].bbox.y0 is not None:
                        t_y0 = table.rows[0][0].bbox.y0
                    y_band = round(t_y0 / 4.0) * 4.0
                    doc_blocks.append((y_band, 0.0, "\n" + tbl_md + "\n"))

                doc_blocks.sort(key=lambda b: (b[0], b[1]))
                for _, _, block_content in doc_blocks:
                    lines.append(block_content)

            content = "\n".join(lines).strip() + "\n"

        with open(target_path, "w", encoding="utf-8") as f:
            f.write(content)

        return target_path
