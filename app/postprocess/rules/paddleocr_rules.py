"""
Reglas específicas de postprocesamiento para el motor PaddleOCR-VL.
Diseñadas para corregir artefactos de reconocimiento óptico de caracteres (OCR) y escaneos.
"""

import re
from app.postprocess.rules.base import BaseTextRule, RuleTarget


class PaddleOCRDehyphenationRule(BaseTextRule):
    """
    Une palabras partidas por un guion al final de línea debido al salto de párrafo u OCR:
    Ejemplo:
      "las cober- \\nturas de la póliza" -> "las coberturas de la póliza"
      "asegura- \\n\\ndo" -> "asegurado"
    Preserva guiones entre números (ej. '2023-2024') o rangos/códigos.
    """
    rule_id = "paddleocr_dehyphenation"
    name = "Reconstrucción de Palabras Hifenadas (Dehyphenation)"
    description = "Une palabras del idioma español partidas al final de una línea por un guion de división silábica."
    target = RuleTarget.PADDLEOCR
    priority = 30

    def apply(self, text: str) -> str:
        if not text:
            return ""

        # Letras en español (incluyendo vocales acentuadas y ñ)
        # Busca: letra + guion + espacio(s)/salto(s) de línea + letra
        pattern = r"([a-zA-ZáéíóúüñÁÉÍÓÚÜÑ])-[\s\r\n]+([a-zA-ZáéíóúüñÁÉÍÓÚÜÑ])"
        return re.sub(pattern, r"\1\2", text)


class PaddleOCRSpeckleCleanupRule(BaseTextRule):
    """
    Elimina líneas huérfanas o 'motas de ruido' producidas por el escáner:
    Líneas que contienen únicamente un punto, coma, comilla, guion o símbolo aislado sin contexto textual.
    """
    rule_id = "paddleocr_speckle_cleanup"
    name = "Limpieza de Ruido de Escaneo (Speckles)"
    description = "Elimina caracteres huérfanos o líneas residuales de ruido visual procedentes de escaneos."
    target = RuleTarget.PADDLEOCR
    priority = 50

    def apply(self, text: str) -> str:
        if not text:
            return ""

        cleaned_lines = []
        for line in text.splitlines():
            stripped = line.strip()
            # Si la línea tiene 1 solo caracter y es un símbolo de puntuación/ruido
            if len(stripped) == 1 and stripped in ".,;:'\"`~_-|/\\*":
                continue
            # Si contiene sólo símbolos de ruido repetidos cortos (ej. '...', '--', '~~')
            if len(stripped) <= 3 and all(c in ".,;:'\"`~_-|/\\*" for c in stripped):
                continue
            cleaned_lines.append(line)

        return "\n".join(cleaned_lines)
