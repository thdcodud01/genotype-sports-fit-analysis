# api/: 점수 산출·종목 추천 API (FastAPI)

원본 프로젝트의 API 구조를 유지하고, 식별자·경로·수치만 일반화한 공개용 재구성본입니다.

```
app/core/engine.py        공용 점수 엔진 (운동능력·부상 모델이 같이 사용)
app/core/registry.py      모델 등록부 (새 모델 = 설정 한 줄 + ref 폴더 하나)
app/repository/           샘플 저장소 (JSON 파일 기반, DB로 교체 시 이 파일만 변경)
app/services/             점수 산출·유형 분류·종목 추천 로직
app/api/routes.py         엔드포인트
ref/                      점수표·가중치표·설정 (합성값)
scripts/table_to_json.py  샘플 표 → group별 JSON 변환
```

## 실행 (저장소 루트 기준)
```bash
pip install -r requirements.txt
python src/normalize_genotype.py --apply   # 표기 정규화 (점수표·샘플 동시)
cd api
python scripts/table_to_json.py            # data/<group>.json 생성
uvicorn main:app --reload                  # http://127.0.0.1:8000/docs
```

## 주요 엔드포인트
| 메서드 | 경로 | 설명 |
|---|---|---|
| GET | `/models` | 모델 목록과 필요 유전자 |
| POST | `/score/{athletic\|injury}/by-id` | group + sample_id + role 로 점수(+유형) 산출 |
| POST | `/recommend/sports/by-id` | 종목·포지션 추천 상위 N개와 이유 |
| POST | `/admin/reload-*` | ref·샘플·종목표 수정 후 재적재 |

요청 예시: `{"group": "team_A", "sample_id": "S001", "role": "타자"}`
