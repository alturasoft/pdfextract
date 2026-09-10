"""
Implementación de GriTS (Grid Table Similarity).
Evalúa la fidelidad estructural y de contenido en tablas 2D
mediante grafos de adyacencia horizontal y vertical de celdas.
"""

from dataclasses import dataclass
from typing import Dict, List, Set, Tuple
from pdfextract.core.models import Table
from pdfextract.evaluation.text_metrics import compute_cer


@dataclass
class GriTSResult:
    grits_top: float   # Similitud topológica (F1 de adyacencias 2D)
    grits_cont: float  # Similitud de contenido en celdas alineadas
    grits_overall: float  # Puntuación combinada GriTS
    precision_top: float
    recall_top: float


def _extract_adjacencies(table: Table) -> Tuple[Set[Tuple[str, str, str]], Dict[Tuple[int, int], str]]:
    """
    Extrae relaciones de adyacencia horizontal ('H') y vertical ('V')
    entre celdas no vacías de la tabla.
    """
    adjacencies: Set[Tuple[str, str, str]] = set()
    cell_map: Dict[Tuple[int, int], str] = {}

    for r_idx, row in enumerate(table.rows):
        for c_idx, cell in enumerate(row):
            txt = " ".join(cell.text.lower().split()) if cell.text else ""
            cell_map[(r_idx, c_idx)] = txt

    num_rows = table.num_rows
    num_cols = table.num_cols

    for r in range(num_rows):
        for c in range(num_cols):
            curr_txt = cell_map.get((r, c), "")
            # Adyacencia horizontal derecha
            if c + 1 < num_cols:
                right_txt = cell_map.get((r, c + 1), "")
                if curr_txt or right_txt:
                    adjacencies.add((curr_txt, right_txt, "H"))
            # Adyacencia vertical inferior
            if r + 1 < num_rows:
                down_txt = cell_map.get((r + 1, c), "")
                if curr_txt or down_txt:
                    adjacencies.add((curr_txt, down_txt, "V"))

    return adjacencies, cell_map


def compute_grits(ground_truth: Table, prediction: Table) -> GriTSResult:
    """
    Calcula GriTS entre la tabla Ground Truth y la Predicción.
    """
    if ground_truth.num_rows == 0 or ground_truth.num_cols == 0:
        if prediction.num_rows == 0 or prediction.num_cols == 0:
            return GriTSResult(1.0, 1.0, 1.0, 1.0, 1.0)
        return GriTSResult(0.0, 0.0, 0.0, 0.0, 0.0)

    gt_adj, gt_cells = _extract_adjacencies(ground_truth)
    pred_adj, pred_cells = _extract_adjacencies(prediction)

    # 1. Topología: F1 de adyacencias
    if not gt_adj and not pred_adj:
        prec_top = 1.0
        rec_top = 1.0
        f1_top = 1.0
    elif not gt_adj or not pred_adj:
        prec_top = 0.0
        rec_top = 0.0
        f1_top = 0.0
    else:
        # Coincidencias exactas o casi exactas de adyacencias
        common_adj = gt_adj.intersection(pred_adj)
        prec_top = len(common_adj) / len(pred_adj) if pred_adj else 0.0
        rec_top = len(common_adj) / len(gt_adj) if gt_adj else 0.0
        f1_top = (2 * prec_top * rec_top / (prec_top + rec_top)) if (prec_top + rec_top) > 0 else 0.0

    # 2. Contenido: Similitud textual en posiciones coincidentes normalizadas
    max_r = max(ground_truth.num_rows, prediction.num_rows)
    max_c = max(ground_truth.num_cols, prediction.num_cols)

    content_sims: List[float] = []
    for r in range(min(ground_truth.num_rows, prediction.num_rows)):
        for c in range(min(ground_truth.num_cols, prediction.num_cols)):
            t_gt = gt_cells.get((r, c), "")
            t_pred = pred_cells.get((r, c), "")
            if not t_gt and not t_pred:
                content_sims.append(1.0)
            else:
                cer = compute_cer(t_gt, t_pred)
                content_sims.append(max(0.0, 1.0 - cer))

    # Penalizar celdas faltantes o sobrantes
    matched_cells = len(content_sims)
    total_expected_cells = max_r * max_c
    avg_content_sim = (sum(content_sims) / total_expected_cells) if total_expected_cells > 0 else 1.0

    overall = 0.6 * f1_top + 0.4 * avg_content_sim

    return GriTSResult(
        grits_top=round(f1_top, 4),
        grits_cont=round(avg_content_sim, 4),
        grits_overall=round(overall, 4),
        precision_top=round(prec_top, 4),
        recall_top=round(rec_top, 4),
    )
