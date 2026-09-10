"""
Reglas generales de postprocesamiento de texto.
Aplican de forma global a todos los motores y a la fase de consenso final.
"""

import re
from app.postprocess.rules.base import BaseTextRule, RuleTarget


class CleanWhitespaceRule(BaseTextRule):
    """
    Normaliza espacios redundantes:
    - Reemplaza espacios múltiples horizontales por uno solo.
    - Elimina espacios al final de cada línea.
    - Reduce 3 o más saltos de línea consecutivos a un máximo de dos.
    - Elimina espacios en blanco al inicio y final del bloque.
    """
    rule_id = "general_clean_whitespace"
    name = "Limpieza de Espacios en Blanco"
    description = "Normaliza espacios redundantes, saltos de línea excesivos y espacios al final de línea."
    target = RuleTarget.GENERAL
    priority = 10

    def apply(self, text: str) -> str:
        if not text:
            return ""

        # 1. Normalizar tabulaciones y espacios no rompibles
        t = text.replace("\t", " ").replace("\u00a0", " ")

        # 2. Reducir múltiples espacios horizontales dentro de cada línea
        t = re.sub(r"[^\S\r\n]+", " ", t)

        # 3. Eliminar espacios al inicio y final de cada línea
        lines = [line.strip() for line in t.splitlines()]
        t = "\n".join(lines)

        # 4. Reducir más de 2 saltos de línea consecutivos a exactamente 2
        t = re.sub(r"\n{3,}", "\n\n", t)

        return t.strip()


class NormalizeTypographyRule(BaseTextRule):
    """
    Normaliza signos tipográficos comúnmente heterogéneos en PDFs:
    - Comillas tipográficas (“ ”, « », „ ‟) -> comilla estándar "
    - Comillas simples tipográficas (‘ ’, ‚ ‛) -> apóstrofe '
    - Guiones largos, medios y signos menos (–, —, −) -> guion estándar -
    """
    rule_id = "general_normalize_typography"
    name = "Normalización Tipográfica"
    description = "Estandariza comillas curvas, guiones largos/medios y signos menos a caracteres ASCII estándar."
    target = RuleTarget.GENERAL
    priority = 20

    def apply(self, text: str) -> str:
        if not text:
            return ""

        # Comillas dobles
        t = re.sub(r"[“”«»„‟]", '"', text)

        # Comillas simples
        t = re.sub(r"[‘’‚‛]", "'", t)

        # Guiones y rayas
        t = re.sub(r"[–—−]", "-", t)

        return t
