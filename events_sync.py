"""Sync de evaluaciones de candidatos a pyme-events-platform.

Lee resultados.json + estados.json del DATA_DIR (Railway Volume) y emite
eventos anonimizados a la plataforma central de data flywheel.

Idempotencia: vía `eventos_emitidos.json` en DATA_DIR (mapa key -> event_id).
Re-correr el sync NO duplica — las keys ya emitidas se saltean.

Automatización: `start_scheduler()` lanza un loop que corre `sync_all()` todos
los días a SYNC_HOUR_UTC. Se llama desde el startup de main.py.

Disparo manual: POST /admin/sync-events con header X-Sync-Token.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import httpx
from fastapi import APIRouter, Header, HTTPException, status

logger = logging.getLogger("events_sync")

router = APIRouter(prefix="/admin", tags=["admin"])

# Cliente y fuente — fijos para esta app
CLIENT_NAME = "Guchini"  # mismo cliente que guchini-ops (Federico es dueño)
SECTOR = "gastro"
FUENTE = "franquicias-ia"

CONCURRENCY = 10
SYNC_HOUR_UTC = 6  # ~03:00 Argentina (UTC-3), horario de baja actividad

# Estados manuales (estados.json) → tipo_evento de la plataforma
ESTADO_TO_EVENTO = {
    "Aprobado": "candidato_aprobado",
    "Rechazado": "candidato_rechazado",
    "Contactado": "candidato_contactado",
}


def _score_bucket(score: float) -> str:
    """Bucket de score (1-10) — análogo a monto_bucket del spec original."""
    if score < 4:
        return "1-4"
    if score < 6:
        return "4-6"
    if score < 7.5:
        return "6-7.5"
    if score < 9:
        return "7.5-9"
    return "9-10"


def _hash_client_id(name: str) -> str:
    return hashlib.sha256(name.encode()).hexdigest()[:16]


def _hash_internal(name: str, client_hash: str) -> str:
    return hashlib.sha256(f"{client_hash}:{name}".encode()).hexdigest()[:12]


# ── Idempotencia: eventos_emitidos.json ────────────────────────────────────

def _emitted_path() -> Path:
    return Path(os.environ.get("DATA_DIR", ".")) / "eventos_emitidos.json"


def _load_emitted() -> dict[str, int]:
    """Mapa {anomalia_key: event_id} de lo ya emitido a la plataforma."""
    p = _emitted_path()
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def _save_emitted(emitted: dict[str, int]) -> None:
    _emitted_path().write_text(
        json.dumps(emitted, ensure_ascii=False, indent=2), encoding="utf-8"
    )


# ── Construcción de eventos ────────────────────────────────────────────────

def _build_evento_evaluado(client_hash: str, r: dict, now_iso: str) -> dict:
    cand_id = r.get("id")
    ev = r.get("evaluacion") or {}
    score = float(ev.get("score") or 0)
    cand_hash = _hash_internal(str(cand_id), client_hash)
    return {
        "fuente": FUENTE,
        "sector": SECTOR,
        "cliente_id_hash": client_hash,
        "tipo_evento": "candidato_evaluado",
        "payload": {
            "candidato_hash": cand_hash,
            "score_bucket": _score_bucket(score),
            "score": score,
            "recomendacion": ev.get("recomendacion") or "REVISAR",
            "ciudad": r.get("ciudad", ""),
            "breakdown": ev.get("breakdown") or {},
        },
        "timestamp_evento": now_iso,
    }


def _build_evento_estado(client_hash: str, r: dict, estado: str, now_iso: str) -> dict | None:
    tipo = ESTADO_TO_EVENTO.get(estado)
    if not tipo:
        return None
    cand_id = r.get("id")
    ev = r.get("evaluacion") or {}
    score = float(ev.get("score") or 0)
    cand_hash = _hash_internal(str(cand_id), client_hash)
    return {
        "fuente": FUENTE,
        "sector": SECTOR,
        "cliente_id_hash": client_hash,
        "tipo_evento": tipo,
        "payload": {
            "candidato_hash": cand_hash,
            "score_bucket": _score_bucket(score),
            "ciudad": r.get("ciudad", ""),
        },
        "timestamp_evento": now_iso,
    }


async def _post_event(
    http: httpx.AsyncClient, headers: dict, body: dict
) -> tuple[bool, int | None, str]:
    """Devuelve (ok, event_id, error)."""
    try:
        resp = await http.post("/events", headers=headers, json=body)
        if resp.status_code == 200:
            return True, resp.json().get("event_id"), ""
        return False, None, f"HTTP {resp.status_code}: {resp.text[:200]}"
    except Exception as e:
        return False, None, str(e)


async def sync_all() -> dict[str, Any]:
    """Emite a la plataforma solo los eventos nuevos. Idempotente."""
    url = os.environ.get("EVENTS_PLATFORM_URL", "").rstrip("/")
    key = os.environ.get("EVENTS_PLATFORM_KEY", "")
    if not url or not key:
        return {"ok": False, "error": "EVENTS_PLATFORM_URL o EVENTS_PLATFORM_KEY no configurados"}

    data_dir = Path(os.environ.get("DATA_DIR", "."))
    resultados_path = data_dir / "resultados.json"
    estados_path = data_dir / "estados.json"
    if not resultados_path.exists():
        return {"ok": False, "error": f"resultados.json no encontrado en {resultados_path}"}

    resultados = json.loads(resultados_path.read_text(encoding="utf-8"))
    estados = (
        json.loads(estados_path.read_text(encoding="utf-8"))
        if estados_path.exists() else {}
    )

    client_hash = _hash_client_id(CLIENT_NAME)
    now_iso = datetime.now(timezone.utc).isoformat()
    headers = {"X-API-Key": key, "Content-Type": "application/json"}

    emitted = _load_emitted()

    # (key, body) de todos los eventos posibles
    candidates: list[tuple[str, dict]] = []
    for r in resultados:
        cid = r.get("id")
        if cid is None:
            continue
        candidates.append(
            (f"candidato_evaluado:{cid}", _build_evento_evaluado(client_hash, r, now_iso))
        )
        estado = (estados.get(str(cid)) or {}).get("estado")
        if estado:
            ev = _build_evento_estado(client_hash, r, estado, now_iso)
            if ev:
                candidates.append((f"{ev['tipo_evento']}:{cid}", ev))

    to_send = [(k, b) for k, b in candidates if k not in emitted]

    sent = 0
    errors: list[str] = []
    new_emitted: dict[str, int] = {}
    sem = asyncio.Semaphore(CONCURRENCY)

    async with httpx.AsyncClient(base_url=url, timeout=30.0) as http:
        async def go(item: tuple[str, dict]) -> None:
            nonlocal sent
            k, body = item
            async with sem:
                ok, event_id, err = await _post_event(http, headers, body)
                if ok and event_id is not None:
                    sent += 1
                    new_emitted[k] = event_id
                elif not ok and len(errors) < 20:
                    errors.append(f"{k}: {err}")

        await asyncio.gather(*(go(it) for it in to_send))

    if new_emitted:
        emitted.update(new_emitted)
        _save_emitted(emitted)

    return {
        "ok": True,
        "sent": sent,
        "attempted": len(to_send),
        "skipped_ya_emitidos": len(candidates) - len(to_send),
        "total_eventos_posibles": len(candidates),
        "errors": errors,
    }


# ── Scheduler diario ───────────────────────────────────────────────────────

async def _scheduler_loop() -> None:
    """Corre sync_all() todos los días a SYNC_HOUR_UTC. Background task."""
    while True:
        now = datetime.now(timezone.utc)
        nxt = now.replace(hour=SYNC_HOUR_UTC, minute=0, second=0, microsecond=0)
        if nxt <= now:
            nxt += timedelta(days=1)
        wait_s = (nxt - now).total_seconds()
        logger.info("events_sync scheduler: proximo sync en %.1f h", wait_s / 3600)
        await asyncio.sleep(wait_s)
        try:
            result = await sync_all()
            logger.info("events_sync scheduled run: %s", result)
        except Exception as e:
            logger.error("events_sync scheduled run failed: %s", e)


def start_scheduler() -> None:
    """Lanza el loop de sync diario como background task.
    Llamar desde un startup event de FastAPI (hay event loop corriendo)."""
    asyncio.create_task(_scheduler_loop())


@router.post("/sync-events")
async def admin_sync_events(
    x_sync_token: str = Header(default="", alias="X-Sync-Token"),
) -> dict:
    expected = os.environ.get("SYNC_ADMIN_TOKEN", "")
    if not expected:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="SYNC_ADMIN_TOKEN no configurado en este service",
        )
    if x_sync_token != expected:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="X-Sync-Token invalido",
        )
    return await sync_all()


if __name__ == "__main__":
    result = asyncio.run(sync_all())
    print(json.dumps(result, indent=2, ensure_ascii=False))
