"""
Implementación de TEDS (Tree-Edit-Distance-based Similarity) y TEDS-S (Structure-only).
Representa las tablas como árboles jerárquicos (árbol HTML) y calcula la similitud
normalizada mediante distancia de edición de árboles (Tree Edit Distance).
"""

from dataclasses import dataclass
from typing import Any, Dict, List, Optional
from pdfextract.core.models import Table
from pdfextract.evaluation.text_metrics import compute_cer


@dataclass
class TreeNode:
    tag: str
    text: Optional[str] = None
    rowspan: int = 1
    colspan: int = 1
    children: List["TreeNode"] = None

    def __post_init__(self):
        if self.children is None:
            self.children = []


def table_to_tree(table: Table, ignore_text: bool = False) -> TreeNode:
    """Convierte un objeto Table canónico a un árbol jerárquico tipo DOM/HTML."""
    root = TreeNode(tag="table")

    # Si hay encabezados
    has_headers = table.headers or (table.rows and any(c.is_header for c in table.rows[0]))

    if has_headers:
        thead = TreeNode(tag="thead")
        tr = TreeNode(tag="tr")
        if table.headers:
            for h in table.headers:
                txt = None if ignore_text else h.strip()
                tr.children.append(TreeNode(tag="th", text=txt))
        elif table.rows:
            for c in table.rows[0]:
                txt = None if ignore_text else c.text.strip()
                tr.children.append(TreeNode(tag="th", text=txt, rowspan=c.row_span, colspan=c.col_span))
        thead.children.append(tr)
        root.children.append(thead)

    tbody = TreeNode(tag="tbody")
    start_row = 1 if (has_headers and not table.headers and table.rows) else 0

    for row in table.rows[start_row:]:
        tr = TreeNode(tag="tr")
        for cell in row:
            txt = None if ignore_text else cell.text.strip()
            tr.children.append(
                TreeNode(
                    tag="td",
                    text=txt,
                    rowspan=cell.row_span,
                    colspan=cell.col_span,
                )
            )
        tbody.children.append(tr)

    root.children.append(tbody)
    return root


def _tree_size(node: TreeNode) -> int:
    """Calcula el número total de nodos en el subárbol."""
    count = 1
    for child in node.children:
        count += _tree_size(child)
    return count


def _node_distance(n1: TreeNode, n2: TreeNode, ignore_text: bool = False) -> float:
    """Calcula el costo de sustitución entre dos nodos."""
    if n1.tag != n2.tag:
        return 1.0

    if n1.rowspan != n2.rowspan or n1.colspan != n2.colspan:
        return 0.5

    if ignore_text or (n1.text is None and n2.text is None):
        return 0.0

    t1 = n1.text or ""
    t2 = n2.text or ""
    if t1 == t2:
        return 0.0

    # Distancia normalizada de texto (CER)
    cer = compute_cer(t1, t2)
    return min(1.0, cer)


def _tree_edit_distance(root1: Optional[TreeNode], root2: Optional[TreeNode], ignore_text: bool = False) -> float:
    """
    Calcula la distancia de edición entre dos árboles jerárquicos
    mediante aproximación multinivel por niveles de tabla (table -> thead/tbody -> tr -> th/td).
    """
    if root1 is None and root2 is None:
        return 0.0
    if root1 is None:
        assert root2 is not None
        return float(_tree_size(root2))
    if root2 is None:
        return float(_tree_size(root1))

    base_cost = _node_distance(root1, root2, ignore_text)

    # Distancia de edición entre listas de hijos (secuencia de filas o celdas)
    children1 = root1.children
    children2 = root2.children
    len1 = len(children1)
    len2 = len(children2)

    # DP para emparejar hijos de manera óptima
    dp = [[0.0] * (len2 + 1) for _ in range(len1 + 1)]

    for i in range(1, len1 + 1):
        dp[i][0] = dp[i - 1][0] + _tree_size(children1[i - 1])
    for j in range(1, len2 + 1):
        dp[0][j] = dp[0][j - 1] + _tree_size(children2[j - 1])

    for i in range(1, len1 + 1):
        for j in range(1, len2 + 1):
            sub_cost = _tree_edit_distance(children1[i - 1], children2[j - 1], ignore_text)
            del_cost = dp[i - 1][j] + _tree_size(children1[i - 1])
            ins_cost = dp[i][j - 1] + _tree_size(children2[j - 1])
            dp[i][j] = min(dp[i - 1][j - 1] + sub_cost, del_cost, ins_cost)

    return base_cost + dp[len1][len2]


def compute_teds(ground_truth: Table, prediction: Table, ignore_text: bool = False) -> float:
    """
    Calcula TEDS (o TEDS-S si ignore_text=True) entre Ground Truth y Predicción.
    TEDS = 1 - (TreeEditDistance / max(size(GT), size(Pred)))
    """
    tree_gt = table_to_tree(ground_truth, ignore_text=ignore_text)
    tree_pred = table_to_tree(prediction, ignore_text=ignore_text)

    size_gt = _tree_size(tree_gt)
    size_pred = _tree_size(tree_pred)
    max_size = max(size_gt, size_pred)

    if max_size == 0:
        return 1.0

    edit_dist = _tree_edit_distance(tree_gt, tree_pred, ignore_text=ignore_text)
    similarity = 1.0 - (edit_dist / max_size)
    return round(max(0.0, min(1.0, similarity)), 4)
