"""API 요청/응답 스키마 (pydantic)."""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class ByIdRequest(BaseModel):
    """저장된 샘플을 식별자로 조회해 점수를 낸다."""
    group: str = Field(..., examples=["team_A"])
    sample_id: str = Field(..., examples=["S001"])
    role: str = Field(..., examples=["타자"])


class SampleResult(BaseModel):
    sample_id: str | None = None
    group: str | None = None
    role: str | None = None
    position: str | None = None
    type_label: str | None = Field(None, description="분류 모델일 때만 채워짐")
    scores: dict[str, float] = Field(..., description="그룹(능력/부위)별 100점 환산 점수")


class ScoreResponse(BaseModel):
    model: str
    title: str
    classified: bool
    count: int
    results: list[SampleResult]
    skipped: list[dict[str, Any]] = Field(
        default_factory=list, description="유전자 부족 등으로 건너뛴 샘플"
    )
    warnings: list[str] = Field(default_factory=list)


class ModelInfo(BaseModel):
    key: str
    title: str
    classify: bool
    groups: list[str] = Field(..., description="점수 그룹(능력/부위) 목록")
    required_genes: list[str]
