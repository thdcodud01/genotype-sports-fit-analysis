"""
유전형 기반 운동능력·부상위험 점수 산출 API (FastAPI, 공개용 재구성본).

실행 (저장소 루트의 api/ 폴더에서):
    uvicorn main:app --reload
문서(자동 생성):
    http://127.0.0.1:8000/docs
"""
from fastapi import FastAPI

from app.api.routes import router

app = FastAPI(
    title="Genotype Sports-Fit Scoring API",
    description="유전형 기반 운동능력 / 부상위험 점수 산출, 유형 분류, 종목 추천 API (합성 데이터 시연용)",
    version="1.0.0",
)

app.include_router(router)


@app.get("/", summary="헬스체크")
def root():
    return {"status": "ok", "docs": "/docs"}
