"""서비스 계층 = 오케스트레이션. 라우트와 엔진 사이를 잇는다.
ref 는 한 번 로딩해 캐시한다(요청마다 디스크 재읽기 방지)."""
from __future__ import annotations

from functools import lru_cache
from typing import Any

from app.core import engine
from app.core.registry import ModelConfig, get_model


@lru_cache(maxsize=None)
def load_ref_cached(key: str) -> dict:
    cfg = get_model(key)
    return engine.load_reference(cfg.ref_dir, cfg.scores_filename)


def reload_refs() -> None:
    """ref CSV 를 수정한 뒤 캐시를 비울 때 호출."""
    load_ref_cached.cache_clear()


def model_info(cfg: ModelConfig) -> dict:
    ref = load_ref_cached(cfg.key)
    return {
        "key": cfg.key,
        "title": cfg.title,
        "classify": cfg.classify,
        "groups": ref["group_order"],
        "required_genes": sorted(engine.required_genes(ref)),
    }


def score_by_id(cfg: ModelConfig, group: str, sample_id: str, role: str) -> dict:
    """group+sample_id+role 로 샘플을 찾아 점수(+분류) 산출.
    분류 모델이면 같은 group·role 집단을 기준으로 평균을 계산한다."""
    from app.repository.sample_store import get_store

    store = get_store()
    target = store.get(group, sample_id, role)
    if target is None:
        return {"found": False, "group": group, "sample_id": sample_id, "role": role}

    if cfg.classify:
        cohort = store.get_cohort(group, role)  # 같은 group+role 전체 = 분류 기준 집단
        result = run_scoring(cfg, cohort)
    else:
        result = run_scoring(cfg, [target])

    # 대상 1명만 추려서 반환
    picked = [r for r in result["results"]
              if r.get("sample_id") == sample_id and r.get("group") == group and r.get("role") == role]
    result["results"] = picked
    result["count"] = len(picked)
    result["found"] = True
    return result


def run_scoring(cfg: ModelConfig, samples: list[dict[str, Any]]) -> dict:
    ref = load_ref_cached(cfg.key)
    need = engine.required_genes(ref)

    results: list[dict] = []
    skipped: list[dict] = []
    warnings: list[str] = []

    # 1차: 점수 계산 + 커버리지 점검
    scored = []  # 분류용 (역할/점수)
    for idx, s in enumerate(samples):
        keys = set(s.keys())
        cov = engine.gene_coverage(keys, ref)
        if cov < cfg.min_gene_coverage:
            skipped.append({
                "index": idx,
                "sample_id": s.get("sample_id"),
                "reason": f"유전자 커버리지 {cov:.0%} < {cfg.min_gene_coverage:.0%}",
                "missing_genes": sorted(need - keys),
            })
            continue
        scores = engine.score_player(s, ref)
        rec = {
            "sample_id": s.get("sample_id"),
            "group": s.get("group"),
            "role": s.get(cfg.role_field),
            "position": s.get("position"),
            "type_label": None,
            "scores": {g: round(v, 4) for g, v in scores.items()},
        }
        results.append(rec)
        scored.append({"role": s.get(cfg.role_field), "rec": rec, "scores": scores})

    # 부분 결손 경고
    missing_any = sorted(need - set().union(*[set(s.keys()) for s in samples])) if samples else []
    if missing_any:
        warnings.append("일부/전체 샘플에 없는 유전자(0점 처리): " + ", ".join(missing_any))

    # 2차: 분류 (필요 모델만)
    if cfg.classify and scored:
        means = engine.group_means_by_role(
            [{"role": sp["role"], "scores": sp["scores"]} for sp in scored],
            ref, cfg.role_field,
        )
        for sp in scored:
            sp["rec"]["type_label"] = engine.classify_one(
                sp["scores"], sp["role"], means.get(sp["role"], {}), ref
            )

    return {
        "model": cfg.key,
        "title": cfg.title,
        "classified": cfg.classify,
        "count": len(results),
        "results": results,
        "skipped": skipped,
        "warnings": warnings,
    }
