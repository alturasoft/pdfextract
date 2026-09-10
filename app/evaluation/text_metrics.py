"""
Métricas de evaluación de texto a nivel de caracteres (CER) y palabras (WER).
Implementación pura basada en programación dinámica (distancia de Levenshtein).
"""

from typing import List, Sequence


def _levenshtein_distance(seq1: Sequence, seq2: Sequence) -> int:
    """Calcula la distancia de Levenshtein mínima de inserción, eliminación y sustitución."""
    n = len(seq1)
    m = len(seq2)

    if n == 0:
        return m
    if m == 0:
        return n

    # Vector de dos filas para optimización de memoria
    prev = list(range(m + 1))
    curr = [0] * (m + 1)

    for i in range(1, n + 1):
        curr[0] = i
        for j in range(1, m + 1):
            cost = 0 if seq1[i - 1] == seq2[j - 1] else 1
            curr[j] = min(
                prev[j] + 1,      # Eliminación
                curr[j - 1] + 1,  # Inserción
                prev[j - 1] + cost  # Sustitución
            )
        prev = curr[:]

    return prev[m]


def compute_cer(reference: str, hypothesis: str) -> float:
    """
    Calcula el Character Error Rate (CER) normalizado.
    CER = Levenshtein(ref_chars, hyp_chars) / len(ref_chars)
    """
    ref = reference.strip()
    hyp = hypothesis.strip()

    if not ref and not hyp:
        return 0.0
    if not ref:
        return 1.0

    dist = _levenshtein_distance(list(ref), list(hyp))
    return min(1.0, dist / len(ref))


def compute_wer(reference: str, hypothesis: str) -> float:
    """
    Calcula el Word Error Rate (WER) normalizado.
    WER = Levenshtein(ref_words, hyp_words) / len(ref_words)
    """
    ref_words = reference.strip().split()
    hyp_words = hypothesis.strip().split()

    if not ref_words and not hyp_words:
        return 0.0
    if not ref_words:
        return 1.0

    dist = _levenshtein_distance(ref_words, hyp_words)
    return min(1.0, dist / len(ref_words))
