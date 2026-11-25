"""
공용 점수 엔진

운동능력/부상 두 모델이 모두 이 엔진을 씀. 모델별 차이(어느 ref 폴더,
분류 여부, 출력 라벨 등)는 registry.py 의 ModelConfig 로만 표현됨

ref 폴더 규약:
  <model>_gene_scores.csv : group, gene, genotype, score
      - group 컬럼명은 모델마다 다를 수 있음(ability / bodypart). 첫 컬럼을 그룹으로 사용.
  classification_types.csv (선택) : role, group, type_label
  settings.json : max_score_per_gene, score_suffix, (선택) balance_threshold, top_n, min_gene_coverage
"""
from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any


# ----------------------------------------------------------------------
# 기준 정보 로딩
# ----------------------------------------------------------------------
def load_reference(ref_dir: Path, scores_filename: str) -> dict:
    ref_dir = Path(ref_dir)

    # 점수표: group, gene, genotype, score  (group 컬럼명은 자유: 첫 컬럼)
    group_order: list[str] = []
    score_map: dict[str, dict[str, dict[str, float]]] = {}
    group_genes: dict[str, list[str]] = {}

    with open(ref_dir / scores_filename, encoding="utf-8-sig", newline="") as f:
        reader = csv.reader(f)
        header = next(reader)
        # 컬럼 인덱스: 0=group, 그리고 gene/genotype/score 이름으로 탐색
        gene_i = header.index("gene")
        gt_i = header.index("genotype")
        sc_i = header.index("score")
        group_i = 0  # 첫 컬럼이 그룹(ability/bodypart)
        for raw in reader:
            if not raw or all(c.strip() == "" for c in raw):
                continue
            group = raw[group_i].strip()
            gene = raw[gene_i].strip()
            genotype = raw[gt_i].strip()
            score = float(raw[sc_i])
            if group not in score_map:
                score_map[group] = {}
                group_genes[group] = []
                group_order.append(group)
            if gene not in score_map[group]:
                score_map[group][gene] = {}
                group_genes[group].append(gene)
            score_map[group][gene][genotype] = score

    # 분류 라벨(선택)
    type_map: dict[str, dict[str, str]] = {}
    ct_path = ref_dir / "classification_types.csv"
    if ct_path.exists():
        with open(ct_path, encoding="utf-8-sig", newline="") as f:
            for row in csv.DictReader(f):
                role = (row.get("role") or "").strip()
                group = (row.get("group") or row.get("ability") or row.get("bodypart") or "").strip()
                label = (row.get("type_label") or "").strip()
                if role and group and label:
                    type_map.setdefault(role, {})[group] = label

    with open(ref_dir / "settings.json", encoding="utf-8") as f:
        settings = json.load(f)

    return {
        "group_order": group_order,
        "score_map": score_map,
        "group_genes": group_genes,
        "type_map": type_map,
        "settings": settings,
    }


def required_genes(ref: dict) -> set[str]:
    return {g for genes in ref["group_genes"].values() for g in genes}


def gene_coverage(player_keys: set[str], ref: dict) -> float:
    need = required_genes(ref)
    if not need:
        return 1.0
    return sum(1 for g in need if g in player_keys) / len(need)


# ----------------------------------------------------------------------
# 점수 계산
# ----------------------------------------------------------------------
def score_player(player: dict[str, Any], ref: dict) -> dict[str, float]:
    """한 선수의 그룹별 100점 환산 점수 dict 반환 (group -> score)."""
    max_per_gene = float(ref["settings"]["max_score_per_gene"])
    out: dict[str, float] = {}
    for group in ref["group_order"]:
        gmap = ref["score_map"][group]
        genes = ref["group_genes"][group]
        raw = 0.0
        for gene in genes:
            val = player.get(gene)
            if val is None:
                continue
            raw += gmap[gene].get(str(val).strip(), 0)
        denom = len(genes) * max_per_gene
        out[group] = (raw / denom * 100) if denom else 0.0
    return out


# ----------------------------------------------------------------------
# 선수유형 분류
# ----------------------------------------------------------------------
def _top_n(scores: dict[str, float], order: list[str], n: int) -> list[tuple[str, float]]:
    """pandas nlargest(keep='first') 와 동일: 점수 내림차순, 동점은 원래 순서."""
    indexed = [(group, scores[group], i) for i, group in enumerate(order)]
    indexed.sort(key=lambda t: (-t[1], t[2]))
    return [(g, s) for g, s, _ in indexed[:n]]


def classify_one(scores: dict[str, float], role: str, group_means: dict[str, float],
                 ref: dict) -> str:
    type_lookup = ref["type_map"].get(role, {})
    settings = ref["settings"]
    threshold = float(settings.get("balance_threshold", 20))
    top_n = int(settings.get("top_n", 2))
    order = ref["group_order"]

    top = _top_n(scores, order, top_n)
    top1, top1_score = top[0]
    values = list(scores.values())
    bottom_score = min(values)
    avg = sum(values) / len(values)

    types: list[str] = []
    if top1_score - bottom_score <= threshold:
        t1 = type_lookup.get(top1)
        if t1:
            types.append(f"밸런스형(평균_{avg:.1f})")
            types.append(f"{t1}({top1_score:.1f})")
    else:
        t1 = type_lookup.get(top1)
        if t1:
            types.append(f"{t1}({top1_score:.1f})")
        if len(top) > 1:
            top2, top2_score = top[1]
            if top2_score > group_means.get(top2, float("inf")):
                t2 = type_lookup.get(top2)
                if t2:
                    types.append(f"{t2}({top2_score:.1f})")

    return ", ".join(sorted(set(types))) if types else "미분류"


def group_means_by_role(scored_players: list[dict], ref: dict, role_field: str
                        ) -> dict[str, dict[str, float]]:
    """역할별 그룹 평균. scored_players: [{'role':..., 'scores':{group:score}}]."""
    order = ref["group_order"]
    acc: dict[str, dict[str, list[float]]] = {}
    for sp in scored_players:
        role = sp["role"]
        acc.setdefault(role, {g: [] for g in order})
        for g in order:
            acc[role][g].append(sp["scores"][g])
    means: dict[str, dict[str, float]] = {}
    for role, gd in acc.items():
        means[role] = {g: (sum(v) / len(v) if v else 0.0) for g, v in gd.items()}
    return means
