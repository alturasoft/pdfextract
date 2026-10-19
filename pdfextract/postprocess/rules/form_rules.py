"""
Regla especializada para desenredar y normalizar tablas/bloques de formulario
clave-valor cuando el motor de extracción agrupa primero las etiquetas
y luego los valores (desfase por orden de lectura en columnas).
"""

import re
from typing import List, Tuple

from pdfextract.core.logger import get_logger
from pdfextract.postprocess.rules.base import BaseTextRule, RuleTarget

logger = get_logger("FormRules")


class ColumnarFormDisentangleRule(BaseTextRule):
    """
    Identifica bloques de formulario de pólizas donde las claves y valores
    se encuentran desfasados en listas contiguas (típico artefacto de
    lectura columnar en cuadros con bordes/sombras).
    
    Recombina las etiquetas y valores de forma consistente 1 a 1:
        Producto:
        Tipo de Póliza:
        ...
        3604 AUT SUDAMERICANA BS.
        Individual
        ...
        ->
        Producto: 3604 AUT SUDAMERICANA BS.
        Tipo de Póliza: Individual
    """
    rule_id = "general_columnar_form_disentangle"
    name = "Desenredo de Formularios Clave-Valor en Columnas"
    description = (
        "Recombina etiquetas y valores cuando el motor extrae primero una columna "
        "de claves y luego la columna de valores correspondiente."
    )
    target = RuleTarget.GENERAL
    priority = 22  # Se ejecuta justo antes de DoclingKeyValueJoinRule (25)

    # Etiquetas conocidas de póliza que pueden no llevar ':' al final
    KNOWN_FORM_LABELS = {
        "forma de pago",
        "tipo de poliza",
        "tipo de póliza",
        "frecuencia de pago",
        "direccion",
        "dirección",
        "contratante",
        "vigencia",
        "producto",
        "agente",
        "poliza",
        "póliza",
        "asegurado",
        "subagente",
    }

    _RE_KEY_LINE = re.compile(
        r"^[A-Za-zÁÉÍÓÚáéíóúÑñüÜ\s/\.]{2,30}:?\s*$"
    )

    def _is_form_key_candidate(self, line: str) -> bool:
        """Determina si una línea aislada parece ser una etiqueta de clave sin valor."""
        stripped = line.strip()
        if not stripped:
            return False

        # Si ya tiene valor tras ':' (ej: "Código: 123"), no es clave huérfana
        if ":" in stripped:
            parts = stripped.split(":", 1)
            if parts[1].strip():
                return False

        # No puede ser encabezado Markdown, lista ni separador
        if stripped.startswith(("#", "-", "*", ">", "|")):
            return False

        # Demasiadas palabras no es etiqueta de campo
        words = stripped.split()
        if len(words) > 5:
            return False

        # Si termina en ':' o coincide con etiqueta conocida
        if stripped.endswith(":"):
            clean_name = stripped[:-1].strip()
            return bool(self._RE_KEY_LINE.match(clean_name))

        lower = stripped.lower()
        if lower in self.KNOWN_FORM_LABELS:
            return True

        return False

    def _normalize_vigencia(self, val: str) -> str:
        """Normaliza 'Hasta el... Desde el...' a orden cronológico 'Desde el... Hasta el...'."""
        m = re.match(
            r"^(Hasta\s+el\s+.+?)\s+(Desde\s+el\s+.+)$",
            val,
            re.IGNORECASE,
        )
        if m:
            return f"{m.group(2).strip()} {m.group(1).strip()}"
        return val

    def apply(self, text: str) -> str:
        if not text:
            return ""

        raw_lines = text.splitlines()
        n = len(raw_lines)
        output: List[str] = []

        i = 0
        while i < n:
            line = raw_lines[i]
            stripped = line.strip()

            # Detectar si se inicia una secuencia de claves contiguas (>= 3 claves)
            if self._is_form_key_candidate(stripped):
                key_lines: List[Tuple[int, str]] = [(i, stripped)]
                j = i + 1
                # Recorrer consumiendo líneas vacías intermedias y acumulando claves
                while j < n:
                    next_s = raw_lines[j].strip()
                    if not next_s:
                        j += 1
                        continue
                    if self._is_form_key_candidate(next_s):
                        key_lines.append((j, next_s))
                        j += 1
                    else:
                        break

                # Si tenemos una ráfaga de al menos 3 claves consecutivas
                if len(key_lines) >= 3:
                    k_count = len(key_lines)
                    val_lines: List[str] = []
                    curr_val_idx = j

                    while curr_val_idx < n:
                        val_s = raw_lines[curr_val_idx].strip()
                        if not val_s:
                            curr_val_idx += 1
                            continue

                        # Si encontramos un salto estructural, encabezado o nuevo bloque de clave
                        if val_s.startswith(("#", "---", "===")) or len(val_s) > 200:
                            break

                        # Si encontramos una nueva clave con ':' y su propio valor (ej. "Póliza: 10229219")
                        if ":" in val_s:
                            prefix, rest = val_s.split(":", 1)
                            if rest.strip() and len(prefix.split()) <= 4:
                                break

                        val_lines.append(val_s)
                        curr_val_idx += 1

                        # Si ya tenemos suficientes valores para cubrir las claves
                        if len(val_lines) >= k_count:
                            # Permitir absorber hasta 2 líneas adicionales si pertenecen al último valor compuesto (ej: agente código + nombre)
                            look_ahead = curr_val_idx
                            while look_ahead < n:
                                peek = raw_lines[look_ahead].strip()
                                if not peek:
                                    look_ahead += 1
                                    continue
                                if peek.startswith(("#", "---")) or ":" in peek or len(peek) > 150:
                                    break
                                if len(val_lines) < k_count + 2:
                                    val_lines.append(peek)
                                    look_ahead += 1
                                else:
                                    break
                            curr_val_idx = look_ahead
                            break

                    # Si encontramos valores para emparejar con las claves
                    if len(val_lines) >= k_count:
                        # Si hay valores extra, agrupar los excedentes en el último valor
                        if len(val_lines) > k_count:
                            merged_last = " ".join(val_lines[k_count - 1:])
                            val_lines = val_lines[:k_count - 1] + [merged_last]

                        for (k_idx, k_text), val in zip(key_lines, val_lines):
                            clean_k = k_text.rstrip(":").strip()
                            clean_v = val.strip()
                            if "vigencia" in clean_k.lower():
                                clean_v = self._normalize_vigencia(clean_v)
                            output.append(f"{clean_k}: {clean_v}")

                        i = curr_val_idx
                        continue

            # Línea normal no perteneciente a bloque columnar
            output.append(line)
            i += 1

        return "\n".join(output)
