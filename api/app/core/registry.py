"""
모델 레지스트리. 새 모델 추가 = 여기에 ModelConfig 한 줄 + ref 폴더 하나.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

# api/ 루트
ROOT = Path(__file__).resolve().parents[2]
REF_ROOT = ROOT / "ref"


@dataclass(frozen=True)
class ModelConfig:
    key: str                      # API 경로용 키 (athletic / injury)
    title: str                    # 사람이 읽는 이름
    ref_dir: Path                 # 기준 폴더
    scores_filename: str          # 점수표 CSV 파일명
    classify: bool                # 유형 분류 수행 여부
    role_field: str = "role"      # 분류 시 역할 구분 컬럼
    min_gene_coverage: float = 0.0  # 이 비율 미만이면 처리 거부(0이면 항상 처리)


MODELS: dict[str, ModelConfig] = {
    "athletic": ModelConfig(
        key="athletic",
        title="운동능력",
        ref_dir=REF_ROOT / "athletic",
        scores_filename="ability_gene_scores.csv",
        classify=True,
        min_gene_coverage=0.0,
    ),
    "injury": ModelConfig(
        key="injury",
        title="부상위험",
        ref_dir=REF_ROOT / "injury",
        scores_filename="injury_gene_scores.csv",
        classify=False,
        min_gene_coverage=0.5,   # 예시값
    ),
}


def get_model(key: str) -> ModelConfig | None:
    return MODELS.get(key)
