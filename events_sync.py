"""Sync de evaluaciones de candidatos a pyme-events-platform.

Lee resultados.json + estados.json del DATA_DIR (Railway Volume) y emite
eventos anonimizados a la plataforma central de data flywheel.

Disparado via POST /admin/sync-events con header X-Sync-Token.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
from datetime import datetime, timezone
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

# Concurrencia para no demorar más de ~10s en ~700 candidatos
CONCURRENCY = 10


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


# Estados manuales (estados.json) → tipo_evento de la plataforma
ESTADO_TO_EVENTO = {
    "Aprobado": "candidato_aprobado",
    "Rechazado": "candidato_rechazado",
    "Contactado": "candidato_contactado",
}


async def _post_event(http: httpx.AsyncClient, headers: dict, body: dict) -> tuple[bool, str]:
    try:
        resp = await http.post("/events", headers=headers, json=body)
        if resp.status_code == 200:
            return True, ""
        return False, f"HTTP {resp.status_code}: {resp.text[:200]}"
    except Exception as e:
        return False, str(e)


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


async def sync_all() -> dict[str, Any]:
    """Lee resultados + estados y emite todos los eventos. Idempotencia: NONE.
    Re-correr generará duplicados en la DB de eventos."""
    url = os.environ.get("EVENTS_PLATFORM_URL", "").rstrip("/")
    key = os.environ.get("EVENTS_PLATFORM_KEY", "")
    if not url or not key:
        return {"ok": False, "error": "EVENTS_PLATFORM_URL o EVENTS_PLATFORM_KEY no setteados"}

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

    # Construyo todos los bodies a enviar
    bodies: list[dict] = []
    for r in resultados:
        if r.get("id") is None:
            continue
        bodies.append(_build_evento_evaluado(client_hash, r, now_iso))
        estado = (estados.get(str(r.get("id"))) or {}).get("estado")
        evento_estado = _build_evento_estado(client_hash, r, estado, now_iso) if estado else None
        if evento_estado:
            bodies.append(evento_estado)

    sent = 0
    errors: list[str] = []
    sem = asyncio.Semaphore(CONCURRENCY)

    async with httpx.AsyncClient(base_url=url, timeout=30.0) as http:
        async def go(body: dict) -> None:
            nonlocal sent
            async with sem:
                ok, err = await _post_event(http, headers, body)
                if ok:
                    sent += 1
                elif len(errors) < 20:
                    errors.append(err)

        await asyncio.gather(*(go(b) for b in bodies))

    return {
        "ok": True,
        "sent": sent,
        "attempted": len(bodies),
        "errors": errors,
    }


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
