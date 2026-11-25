"""API 라우트 (엔드포인트)."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException

from app.core.registry import MODELS, get_model
from app.repository.sample_store import get_store, reload_store
from app.schemas.scoring import ByIdRequest, ModelInfo, ScoreResponse
from app.services import recommend_service as rec
from app.services import scoring_service as svc

router = APIRouter()


@router.get("/models", response_model=list[ModelInfo], summary="사용 가능한 모델 목록")
def list_models():
    return [svc.model_info(cfg) for cfg in MODELS.values()]


@router.get("/models/{model_key}", response_model=ModelInfo, summary="모델 상세")
def model_detail(model_key: str):
    cfg = get_model(model_key)
    if not cfg:
        raise HTTPException(404, f"알 수 없는 모델: {model_key}")
    return svc.model_info(cfg)


@router.post("/score/{model_key}/by-id", response_model=ScoreResponse,
             summary="저장된 샘플을 group+sample_id+role 로 조회해 점수 산출")
def score_by_id(model_key: str, req: ByIdRequest):
    cfg = get_model(model_key)
    if not cfg:
        raise HTTPException(404, f"알 수 없는 모델: {model_key}. 가능: {list(MODELS)}")
    result = svc.score_by_id(cfg, req.group, req.sample_id, req.role)
    if not result.get("found"):
        raise HTTPException(404, f"샘플을 찾을 수 없습니다: group={req.group}, sample_id={req.sample_id}, "
                                 f"role={req.role}. data/ 폴더에 해당 group JSON 이 있는지 확인하세요.")
    if result["count"] == 0:
        raise HTTPException(422, f"샘플은 찾았으나 점수 산출에서 제외되었습니다(유전자 부족 등): {result.get('skipped')}")
    return result


@router.post("/recommend/sports/by-id", summary="저장된 샘플에 적합한 운동종목 추천(상위 N)")
def recommend_sports(req: ByIdRequest):
    result = rec.recommend_by_id(req.group, req.sample_id, req.role)
    if not result.get("found"):
        raise HTTPException(404, f"샘플을 찾을 수 없습니다: group={req.group}, sample_id={req.sample_id}, role={req.role}.")
    return result


@router.get("/samples/groups", summary="저장된 group 목록")
def list_groups():
    store = get_store()
    return {"groups": store.groups, "count": store.count()}


@router.post("/admin/reload-refs", summary="ref CSV 수정 후 캐시 갱신")
def reload_refs():
    svc.reload_refs()
    return {"status": "ok", "message": "ref 캐시를 비웠습니다. 다음 요청부터 재로딩됩니다."}


@router.post("/admin/reload-samples", summary="data/ JSON 갱신 후 샘플 재적재")
def reload_samples():
    return {"status": "ok", "count": reload_store()}


@router.post("/admin/reload-sports", summary="종목 요구 프로파일(ref/sports) 수정 후 갱신")
def reload_sports():
    rec.reload_sports_ref()
    return {"status": "ok", "message": "종목 표 캐시를 비웠습니다. 다음 요청부터 재로딩됩니다."}
