"""
Regla general para detección y eliminación inteligente de encabezados y pies de página.
Combina 4 técnicas avanzadas:
1. Repetición inter-página (Cross-page fingerprinting con enmascaramiento de dígitos de página).
2. Filtrado geométrico espacial por zonas de margen (BoundingBox en márgenes superior e inferior).
3. Detección semántica de paginación (ej. 'Página X de Y', 'Pág. X', números aislados).
4. Detección de bloques de contacto corporativo densos (ej. 'OFICINA PRINCIPAL', 'Telf:', 'Fax:', 'email:', 'Central Piloto:').
"""

from collections import Counter
import re
from typing import List, Optional, Set, Tuple

from app.core.models import BoundingBox, DocumentModel, Page, TextElement
from app.postprocess.rules.base import BaseTextRule, RuleTarget


class HeaderFooterRemovalRule(BaseTextRule):
    """
    Elimina encabezados y pies de página en documentos y flujos de texto/Markdown.
    """
    rule_id = "general_header_footer_removal"
    name = "Eliminación de Encabezados y Pies de Página"
    description = (
        "Identifica y elimina encabezados y pies de página mediante análisis de repetición inter-página, "
        "umbrales espaciales de margen, patrones de paginación y heurísticas de contacto corporativo."
    )
    target = RuleTarget.GENERAL
    priority = 15  # Se ejecuta temprano en la cadena de reglas

    # Patrones de paginación
    PAGINATION_LINE_REGEX = re.compile(
        r"^\s*(?:p[aá]gina|p[aá]g\.?|page)\s*\d+(?:\s*(?:de|/)\s*\d+)?\s*$",
        re.IGNORECASE,
    )
    ISOLATED_PAGE_NUM_REGEX = re.compile(
        r"^\s*(?:[-–—]\s*)?\d{1,4}(?:\s*[-–—])?\s*$"
    )

    # Indicadores de contacto corporativo en pies de página
    CONTACT_INDICATORS = [
        re.compile(r"\btelf?[:\.]?\s*\(?\d+", re.IGNORECASE),
        re.compile(r"\bcentral\s+piloto[:\.]?", re.IGNORECASE),
        re.compile(r"\bfax[:\.]?\s*\(?\d+", re.IGNORECASE),
        re.compile(r"\bcasilla[:\.]?\s*\d+", re.IGNORECASE),
        re.compile(r"\bemail[:\.]?\s*[\w\.-]+@[\w\.-]+", re.IGNORECASE),
        re.compile(r"\bcorreo[:\.]?\s*[\w\.-]+@[\w\.-]+", re.IGNORECASE),
        re.compile(r"\bwww\.[\w\.-]+\.[a-z]{2,}", re.IGNORECASE),
        re.compile(r"\boficina\s+principal\b", re.IGNORECASE),
        re.compile(r"\bsucursal(?:\s+\d+|\s+[a-z]+)?\b", re.IGNORECASE),
        re.compile(r"\bcasa\s+matriz\b", re.IGNORECASE),
    ]

    # Ciudades bolivianas / sedes frecuentes en pólizas
    BRANCH_CITIES = [
        "la paz", "santa cruz", "cochabamba", "oruro", "potosi", "potosí",
        "sucre", "tarija", "trinidad", "camiri", "yacuiba", "bolivia"
    ]

    def _is_contact_line(self, line: str) -> bool:
        """Verifica si una línea contiene indicadores de pie de página de contacto."""
        stripped = line.strip()
        if not stripped:
            return False

        # Verificar indicadores principales
        for ind in self.CONTACT_INDICATORS:
            if ind.search(stripped):
                return True

        # Verificar si es un encabezado de sucursal o ciudad aislada dentro de un pie de página
        lower_line = stripped.lower()
        if any(lower_line == city or f"sucursal {city}" in lower_line for city in self.BRANCH_CITIES):
            return True

        return False

    def _remove_contact_footer_blocks(self, text: str) -> str:
        """
        Detecta y elimina bloques de texto que forman un pie de página corporativo de contacto.
        (Ej: Oficinas, teléfonos múltiples, fax, emails, sucursales).
        """
        lines = text.splitlines()
        if len(lines) < 2:
            return text

        n = len(lines)
        is_contact = [self._is_contact_line(line) for line in lines]

        # Encontrar rangos continuos o densos de líneas de contacto
        # Un pie de página de contacto típicamente contiene múltiples indicadores de contacto
        lines_to_remove: Set[int] = set()
        i = 0
        while i < n:
            if is_contact[i]:
                # Iniciar un bloque candidato
                start = i
                # Si la línea anterior es algo como 'OFICINA PRINCIPAL' o una dirección previa, incluirla
                if start > 0 and (
                    "oficina" in lines[start - 1].lower()
                    or "sucursal" in lines[start - 1].lower()
                    or any(c in lines[start - 1].lower() for c in self.BRANCH_CITIES)
                ):
                    start = start - 1

                end = i
                j = i
                indicator_count = 0

                # Expandir mientras haya densidad de contacto (permite hasta 2 líneas intermedias de texto/dirección)
                gap = 0
                while j < n and gap <= 2:
                    if is_contact[j]:
                        indicator_count += 1
                        end = j
                        gap = 0
                    else:
                        gap += 1
                    j += 1

                # Si el bloque contiene 2 o más indicadores de contacto, se considera pie corporativo
                if indicator_count >= 2:
                    for idx in range(start, end + 1):
                        lines_to_remove.add(idx)
                    i = end + 1
                    continue
            i += 1

        if not lines_to_remove:
            return text

        result_lines = [lines[idx] for idx in range(n) if idx not in lines_to_remove]
        return "\n".join(result_lines)

    def _remove_pagination_lines(self, text: str) -> str:
        """Elimina líneas de paginación del texto."""
        cleaned_lines = []
        for line in text.splitlines():
            stripped = line.strip()
            if self.PAGINATION_LINE_REGEX.match(stripped):
                continue
            cleaned_lines.append(line)
        return "\n".join(cleaned_lines)

    def apply(self, text: str) -> str:
        """
        Aplica la regla sobre una cadena de texto (Markdown, TXT o bloque individual).
        """
        if not text:
            return ""

        # 1. Eliminar líneas de paginación
        t = self._remove_pagination_lines(text)

        # 2. Eliminar bloques de contacto corporativo (ej. Credinform, sucursales, teléfonos)
        t = self._remove_contact_footer_blocks(t)

        return t.strip()

    @staticmethod
    def _normalize_for_fingerprint(text: str) -> str:
        """
        Normaliza una cadena para generar una 'huella' que identifique repeticiones inter-página,
        enmascarando números de página variables (ej. 'Página 1 de 10' -> 'pagina <NUM> de <NUM>').
        """
        if not text:
            return ""
        t = text.lower().strip()
        # Enmascarar números
        t = re.sub(r"\d+", "<NUM>", t)
        # Normalizar espacios y signos
        t = re.sub(r"[^\w\s<>]", "", t)
        t = re.sub(r"\s+", " ", t)
        return t.strip()

    def _find_repetitive_signatures(self, document: DocumentModel) -> Set[str]:
        """
        Analiza las páginas del documento y detecta huellas de texto que se repiten
        sistemáticamente en la zona superior (encabezado) o inferior (pie).
        """
        num_pages = len(document.pages)
        if num_pages < 2:
            return set()

        header_counter: Counter = Counter()
        footer_counter: Counter = Counter()

        for page in document.pages:
            p_height = page.height if page.height > 0 else 792.0  # estándar carta en puntos
            top_threshold = 0.15 * p_height
            bottom_threshold = 0.82 * p_height

            page_header_sigs = set()
            page_footer_sigs = set()

            for elem in page.elements:
                text_norm = self._normalize_for_fingerprint(elem.text)
                if not text_norm or len(text_norm) < 3:
                    continue

                if elem.bbox is not None:
                    if elem.bbox.y0 <= top_threshold:
                        page_header_sigs.add(text_norm)
                    elif elem.bbox.y1 >= bottom_threshold:
                        page_footer_sigs.add(text_norm)
                else:
                    # Sin bbox: inferir por orden de lectura relativo
                    if elem.reading_order == 0:
                        page_header_sigs.add(text_norm)
                    elif elem.reading_order >= len(page.elements) - 2:
                        page_footer_sigs.add(text_norm)

            for sig in page_header_sigs:
                header_counter[sig] += 1
            for sig in page_footer_sigs:
                footer_counter[sig] += 1

        repetitive_signatures: Set[str] = set()

        # Un encabezado/pie repetitivo aparece en al menos 2 páginas y al menos el 30% del documento
        min_repeats = max(2, int(num_pages * 0.30)) if num_pages > 2 else 2

        for sig, count in header_counter.items():
            if count >= min_repeats:
                repetitive_signatures.add(sig)

        for sig, count in footer_counter.items():
            if count >= min_repeats:
                repetitive_signatures.add(sig)

        return repetitive_signatures

    def _is_element_header_or_footer(
        self,
        elem: TextElement,
        page_height: float,
        repetitive_sigs: Set[str],
    ) -> bool:
        """Determina si un TextElement individual corresponde a un encabezado o pie de página."""
        # 1. Clasificación previa del motor
        if elem.type in ("header", "footer"):
            return True

        text = elem.text.strip()
        if not text:
            return False

        # 2. Paginación directa
        if self.PAGINATION_LINE_REGEX.match(text) or (
            self.ISOLATED_PAGE_NUM_REGEX.match(text)
            and elem.bbox is not None
            and (elem.bbox.y0 <= 0.12 * page_height or elem.bbox.y1 >= 0.88 * page_height)
        ):
            return True

        # 3. Coincidencia con huella repetitiva inter-página
        sig = self._normalize_for_fingerprint(text)
        if sig in repetitive_sigs:
            return True

        # 4. Indicador de contacto en zona de pie de página
        if elem.bbox is not None and elem.bbox.y1 >= 0.82 * page_height:
            if self._is_contact_line(text):
                return True

        return False

    def apply_to_page(self, page: Page) -> Page:
        """Aplica la regla sobre una página física."""
        if not self.enabled:
            return page

        p_height = page.height if page.height > 0 else 792.0
        filtered_elements = []

        for elem in page.elements:
            if self._is_element_header_or_footer(elem, p_height, set()):
                continue
            # Limpiar contenido del elemento en caso de contener bloques menores
            elem.text = self.apply(elem.text)
            if elem.text.strip():
                filtered_elements.append(elem)

        page.elements = filtered_elements

        if page.raw_text:
            page.raw_text = self.apply(page.raw_text)

        return page

    def apply_to_document(self, document: DocumentModel) -> DocumentModel:
        """
        Aplica la regla sobre la totalidad de un DocumentModel con análisis inter-página.
        """
        if not self.enabled:
            return document

        # 1. Identificar huellas repetitivas entre páginas
        repetitive_sigs = self._find_repetitive_signatures(document)

        # 2. Filtrar elementos en cada página
        for page in document.pages:
            p_height = page.height if page.height > 0 else 792.0
            new_elements: List[TextElement] = []

            for elem in page.elements:
                if self._is_element_header_or_footer(elem, p_height, repetitive_sigs):
                    continue
                # Limpiar texto interno del elemento
                elem.text = self.apply(elem.text)
                if elem.text.strip():
                    new_elements.append(elem)

            page.elements = new_elements

            if page.raw_text:
                page.raw_text = self.apply(page.raw_text)

        # 3. Sincronizar doc.texts con los elementos conservados
        all_remaining_elements = []
        for page in document.pages:
            all_remaining_elements.extend(page.elements)
        document.texts = all_remaining_elements

        return document
