"""
공개용 합성(가짜) 데이터 생성기.

원본 프로젝트의 데이터는 개인 유전형·사내 모델 계수가 포함되어 공개할 수 없다.
이 스크립트는 '구조만 같은' 가짜 데이터를 만든다.
- 유전자명: G01~G24 (실제 유전자 아님)
- 능력·부위·종목명: 일반 명칭
- 점수표·가중치표·코치 요구표: 무작위 생성값 (실제 모델 계수 아님)
- 샘플: 무작위 생성 (실존 인물 아님)

원본에서 실제로 겪었던 데이터 문제를 일부러 재현한다.
- 이형접합 표기가 기준과 역순인 경우 (예: 기준 AG, 데이터 GA)
- 유전자명 표기 차이 (기준표 G07-2, 데이터 G07_2)

생성 위치
  data/sample/   snp_reference.csv, samples.csv, coach_requirements.csv
  api/ref/       athletic/, injury/, sports/ (점수표·가중치표·설정)

사용: python scripts/make_synthetic_data.py
"""
import json
from pathlib import Path

import numpy as np
import pandas as pd

SEED = 42
ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data" / "sample"
REF = ROOT / "api" / "ref"

N_GENES = 24
ABILITIES = ["파워", "지구력", "순발력", "협응력", "회복력", "판단력"]
TYPE_LABELS = {"파워": "파워형", "지구력": "지구형", "순발력": "스피드형",
               "협응력": "협응형", "회복력": "회복형", "판단력": "판단형"}
BODYPARTS = ["허리", "무릎", "어깨", "햄스트링", "발목"]
FIELD_POSITIONS = ["포수", "1루수", "2루수", "3루수", "유격수", "좌익수", "중견수", "우익수"]
# 포지션별 인원. 좌익수를 일부러 적게 두어 '작은 표본의 상대평가 왜곡'을 재현
POSITION_SIZES = {"포수": 10, "1루수": 9, "2루수": 9, "3루수": 8,
                  "유격수": 8, "좌익수": 3, "중견수": 9, "우익수": 9}
N_PITCHERS = 14
GROUPS = ["team_A", "team_B"]
SPORTS = [("단거리육상", ""), ("마라톤", ""), ("수영", ""), ("사이클", ""),
          ("테니스", ""), ("배드민턴", ""), ("축구", "공격수"), ("축구", "수비수"),
          ("농구", "가드"), ("농구", "센터"), ("배구", "공격수"), ("배구", "리베로")]
ALLELE_PAIRS = [("A", "G"), ("C", "T"), ("A", "T"), ("G", "T"), ("A", "C"), ("I", "D")]
MAX_SCORE = 2   # 유전형별 점수 0/1/2 (가짜 척도)
P_FAV_BOOST = 0.6   # 코치 필수 능력 유전자에서 유리한 대립유전자가 나올 확률 (기본 0.5)


def gname(i):
    return "G07-2" if i == 7 else f"G{i:02d}"   # 기준표는 하이픈 표기


def make_reference(rng):
    """기준 SNP 표: 유전자별 두 대립유전자와 '정본' 이형접합 표기."""
    rows = []
    for i in range(1, N_GENES + 1):
        a1, a2 = ALLELE_PAIRS[rng.integers(len(ALLELE_PAIRS))]
        het = a1 + a2 if rng.random() < 0.5 else a2 + a1   # 정본 순서가 알파벳순이 아닐 수 있음
        rows.append({"gene": gname(i), "allele_1": a1, "allele_2": a2, "het_canonical": het})
    return pd.DataFrame(rows)


def make_score_table(ref, groups, group_col, rng, size=(5, 8)):
    """그룹(능력/부위)-유전자-유전형별 점수표 (가짜 계수)."""
    genes = [g.replace("-", "_") for g in ref["gene"]]
    rows = []
    for grp in groups:
        for g in rng.choice(genes, size=rng.integers(*size), replace=False):
            r = ref[ref["gene"].str.replace("-", "_") == g].iloc[0]
            hi, lo = (r.allele_1, r.allele_2) if rng.random() < 0.5 else (r.allele_2, r.allele_1)
            # 일부 행에 역순 이형접합 표기를 섞음 (원본에서 실제 발생)
            het = r.het_canonical if rng.random() < 0.6 else r.het_canonical[::-1]
            rows += [{group_col: grp, "gene": g, "genotype": hi * 2, "score": 2},
                     {group_col: grp, "gene": g, "genotype": het, "score": 1},
                     {group_col: grp, "gene": g, "genotype": lo * 2, "score": 0}]
    return pd.DataFrame(rows)


def make_coach_requirements(rng):
    """수비 포지션 x 능력 코치 요구표 (O=필수). 포지션당 2~3개."""
    rows = []
    for pos in FIELD_POSITIONS:
        req = set(rng.choice(ABILITIES, size=rng.integers(2, 4), replace=False))
        rows += [{"position": pos, "ability": ab, "required": "O" if ab in req else "X"}
                 for ab in ABILITIES]
    return pd.DataFrame(rows)


def make_samples(ref, ability_tbl, coach, rng):
    """샘플 유전형. 코치 필수 능력의 유전자는 유리한 대립유전자가 약간 더 잘 나오게 함."""
    fav = (ability_tbl[ability_tbl.score == MAX_SCORE]
           .assign(a=lambda d: d.genotype.str[0]).groupby("gene").a.first().to_dict())
    req = coach[coach.required == "O"].groupby("position").ability.apply(set).to_dict()
    genes_of = ability_tbl.groupby("ability").gene.apply(set).to_dict()

    roster = [(pos, "타자") for pos, n in POSITION_SIZES.items() for _ in range(n)]
    roster += [("투수", "투수")] * N_PITCHERS
    rows = []
    for n, (pos, role) in enumerate(roster, 1):
        boosted = set().union(*(genes_of[a] for a in req.get(pos, [])))
        row = {"sample_id": f"S{n:03d}", "group": GROUPS[rng.integers(2)],
               "role": role, "position": pos}
        for r in ref.itertuples():
            g = r.gene.replace("-", "_")
            f = fav.get(g, r.allele_1)
            o = r.allele_2 if f == r.allele_1 else r.allele_1
            p = P_FAV_BOOST if g in boosted else 0.5
            a, b = (f if rng.random() < p else o for _ in range(2))
            if a == b:
                gt = a * 2
            else:   # 데이터 쪽 이형접합 표기도 20% 확률로 역순
                gt = r.het_canonical if rng.random() < 0.8 else r.het_canonical[::-1]
            row[g] = gt   # 데이터는 언더바 표기
        rows.append(row)
    return pd.DataFrame(rows)


def make_sports_tables(rng):
    ab = pd.DataFrame([{"sport": s, "position": p,
                        **{a: int(rng.choice([0, 1, 1, 2, 3])) for a in ABILITIES}} for s, p in SPORTS])
    rk = pd.DataFrame([{"sport": s, "position": p,
                        **{b: int(rng.choice([0, 0, 1, 2, 3])) for b in BODYPARTS}} for s, p in SPORTS])
    return ab, rk


def write_json(path, obj):
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")


def main():
    rng = np.random.default_rng(SEED)
    for d in (DATA, REF / "athletic", REF / "injury", REF / "sports"):
        d.mkdir(parents=True, exist_ok=True)

    ref = make_reference(rng)
    ability_tbl = make_score_table(ref, ABILITIES, "ability", rng)
    injury_tbl = make_score_table(ref, BODYPARTS, "bodypart", rng, size=(3, 6))
    coach = make_coach_requirements(rng)
    samples = make_samples(ref, ability_tbl, coach, rng)
    sport_ab, sport_rk = make_sports_tables(rng)

    ref.to_csv(DATA / "snp_reference.csv", index=False)
    samples.to_csv(DATA / "samples.csv", index=False)
    coach.to_csv(DATA / "coach_requirements.csv", index=False)

    ability_tbl.to_csv(REF / "athletic" / "ability_gene_scores.csv", index=False)
    pd.DataFrame([{"role": r, "ability": a, "type_label": t}
                  for r in ("타자", "투수") for a, t in TYPE_LABELS.items()]
                 ).to_csv(REF / "athletic" / "classification_types.csv", index=False)
    write_json(REF / "athletic" / "settings.json",
               {"max_score_per_gene": MAX_SCORE, "balance_threshold": 20, "top_n": 2})

    injury_tbl.to_csv(REF / "injury" / "injury_gene_scores.csv", index=False)
    write_json(REF / "injury" / "settings.json", {"max_score_per_gene": MAX_SCORE})

    sport_ab.to_csv(REF / "sports" / "sport_ability_weights.csv", index=False)
    sport_rk.to_csv(REF / "sports" / "sport_risk_parts.csv", index=False)
    write_json(REF / "sports" / "settings.json",
               {"injury_penalty_lambda": 0.3, "top_n": 3, "strength_min_weight": 2,
                "caution_min_weight": 1, "caution_min_risk": 60})

    print(f"생성 완료: 샘플 {len(samples)}명(타자 {sum(samples.role == '타자')}, 투수 {sum(samples.role == '투수')}), "
          f"유전자 {len(ref)}개, 종목 블록 {len(SPORTS)}개")


if __name__ == "__main__":
    main()
