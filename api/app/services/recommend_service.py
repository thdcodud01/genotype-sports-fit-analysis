"""
운동종목 추천 서비스.

샘플의 운동능력 점수 + 부상위험 점수를 종목(·포지션) 요구 프로파일과 매칭해
적합한 종목 상위 N개를 이유와 함께 추천한다.

적합도 계산:
  fit       = Σ(능력 가중치 × 능력 점수) / Σ(능력 가중치)        # 0~100, 높을수록 적합
  injury    = Σ(부위 위험 가중치 × 부상 점수) / Σ(부위 위험 가중치) # 0~100, 높을수록 위험
  score     = fit × (1 − λ × injury/100)                          # 부상 위험만큼 감점

종목 참조표는 (sport, position) 2열 키 구조다. position 이 비어 있으면
포지션 구분이 없는 종목이다. 종목·포지션 추가 = CSV 행 추가 (코드 변경 없음).
"""
from __future__ import annotations

import csv
import json
from functools import lru_cache
from pathlib import Path

from app.core import engine
from app.repository.sample_store import get_store
from app.services.scoring_service import load_ref_cached

ROOT = Path(__file__).resolve().parents[2]
SPORTS_REF = ROOT / "ref" / "sports"


def _read_wide_csv(path: Path) -> tuple[list[tuple[str, str]], dict[tuple[str, str], dict[str, float]]]:
    """wide CSV(sport, position, 축...) -> ([(종목, 포지션)], {(종목, 포지션): {축: 값}})."""
    with open(path, encoding="utf-8-sig", newline="") as f:
        reader = csv.reader(f)
        header = next(reader)
        if header[1].strip().lower() != "position":
            raise ValueError(f"{path.name}: 두 번째 컬럼은 'position' 이어야 합니다.")
        axes = [h.strip() for h in header[2:]]
        order, table = [], {}
        for row in reader:
            if not row or row[0].strip() == "":
                continue
            key = (row[0].strip(), row[1].strip())
            order.append(key)
            table[key] = {ax: float(row[i + 2] or 0) for i, ax in enumerate(axes)}
        return order, table


def label(key: tuple[str, str]) -> str:
    """표시용 이름. 포지션이 있으면 '종목(포지션)'."""
    sport, position = key
    return f"{sport}({position})" if position else sport


@lru_cache(maxsize=1)
def load_sports_ref() -> dict:
    sports, ability_w = _read_wide_csv(SPORTS_REF / "sport_ability_weights.csv")
    _, risk_w = _read_wide_csv(SPORTS_REF / "sport_risk_parts.csv")
    settings = json.loads((SPORTS_REF / "settings.json").read_text(encoding="utf-8"))
    return {"sports": sports, "ability_w": ability_w, "risk_w": risk_w, "settings": settings}


def reload_sports_ref():
    load_sports_ref.cache_clear()


def _weighted_avg(weights: dict[str, float], scores: dict[str, float]) -> tuple[float, float]:
    """(가중평균, 가중치합). 가중치 0 인 축은 무시."""
    num = sum(w * scores.get(ax, 0.0) for ax, w in weights.items() if w > 0)
    den = sum(w for w in weights.values() if w > 0)
    return (num / den if den else 0.0, den)


def _build_explanation(name: str, strengths: list[dict], cautions: list[dict]) -> str:
    """강점·주의 데이터를 사람이 읽기 좋은 한 문장으로 조립."""
    if strengths:
        s = ", ".join(f"{x['ability']} {round(x['score'])}점" for x in strengths)
        txt = f"{s}이 강점이라 {name}에 적합합니다."
    else:
        txt = f"{name} 적합도를 평가했습니다."
    if cautions:
        c = ", ".join(f"{x['bodypart']}(위험 {round(x['risk'])})" for x in cautions)
        txt += f" 다만 {c} 부위는 부상위험이 높아 관리가 필요합니다."
    else:
        txt += " 부상위험이 특별히 높은 부위는 없습니다."
    return txt


def profile(sample: dict) -> tuple[dict[str, float], dict[str, float]]:
    """운동능력·부상위험 점수 (엔진 재사용)."""
    ath = {k: round(v, 2) for k, v in engine.score_player(sample, load_ref_cached("athletic")).items()}
    inj = {k: round(v, 2) for k, v in engine.score_player(sample, load_ref_cached("injury")).items()}
    return ath, inj


def rank_sports(ath: dict, inj: dict, lam: float | None = None) -> list[dict]:
    """모든 (종목, 포지션) 블록의 점수를 계산해 내림차순 정렬."""
    sref = load_sports_ref()
    s = sref["settings"]
    lam = float(s.get("injury_penalty_lambda", 0.3)) if lam is None else lam
    str_min_w = float(s.get("strength_min_weight", 2))   # 강점: 능력 가중치 하한
    caut_min_w = float(s.get("caution_min_weight", 1))   # 주의: 부위 가중치 하한
    caut_min = float(s.get("caution_min_risk", 60))      # 주의: 부상위험 점수 하한

    ranked = []
    for key in sref["sports"]:
        aw = sref["ability_w"][key]
        rw = sref["risk_w"].get(key, {})
        fit, _ = _weighted_avg(aw, ath)
        injury, _ = _weighted_avg(rw, inj)
        score = fit * (1 - lam * injury / 100.0)

        # 이유: 강점 능력(가중치 높고 점수 높은 순)
        contribs = sorted(((aw[a] * ath.get(a, 0), a) for a in aw if aw[a] >= str_min_w), reverse=True)
        strengths = [{"ability": a, "score": ath.get(a, 0), "weight": aw[a]} for _, a in contribs[:3]]
        # 주의: 종목이 중시하는 부위 중 위험 점수 높은 것
        cautions = [{"bodypart": b, "risk": inj.get(b, 0), "weight": rw[b]}
                    for b in rw if rw[b] >= caut_min_w and inj.get(b, 0) >= caut_min]
        cautions.sort(key=lambda c: (-c["weight"], -c["risk"]))

        ranked.append({
            "sport": key[0],
            "position": key[1] or None,
            "name": label(key),
            "score": round(score, 2),
            "fit": round(fit, 2),
            "injury_risk": round(injury, 2),
            "explanation": _build_explanation(label(key), strengths, cautions),
            "strengths": strengths,
            "cautions": cautions,
        })
    ranked.sort(key=lambda r: r["score"], reverse=True)
    return ranked


def recommend_by_id(group: str, sample_id: str, role: str) -> dict:
    target = get_store().get(group, sample_id, role)
    if target is None:
        return {"found": False}
    ath, inj = profile(target)
    ranked = rank_sports(ath, inj)
    top_n = int(load_sports_ref()["settings"].get("top_n", 3))
    return {
        "found": True,
        "sample_id": target.get("sample_id"),
        "group": target.get("group"),
        "role": target.get("role"),
        "profile": {"athletic": ath, "injury": inj},
        "recommendations": ranked[:top_n],
        "all_scores": [{"sport": r["sport"], "position": r["position"], "score": r["score"]} for r in ranked],
    }
