"""
포지션 가중치 재산정 & 코치 판단 대비 일치율 분석 (공개용 재작성본).

질문
  "유전형으로 계산한 능력 점수가, 현장 코치가 포지션별로 필요하다고 본 능력과
   얼마나 같은 방향을 가리키는가?"

이 스크립트가 비교하는 두 가지 결정
  1) 판정 기준: 엄격(가중치 2점 이상만 일치) vs 완화(1점 이상이면 일치)
     - 코치 요구는 O/X 이진값이므로, 데이터의 1점(약한 연관)도 '같은 방향'으로 본다.
  2) 가중치 산정 기준: 포지션끼리 상대비교 vs 전체 모집단 기준(z-score)
     - 상대비교는 포지션 평균끼리만 비교해서, 인원이 적은 포지션의 작은 차이가
       크게 부풀려진다(원본에서 '좌익수 판단력'이 과대평가된 사례).
     - 전체 모집단 기준은 '전체 선수 대비 이 포지션이 정말 높은가'를 본다.
       대표값은 중앙값(이상치에 강함)을 메인, 평균을 검증용으로 함께 산출한다.

주의
  data/sample 은 합성 데이터다. 결과 수치는 원본 프로젝트 수치와 다르며,
  방법을 재현하기 위한 것이다. 임계값(3/2/1점 컷)도 예시값이다.

사용: python analysis/position_weight_calibration.py
"""
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src.normalize_genotype import build_canon_map, normalize_samples, normalize_score_table  # noqa: E402

DATA = ROOT / "data" / "sample"
ATHLETIC = ROOT / "api" / "ref" / "athletic"
OUT = ROOT / "results"

# 상대비교(기존 방식)용 고정 z 임계값 (예시값)
FIXED_Z_CUTS = [(1.0, 3), (0.5, 2), (0.0, 1)]
# 전체기준(신규 방식)용 분포 기반 임계값: 전체 셀 z 분포의 상위 백분위 (예시값)
PCT_CUTS = [(90, 3), (65, 2), (30, 1)]


# ---------- 1. 점수 계산 ----------
def ability_scores(samples, table, max_per_gene):
    """샘플별 능력 점수(0~100). 점수표에 없는 유전형은 0점 + 미매칭으로 집계."""
    lookup = {(r.ability, r.gene, r.genotype): r.score for r in table.itertuples()}
    genes_of = table.groupby("ability").gene.unique().to_dict()
    rows, misses = [], 0
    for s in samples.itertuples(index=False):
        s = s._asdict()
        row = {"sample_id": s["sample_id"], "position": s["position"]}
        for ab, genes in genes_of.items():
            total = 0
            for g in genes:
                v = lookup.get((ab, g, s.get(g)))
                if v is None:
                    misses += 1
                    v = 0
                total += v
            row[ab] = total / (max_per_gene * len(genes)) * 100
        rows.append(row)
    return pd.DataFrame(rows), misses


# ---------- 2. 가중치 산정 ----------
def to_points(z, cuts):
    for c, p in cuts:
        if z >= c:
            return p
    return 0


def weights_relative(scores, abilities):
    """기존: 포지션 평균끼리 비교한 z (포지션 간 상대평가) → 고정 임계값."""
    pos_mean = scores.groupby("position")[abilities].mean()
    z = (pos_mean - pos_mean.mean()) / pos_mean.std(ddof=0)
    return z, z.map(lambda v: to_points(v, FIXED_Z_CUTS))


def weights_population(scores, abilities, center="median"):
    """신규: 전체 선수 분포 대비 포지션 대표값의 z → 분포 기반 임계값."""
    agg = scores.groupby("position")[abilities]
    pos_c = agg.median() if center == "median" else agg.mean()
    pop_c = scores[abilities].median() if center == "median" else scores[abilities].mean()
    z = (pos_c - pop_c) / scores[abilities].std(ddof=0)
    cuts = [(np.percentile(z.values, p), pts) for p, pts in PCT_CUTS]
    return z, z.map(lambda v: to_points(v, cuts))


# ---------- 3. 일치율 ----------
def match_rate(weights, coach, min_w):
    req = coach[coach.required == "O"]
    hits = [weights.loc[r.position, r.ability] >= min_w for r in req.itertuples()]
    return np.mean(hits), int(np.sum(hits)), len(hits)


def main():
    ref = pd.read_csv(DATA / "snp_reference.csv")
    samples_raw = pd.read_csv(DATA / "samples.csv", dtype=str)
    samples_raw = samples_raw[samples_raw.role == "타자"]   # 수비 포지션 분석 대상만
    table_raw = pd.read_csv(ATHLETIC / "ability_gene_scores.csv")
    max_per_gene = json.loads((ATHLETIC / "settings.json").read_text(encoding="utf-8"))["max_score_per_gene"]
    coach = pd.read_csv(DATA / "coach_requirements.csv")
    OUT.mkdir(exist_ok=True)

    canon = build_canon_map(ref)
    samples, _, _ = normalize_samples(samples_raw, canon)
    table, _ = normalize_score_table(table_raw, canon)
    abilities = list(table.ability.unique())

    # 표기 정규화 전후 미매칭 비교 (정규화가 왜 필요한지)
    raw_cols = {c: c.replace("-", "_") for c in samples_raw.columns}
    _, miss_before = ability_scores(samples_raw.rename(columns=raw_cols),
                                    table_raw.assign(gene=table_raw.gene.str.replace("-", "_")), max_per_gene)
    scores, miss_after = ability_scores(samples, table, max_per_gene)
    print(f"[정규화 효과] 점수표 조회 실패: {miss_before}건 → {miss_after}건\n")

    z_rel, w_rel = weights_relative(scores, abilities)
    z_med, w_med = weights_population(scores, abilities, "median")
    z_mean, w_mean = weights_population(scores, abilities, "mean")

    rows = []
    for name, w in [("상대비교 (기존)", w_rel), ("전체기준-중앙값 (메인)", w_med), ("전체기준-평균 (검증)", w_mean)]:
        strict, *_ = match_rate(w, coach, 2)
        relaxed, hit, n = match_rate(w, coach, 1)
        rows.append({"가중치 기준": name, "엄격(≥2점)": f"{strict:.0%}", "완화(≥1점)": f"{relaxed:.0%}", "완화 일치 셀": f"{hit}/{n}"})
    summary = pd.DataFrame(rows)
    print("[코치 필수 능력 대비 방향 일치율]")
    print(summary.to_string(index=False))

    same = (w_med.values == w_mean.values).mean()
    print(f"\n[강건성] 중앙값 vs 평균 가중치 동일 셀 비율: {same:.0%}")

    small = min(scores.position.value_counts().items(), key=lambda kv: kv[1])[0]
    ab = z_rel.loc[small].abs().idxmax()
    print(f"[왜곡 교정 예시] 인원 최소 포지션 '{small}'의 '{ab}': "
          f"상대비교 z {z_rel.loc[small, ab]:+.2f} → 전체기준 z {z_med.loc[small, ab]:+.2f}")

    summary.to_csv(OUT / "match_rate_summary.csv", index=False, encoding="utf-8-sig")
    for name, w in [("relative", w_rel), ("population_median", w_med), ("population_mean", w_mean)]:
        w.to_csv(OUT / f"position_weights_{name}.csv", encoding="utf-8-sig")
    print(f"\n결과 저장 → {OUT.relative_to(ROOT)}/")


if __name__ == "__main__":
    main()
