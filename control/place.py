from __future__ import annotations

from shared.langs import KIND_LANG


def env_rank(env: dict, scan: dict) -> tuple:
    lang = str(scan.get("language") or "")
    kind = str(env.get("kind") or "")
    expect = KIND_LANG.get(kind) or ""
    if lang == "html" and kind == "python":
        exact = 0
    elif expect and lang and lang == expect:
        exact = 0
    else:
        exact = 1
    pkgs = int(env.get("pkg_n") or 0)
    return (exact, -pkgs, str(env.get("id") or ""))


def pick_env(ready: list[dict], scan: dict) -> dict:
    if not ready:
        raise ValueError("no environment")
    return sorted(ready, key=lambda item: env_rank(item, scan))[0]


def score_worker(
    *,
    idle: bool,
    queued: int,
    cpu: float,
    mem: float,
    sticky: bool,
    has_gpu: bool,
    needs_gpu: bool,
) -> int:
    score = 0
    if idle:
        score += 400
    score -= max(0, int(queued)) * 80
    score -= min(100, max(0, int(cpu or 0)))
    score -= min(100, max(0, int(mem or 0))) // 4
    if sticky:
        score += 35
    if needs_gpu:
        score += 60 if has_gpu else -500
    return score
