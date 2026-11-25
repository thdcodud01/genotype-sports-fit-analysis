"""
부상위험 감산 계수 λ 민감도 분석 (공개용 재구성본).

질문
  종목 추천 점수 = 적합도 × (1 − λ × 부상위험/100)
  "부상위험을 얼마나 강하게 반영(λ)하면, 기존 추천 결과가 얼마나 흔들리는가?"

지표 (λ=0, 즉 감산 전 적합도 순위 대비)
  - 1순위 변동률: 추천 1순위가 바뀐 샘플 비율
  - 평균 순위 변동: 종목별 순위가 평균 몇 계단 움직였는지
  - 기존 1순위 TOP3 이탈률: 감산 전 1순위였던 종목이 TOP3 밖으로 밀린 비율

원본과 다른 점
  - 원본은 야구 포지션 블록만 대상으로 했다. 공개본은 전체 (종목, 포지션) 블록 대상.
  - 결과는 엑셀 서식 파일 대신 CSV로 저장한다.
  - 합성 데이터 기준이라 수치는 원본과 다르다.

사용 (저장소 루트에서, 사전에 api/scripts/table_to_json.py 실행 필요)
  python analysis/lambda_sweep.py
"""
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "api"))
from app.repository.sample_store import get_store  # noqa: E402
from app.services.recommend_service import profile, rank_sports  # noqa: E402

LAMBDAS = [0.1, 0.2, 0.3, 0.4, 0.5]
OUT = ROOT / "results"


def ranks(ranked):
    return {r["name"]: i + 1 for i, r in enumerate(ranked)}


def main():
    samples = get_store().all()
    if not samples:
        sys.exit("샘플이 없습니다. 먼저 api/ 폴더에서 python scripts/table_to_json.py 를 실행하세요.")

    profiles = [profile(s) for s in samples]
    base = [ranks(rank_sports(ath, inj, lam=0.0)) for ath, inj in profiles]
    base_top = [min(b, key=b.get) for b in base]
    n = len(samples)

    rows = []
    for lam in LAMBDAS:
        changed = top3_out = 0
        shift = 0.0
        for (ath, inj), b, bt in zip(profiles, base, base_top):
            a = ranks(rank_sports(ath, inj, lam=lam))
            changed += min(a, key=a.get) != bt
            top3_out += a[bt] > 3
            shift += sum(abs(b[k] - a[k]) for k in a) / len(a)
        rows.append({"lambda": lam,
                     "1순위 변동률(%)": round(changed / n * 100, 1),
                     "평균 순위변동(계단)": round(shift / n, 2),
                     "기존1순위 TOP3 이탈률(%)": round(top3_out / n * 100, 1)})

    df = pd.DataFrame(rows)
    print(f"샘플 {n}명 | 감산 전(λ=0) 순위 대비\n")
    print(df.to_string(index=False))
    OUT.mkdir(exist_ok=True)
    df.to_csv(OUT / "lambda_sensitivity.csv", index=False, encoding="utf-8-sig")
    print(f"\n결과 저장 → results/lambda_sensitivity.csv")


if __name__ == "__main__":
    main()
