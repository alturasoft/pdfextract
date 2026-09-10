"""
Módulo de Evaluación y Métricas de Rendimiento (GriTS, TEDS, TEDS-S, CER, WER).
"""

from app.evaluation.text_metrics import compute_cer, compute_wer
from app.evaluation.grits_evaluator import compute_grits, GriTSResult
from app.evaluation.teds_evaluator import compute_teds, table_to_tree
from app.evaluation.benchmark_runner import (
    BenchmarkRunner,
    BenchmarkReport,
    EngineBenchmarkMetrics,
)

__all__ = [
    "compute_cer",
    "compute_wer",
    "compute_grits",
    "GriTSResult",
    "compute_teds",
    "table_to_tree",
    "BenchmarkRunner",
    "BenchmarkReport",
    "EngineBenchmarkMetrics",
]
