"""
유전형 표기 검사·정규화 스크립트 (공개용 재작성본).

배경
- 점수 계산은 '유전형 문자열'로 점수표를 조회한다. 같은 이형접합이라도
  'AG'와 'GA'처럼 순서가 다르면 조회에 실패하고, 오류 없이 0점 처리된다.
- 원본 프로젝트에서는 기준 SNP 표와 대조한 결과, 대상 유전자 상당수에서
  점수표·데이터의 표기가 기준과 어긋나 있었다. 일부는 양쪽이 같은 방향으로
  틀려 우연히 맞아 떨어지고 있었기 때문에 겉으로 드러나지 않았다.

원칙
- 기준 SNP 표(data/sample/snp_reference.csv)를 유일한 정본으로 삼는다.
- 점수표(api/ref 의 운동능력·부상 2종)와 샘플 데이터를 '동시에' 정본 표기로 맞춘다.
- 기본은 검사만(dry-run). --apply 를 줄 때만 파일을 고친다.
- 여러 번 실행해도 결과가 같다(멱등). 두 번째 실행은 '변경 대상 없음'.

사용
    python src/normalize_genotype.py            # 검사 리포트만
    python src/normalize_genotype.py --apply    # 실제 반영
"""
import argparse
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data" / "sample"
SCORE_TABLES = [ROOT / "api" / "ref" / "athletic" / "ability_gene_scores.csv",
                ROOT / "api" / "ref" / "injury" / "injury_gene_scores.csv"]
META_COLS = {"sample_id", "group", "role", "position"}


def canon_gene(name: str) -> str:
    """유전자명 표기 통일: 하이픈/언더바 차이를 흡수 (예: G07-2 == G07_2)."""
    return str(name).strip().replace("-", "_")


def build_canon_map(ref: pd.DataFrame) -> dict:
    """유전자별 {허용 표기 -> 정본 표기} 매핑. 동형접합은 그대로, 이형접합은 정본 순서로."""
    m = {}
    for r in ref.itertuples():
        a1, a2, het = r.allele_1, r.allele_2, r.het_canonical
        m[canon_gene(r.gene)] = {a1 * 2: a1 * 2, a2 * 2: a2 * 2, het: het, het[::-1]: het}
    return m


def check_series(gene, values, canon_map):
    """한 유전자 열을 검사해 (고칠 것, 알 수 없는 표기) 반환."""
    allowed = canon_map.get(gene)
    if allowed is None:
        return {}, {}
    fixes, unknown = {}, {}
    for v, cnt in values.value_counts(dropna=True).items():
        v = str(v).strip().upper()
        if v not in allowed:
            unknown[v] = int(cnt)
        elif allowed[v] != v:
            fixes[v] = (allowed[v], int(cnt))
    return fixes, unknown


def normalize_samples(samples, canon_map):
    samples = samples.rename(columns={c: canon_gene(c) for c in samples.columns if c not in META_COLS})
    report, not_in_ref = [], []
    for col in samples.columns:
        if col in META_COLS:
            continue
        if col not in canon_map:
            not_in_ref.append(col)
            continue
        fixes, unknown = check_series(col, samples[col], canon_map)
        for old, (new, cnt) in fixes.items():
            report.append(("samples", col, old, new, cnt))
        for v, cnt in unknown.items():
            report.append(("samples", col, v, "?? 기준에 없는 표기", cnt))
        samples[col] = samples[col].map(lambda v: canon_map[col].get(str(v).strip().upper(), v))
    return samples, report, not_in_ref


def normalize_score_table(table, canon_map, source="score_table"):
    table = table.copy()
    table["gene"] = table["gene"].map(canon_gene)
    report = []
    for gene, sub in table.groupby("gene"):
        fixes, unknown = check_series(gene, sub["genotype"], canon_map)
        for old, (new, cnt) in fixes.items():
            report.append((source, gene, old, new, cnt))
        for v, cnt in unknown.items():
            report.append((source, gene, v, "?? 기준에 없는 표기", cnt))
    table["genotype"] = [canon_map.get(g, {}).get(str(v).strip().upper(), v)
                         for g, v in zip(table.gene, table.genotype)]
    return table, report


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--data-dir", type=Path, default=DATA)
    ap.add_argument("--apply", action="store_true", help="검사 결과를 파일에 반영")
    args = ap.parse_args()

    d = args.data_dir
    ref = pd.read_csv(d / "snp_reference.csv")
    samples = pd.read_csv(d / "samples.csv", dtype=str)
    canon_map = build_canon_map(ref)

    samples_n, rep_s, not_in_ref = normalize_samples(samples, canon_map)
    tables_n, rep_t = {}, []
    for path in SCORE_TABLES:
        tbl, rep = normalize_score_table(pd.read_csv(path), canon_map, source=path.parent.name)
        tables_n[path] = tbl
        rep_t += rep
    report = pd.DataFrame(rep_t + rep_s, columns=["source", "gene", "found", "canonical", "count"])

    renamed = [c for c in samples.columns if c not in META_COLS and canon_gene(c) != c]
    if report.empty and not renamed:
        print("변경 대상 없음. 모든 표기가 기준과 일치합니다.")
        return

    if renamed:
        print(f"유전자명 표기 통일: {renamed}")
    if not report.empty:
        genes = report.gene.nunique()
        print(f"표기 불일치 유전자 {genes}개 / 기준 {len(canon_map)}개")
        print(report.sort_values(["gene", "source"]).to_string(index=False))
    if not_in_ref:
        print(f"\n[참고] 기준표에 없어 검사하지 않은 열: {not_in_ref}")

    if args.apply:
        if (report["canonical"].str.startswith("??")).any():
            print("\n기준에 없는 표기가 있어 반영을 중단합니다. 원본 확인이 필요합니다.")
            return
        samples_n.to_csv(d / "samples.csv", index=False)
        for path, tbl in tables_n.items():
            tbl.to_csv(path, index=False)
        print("\n반영 완료. 다시 실행하면 '변경 대상 없음'이 나와야 합니다.")
    else:
        print("\n(검사만 수행. 반영하려면 --apply)")


if __name__ == "__main__":
    main()
