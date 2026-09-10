"""
Reglas específicas de postprocesamiento para el motor Docling.
Diseñadas para corregir artefactos de parseo estructural nativo y sintaxis Markdown/HTML.
"""

import re
from app.postprocess.rules.base import BaseTextRule, RuleTarget


class DoclingMarkdownArtifactsRule(BaseTextRule):
    """
    Limpia artefactos HTML y comentarios generados residualmente por Docling:
    - Remueve comentarios HTML (<!-- ... -->).
    - Convierte etiquetas <br> o <br/> en saltos de línea.
    - Remueve etiquetas HTML vacías residuales (ej. <span></span>, <div></div>).
    - Elimina escapes excesivos de barras invertidas en caracteres comunes (ej. \\-, \\*).
    """
    rule_id = "docling_markdown_artifacts"
    name = "Limpieza de Artefactos Markdown y HTML de Docling"
    description = "Elimina comentarios HTML, normaliza etiquetas <br> y remueve escapes innecesarios de Docling."
    target = RuleTarget.DOCLING
    priority = 30

    def apply(self, text: str) -> str:
        if not text:
            return ""

        # Eliminar comentarios HTML
        t = re.sub(r"<!--.*?-->", "", text, flags=re.DOTALL)

        # Convertir <br> o <br/> a salto de línea
        t = re.sub(r"<br\s*/?>", "\n", t, flags=re.IGNORECASE)

        # Eliminar tags HTML vacíos o residuales comunes
        t = re.sub(r"<\/?(span|div|p|b|i|strong|em)\b[^>]*>", "", t, flags=re.IGNORECASE)

        # Quitar barras invertidas de escape innecesarias frente a caracteres comunes
        t = re.sub(r"\\([_\*\[\]\(\)\~\`\>\#\+\-\=\|\{\}\.\!])", r"\1", t)

        return t.strip()


class DoclingHeaderCleanRule(BaseTextRule):
    """
    Normaliza encabezados y títulos extraídos por Docling:
    - Elimina marcadores de encabezado redundantes o duplicados (ej. '### ### Sección' -> '### Sección').
    - Elimina hashes huérfanos o al final de líneas de título (ej. '### Título ###' -> '### Título').
    """
    rule_id = "docling_header_clean"
    name = "Limpieza de Encabezados de Docling"
    description = "Normaliza sintaxis repetitiva de encabezados Markdown generados por Docling."
    target = RuleTarget.DOCLING
    priority = 40

    def apply(self, text: str) -> str:
        if not text:
            return ""

        lines = []
        for line in text.splitlines():
            # Si la línea contiene múltiples grupos de '#'
            cleaned_line = re.sub(r"^(#{1,6})\s+(?:#{1,6}\s+)+", r"\1 ", line)
            # Eliminar '#' de cierre al final de la línea
            cleaned_line = re.sub(r"\s+#+\s*$", "", cleaned_line)
            lines.append(cleaned_line)

        return "\n".join(lines)


class DoclingKeyValueJoinRule(BaseTextRule):
    """
    Reconstruye pares "Clave: Valor" fragmentados por Docling.

    Docling separa frecuentemente un par Clave/Valor en lineas distintas,
    con o sin linea en blanco entre ellas:

        Patron 1 - sin linea vacia:
            Poliza Anterior AUT-SCR0667473
            AUT-SCR0604018

        Patron 2 - con linea vacia (muy comun en Docling):
            Telefono
            (linea vacia)
            -.-

    Esta regla reune ambos patrones en una sola linea usando ": " como
    separador:

        Poliza Anterior: AUT-SCR0667473 AUT-SCR0604018
        Telefono: -.-

    Criterios de deteccion de clave pendiente:
    - La linea no contiene ":" (nombre de campo solo) O termina en ":" sin valor.
    - La linea es corta (menor o igual a MAX_KEY_WORDS palabras).
    - No es encabezado Markdown, separador de seccion ni vineta de lista.

    Las lineas vacias entre clave y valor son consumidas silenciosamente.
    Las lineas vacias sin clave pendiente se conservan tal cual.
    """

    rule_id = "docling_key_value_join"
    name = "Reconstruccion de Pares Clave-Valor de Docling"
    description = (
        "Reune en una sola linea los fragmentos Clave y Valor que "
        "Docling separa en lineas diferentes (con o sin linea vacia entre "
        "ellas), manteniendo el separador ':'."
    )
    target = RuleTarget.DOCLING
    priority = 25  # Antes de markdown_artifacts (30) y header_clean (40)

    # Maximo de palabras que puede tener una "clave" candidata.
    MAX_KEY_WORDS: int = 6

    # Lineas estructurales que no pueden ser una clave.
    _RE_NON_KEY = re.compile(
        r"""
        ^(?:
            \#{1,6}\s      |
            [=\-]{3,}\s*$  |
            [-*+]\s        |
            \d+\.\s        |
            >\s
        )
        """,
        re.VERBOSE,
    )

    # Linea que ya tiene clave Y valor no vacio.
    _RE_HAS_VALUE = re.compile(r"^[^:]+:\s*\S")

    # Linea con ":" pero sin valor util.
    _RE_KEY_NO_VALUE = re.compile(r"^([^:]+):\s*$")

    def _is_structural(self, line: str) -> bool:
        return bool(self._RE_NON_KEY.match(line))

    # Patron que identifica "valores tipicos" que nunca son nombres de campo:
    # - Empieza por digito
    # - Empieza por simbolo/puntuacion (ej. -.- @ # $ / . ,)
    # - Solo contiene digitos, guiones, puntos, '@' (numeros, telefonos, emails...)
    _RE_VALUE_LIKE = re.compile(
        r"""
        ^(?:
            \d              |   # empieza por digito
            [-./,@#$%()_]  |   # empieza por signo/simbolo tipico de valor
            [^\w]               # empieza por cualquier no-palabra (unicode)
        )
        """,
        re.VERBOSE,
    )

    # Patron que valida que UNA PALABRA sea propia de un nombre de campo:
    # solo letras (con acentos/enies), puntos internos y guiones internos.
    # Ej: "Nro.", "E-mail", "NIT" -> validos
    # Ej: "AUT-SCR0667473", "3437878", "SC." con digitos -> invalidos
    _RE_KEY_WORD = re.compile(
        r"^[a-zA-Z\u00e1\u00e9\u00ed\u00f3\u00fa\u00fc\u00f1\u00c1\u00c9\u00cd\u00d3\u00da\u00dc\u00d1]"  # empieza por letra
        r"[a-zA-Z\u00e1\u00e9\u00ed\u00f3\u00fa\u00fc\u00f1\u00c1\u00c9\u00cd\u00d3\u00da\u00dc\u00d1.\-]*:?$"  # letras/puntos/guiones, ':' final opcional
    )

    # Token de valor: contiene digito(s) o es todo mayusculas con 4+ chars
    # (codigos como "AUT-SCR0667473", "NORTE", "JUAN", "SC.")
    _RE_VALUE_TOKEN = re.compile(r"\d|[A-Z]{4,}|[A-Z]+\d+|[A-Z]+-[A-Z0-9]+")

    def _has_inline_value(self, line: str) -> bool:
        """
        Devuelve True si la linea (sin ':') parece contener ya un valor
        junto al nombre de campo. Ejemplo: 'Asegurado STEER NUNES JUAN'
        o 'Poliza Anterior AUT-SCR0667473'.

        Heuristica: si alguna de las palabras (exceptuando la primera) parece
        un token de valor (contiene digitos o es todo-mayusculas larga), la
        linea ya tiene el valor embebido.
        """
        words = line.strip().split()
        if len(words) < 2:
            return False
        # Si la primera palabra es todo-minusculas o mixta, y alguna siguiente
        # parece un valor (codigo, nombre propio en mayusculas, numero...)
        for w in words[1:]:
            if self._RE_VALUE_TOKEN.search(w):
                return True
        return False

    def _is_candidate_key(self, line: str) -> bool:
        stripped = line.strip()
        if not stripped:
            return False
        if self._is_structural(stripped):
            return False
        if self._RE_HAS_VALUE.match(stripped):
            return False
        # Los valores tipicos (numericos, simbolicos, emails...) no son claves
        if self._RE_VALUE_LIKE.match(stripped):
            return False
        # La linea debe contener al menos una letra
        if not re.search(r"[a-zA-Z\u00e1\u00e9\u00ed\u00f3\u00fa\u00fc\u00f1\u00c1\u00c9\u00cd\u00d3\u00da\u00dc\u00d1]", stripped):
            return False
        # Si la linea ya tiene un valor embebido (patron clave+valor sin ':')
        # no es una "clave pura" candidata a unirse con la siguiente linea.
        if self._has_inline_value(stripped):
            return False
        words = stripped.split()
        # Las claves de formulario son cortas
        if len(words) > self.MAX_KEY_WORDS:
            return False
        # Todas las palabras deben parecerse a un nombre de campo
        # (solo letras, puntos o guiones). Si alguna contiene un digito
        # o parece un codigo/valor, la linea ya trae el valor embebido.
        if not all(self._RE_KEY_WORD.match(w) for w in words):
            return False
        # CRITERIO DE CAPITALIZACIÓN:
        # Al menos UNA palabra debe empezar por mayúscula y continuar con
        # minúsculas o con un separador (-/.) seguido de minúscula.
        # Ej. válidos: "Zona" (Z+o), "Nro." (N+r), "E-mail" (E+-+m)
        # Ej. inválidos: "NORTE" (N+O), "NIT" (N+I)
        def _is_title(w: str) -> bool:
            if len(w) < 2:
                return False
            if w[0].isupper() and w[1].islower():
                return True
            # Acepta "E-mail", "Nro." → upper + (punct) + lower
            if w[0].isupper() and w[1] in ".-" and len(w) > 2 and w[2].islower():
                return True
            return False

        if not any(_is_title(w) for w in words):
            return False
        return True


    def _extract_key(self, line: str) -> str:
        m = self._RE_KEY_NO_VALUE.match(line.strip())
        if m:
            return m.group(1).strip()
        return line.strip()

    def _next_nonempty(self, lines: list[str], from_idx: int) -> tuple[int, str]:
        """Devuelve (indice, linea) de la proxima linea no-vacia, o (-1, '') si no existe."""
        i = from_idx
        while i < len(lines):
            stripped = lines[i].strip()
            if stripped:
                return i, stripped
            i += 1
        return -1, ""

    def apply(self, text: str) -> str:
        if not text:
            return ""

        raw_lines = text.splitlines()
        n = len(raw_lines)
        output: list[str] = []

        i = 0
        while i < n:
            line = raw_lines[i].strip()

            # ----------------------------------------------------------------
            # Linea vacia -> conservar tal cual
            # ----------------------------------------------------------------
            if not line:
                output.append("")
                i += 1
                continue

            # ----------------------------------------------------------------
            # Linea estructural (encabezado Markdown, separador, vineta...)
            # ----------------------------------------------------------------
            if self._is_structural(line):
                output.append(line)
                i += 1
                continue

            # ----------------------------------------------------------------
            # Linea con clave y valor completo via ':' (ej. "Zona: NORTE")
            # -> Ya está correcta, conservar sin cambios.
            # ----------------------------------------------------------------
            if self._RE_HAS_VALUE.match(line):
                # Caso especial: "Clave: " sin valor (ej. "Celular:")
                # Comprobamos si la siguiente linea no-vacia podria ser su valor
                m = self._RE_KEY_NO_VALUE.match(line)
                if m:
                    key_text = m.group(1).strip()
                    nxt_idx, nxt_line = self._next_nonempty(raw_lines, i + 1)
                    # Si la proxima linea NO es otra clave compuesta (>1 palabra)
                    # ni estructural ni ya tiene valor, la absorbe como valor.
                    # Nota: candidatos de UNA SOLA PALABRA (ej. 'Dolares',
                    # 'Mensual') se absorben como valor igualmente, porque
                    # tras "Moneda:" o "Forma de Pago:" es mas probable que
                    # sean el valor que una nueva clave independiente.
                    nxt_is_multiword_key = (
                        self._is_candidate_key(nxt_line)
                        and len(nxt_line.split()) > 1
                    )
                    if (nxt_idx != -1
                            and not self._is_structural(nxt_line)
                            and not self._RE_HAS_VALUE.match(nxt_line)
                            and not nxt_is_multiword_key):

                        # Recopilar valor (puede ser multi-linea contigua)
                        value_parts: list[str] = [nxt_line]
                        j = nxt_idx + 1
                        while j < n:
                            nl = raw_lines[j].strip()
                            if not nl:
                                break
                            if (self._is_structural(nl)
                                    or self._RE_HAS_VALUE.match(nl)
                                    or self._is_candidate_key(nl)):
                                break
                            value_parts.append(nl)
                            j += 1
                        output.append(f"{key_text}: {' '.join(value_parts)}")
                        i = j
                    else:
                        # La proxima es otra clave o no hay proxima -> clave sola
                        output.append(line)
                        i += 1
                else:
                    output.append(line)
                    i += 1
                continue

            # ----------------------------------------------------------------
            # Candidata a ser una clave sin valor propio
            # ----------------------------------------------------------------
            if self._is_candidate_key(line):
                # Detectar si la linea original termina en ':' (senal explicita de valor)
                line_has_colon = line.strip().endswith(":")
                key_text = self._extract_key(line)  # quita el ':' si lo tiene
                nxt_idx, nxt_line = self._next_nonempty(raw_lines, i + 1)

                def _nxt_is_another_key(nxt_ln: str, nxt_i: int) -> bool:
                    """Devuelve True si nxt_ln debe tratarse como otra clave (no como valor)."""
                    if self._is_structural(nxt_ln):
                        return True
                    if self._RE_HAS_VALUE.match(nxt_ln):
                        return True
                    if self._is_candidate_key(nxt_ln):
                        if len(nxt_ln.split()) > 1:
                            return True  # multi-palabra -> definitivamente otra clave
                        # 1 sola palabra: doble lookahead
                        nxt2_i, nxt2_ln = self._next_nonempty(raw_lines, nxt_i + 1)
                        if nxt2_i == -1:
                            return False  # ultimo elemento -> tratar como valor
                        # Si tras el candidato viene otra clave -> el candidato es clave
                        if self._is_structural(nxt2_ln) or self._is_candidate_key(nxt2_ln):
                            return True
                        return True  # tiene su propio valor -> es otra clave
                    return False

                if nxt_idx == -1:
                    # No hay siguiente linea -> clave sola al final del texto
                    output.append(line)
                    i += 1
                    continue

                nxt_already_has_kv = self._RE_HAS_VALUE.match(nxt_line) is not None
                if (line_has_colon and not nxt_already_has_kv) or not _nxt_is_another_key(nxt_line, nxt_idx):
                    # La clave tiene ':' explicito (y la proxima no tiene su propio kv)
                    # O la proxima linea es un valor sin ambiguedad: absorber.
                    value_parts = [nxt_line]
                    j = nxt_idx + 1
                    while j < n:
                        nl = raw_lines[j].strip()
                        if not nl:
                            break
                        if _nxt_is_another_key(nl, j):
                            break
                        value_parts.append(nl)
                        j += 1
                    output.append(f"{key_text}: {' '.join(value_parts)}")
                    i = j
                else:
                    # La proxima linea no-vacia es otra clave -> esta queda sin valor.
                    #
                    # FALLBACK DE CONSOLIDACION: si la proxima "clave" es de UNA SOLA
                    # PALABRA sin ':' explicito Y a su vez no tiene un valor claro detras,
                    # entonces la situacion es verdaderamente ambigua -> consolidar en
                    # una sola linea. Si la proxima clave tiene su propio valor (ej.
                    # 'Distrito' seguido de 'SANTA CRUZ'), es una clave real -> no consolidar.
                    nxt_is_ambiguous = False
                    if (self._is_candidate_key(nxt_line)
                            and len(nxt_line.split()) == 1
                            and not nxt_line.strip().endswith(":")
                            and not self._RE_HAS_VALUE.match(nxt_line)):
                        # Tercer nivel de lookahead: ver qué sigue tras el candidato
                        nxt2_i, nxt2_ln = self._next_nonempty(raw_lines, nxt_idx + 1)
                        if nxt2_i == -1:
                            # El candidato es el ultimo elemento -> ambiguo
                            nxt_is_ambiguous = True
                        elif self._is_candidate_key(nxt2_ln) or self._is_structural(nxt2_ln):
                            # Tras el candidato viene OTRA clave/estructura:
                            # el candidato NO tiene valor propio -> es ambiguo
                            nxt_is_ambiguous = True
                        # else: el candidato tiene un valor real detras -> es clave legitima

                    if nxt_is_ambiguous:
                        # Consolidamos en una sola linea sin separador artificial
                        output.append(f"{key_text} {nxt_line}")
                        i = nxt_idx + 1
                    else:
                        output.append(line)
                        i += 1
                continue

            # ----------------------------------------------------------------
            # Linea de contenido general (no clasificada)
            # ----------------------------------------------------------------
            output.append(line)
            i += 1

        return "\n".join(output)




