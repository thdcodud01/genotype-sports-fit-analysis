"""
표(CSV/XLSX) -> group 별 JSON 변환 스크립트  (처음 1회 + 데이터 갱신 때만 실행)

샘플 유전형 표를 읽어 group 별로 data/<group>.json 파일을 만든다.
서버(API)는 이 JSON 만 읽으므로, 원본 표가 바뀌면 이 스크립트를 다시 돌려
JSON 을 갱신하면 된다. (서버 코드는 건드릴 필요 없음)

기본 입력: 저장소의 data/sample/samples.csv (합성 데이터)

사용 (api/ 폴더에서):
    python scripts/table_to_json.py                  # 기본 입력
    python scripts/table_to_json.py 경로/파일.xlsx    # 다른 파일
"""
from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]                    # api/
DEFAULT_INPUT = ROOT.parent / "data" / "sample" / "samples.csv"
DATA_DIR = ROOT / "data"

# 유전자가 아닌 메타 컬럼 (이 외 컬럼은 전부 genotypes 로 저장)
META_COLUMNS = {"sample_id", "group", "role", "position"}


def read_rows(path: Path) -> list[dict]:
    if path.suffix.lower() == ".csv":
        with open(path, encoding="utf-8-sig", newline="") as f:
            return list(csv.DictReader(f))
    from openpyxl import load_workbook   # xlsx 일 때만 필요
    wb = load_workbook(path, read_only=True, data_only=True)
    rows = wb.active.iter_rows(values_only=True)
    header = [str(h).strip() if h is not None else "" for h in next(rows)]
    out = [dict(zip(header, r)) for r in rows if r and any(v not in (None, "") for v in r)]
    wb.close()
    return out


def to_record(row: dict) -> dict:
    """한 행 -> 샘플 레코드 (genotypes 중첩 구조)."""
    rec = {m: str(row[m]).strip() for m in META_COLUMNS if row.get(m) not in (None, "")}
    rec["genotypes"] = {k.strip(): str(v).strip() for k, v in row.items()
                        if k and k not in META_COLUMNS and v not in (None, "")}
    return rec


def main(args: list[str]):
    files = [Path(a) for a in args] if args else [DEFAULT_INPUT]
    files = [f for f in files if f.exists() and f.suffix.lower() in (".csv", ".xlsx")]
    if not files:
        sys.exit(f"[오류] 변환할 파일이 없습니다. (기본 경로: {DEFAULT_INPUT})")

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    by_group: dict[str, list[dict]] = {}
    for f in files:
        recs = [to_record(r) for r in read_rows(f)]
        for r in recs:
            by_group.setdefault(r.get("group") or f.stem, []).append(r)
        print(f"  읽음: {f.name} -> {len(recs)}건")

    for group, recs in by_group.items():
        out = DATA_DIR / f"{group}.json"
        out.write_text(json.dumps(recs, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"  저장: data/{out.name} ({len(recs)}건)")
    print("완료.")


if __name__ == "__main__":
    main(sys.argv[1:])
