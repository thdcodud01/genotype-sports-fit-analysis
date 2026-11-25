"""
샘플 저장소. data/<group>.json 들을 메모리에 적재하고
(group, sample_id, role) 로 조회한다.

지금은 JSON 파일 기반이지만, 나중에 DB 등으로 바꾸려면
이 파일(get / get_cohort / load)만 교체하면 된다. (API·엔진은 그대로)
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]   # api/
DATA_DIR = ROOT / "data"
META = ("sample_id", "group", "role", "position")


def _flatten(rec: dict) -> dict[str, Any]:
    """저장 레코드(genotypes 중첩) -> 엔진/응답용 평탄 dict."""
    flat = dict(rec.get("genotypes", {}))
    for m in META:
        if m in rec:
            flat[m] = rec[m]
    return flat


class SampleStore:
    def __init__(self, data_dir: Path = DATA_DIR):
        self.data_dir = Path(data_dir)
        self._by_key: dict[tuple[str, str, str], dict] = {}
        self._by_group_role: dict[tuple[str, str], list[dict]] = {}
        self.load()

    def load(self) -> None:
        self._by_key.clear()
        self._by_group_role.clear()
        if not self.data_dir.exists():
            return
        for f in sorted(self.data_dir.glob("*.json")):
            try:
                records = json.loads(f.read_text(encoding="utf-8"))
            except Exception as e:
                print(f"[경고] {f.name} 읽기 실패: {e}")
                continue
            for rec in records:
                flat = _flatten(rec)
                group = str(flat.get("group", f.stem))
                sid = str(flat.get("sample_id", ""))
                role = str(flat.get("role", ""))
                self._by_key[(group, sid, role)] = flat
                self._by_group_role.setdefault((group, role), []).append(flat)

    # 조회: group + sample_id + role
    def get(self, group: str, sample_id: str, role: str) -> dict | None:
        return self._by_key.get((group.strip(), sample_id.strip(), role.strip()))

    # 분류 기준 집단: 같은 group + 같은 role 전체
    def get_cohort(self, group: str, role: str) -> list[dict]:
        return list(self._by_group_role.get((group.strip(), role.strip()), []))

    def all(self) -> list[dict]:
        return list(self._by_key.values())

    @property
    def groups(self) -> list[str]:
        return sorted({g for (g, _, _) in self._by_key})

    def count(self) -> int:
        return len(self._by_key)


# 모듈 싱글턴 (서버 기동 시 1회 로딩, reload 로 갱신)
_store: SampleStore | None = None


def get_store() -> SampleStore:
    global _store
    if _store is None:
        _store = SampleStore()
    return _store


def reload_store() -> int:
    get_store().load()
    return get_store().count()
