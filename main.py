"""
Webhook Dispatcher — Tallos / RD Conversas

Recebe TODOS os webhooks do RD Conversas e roteia para os bots corretos
com base em tags, departamento ou canal do contato.

Arquitetura:
  RD Conversas → POST /webhook/tallos → Dispatcher → BOT MBA (8002)
                                                    → BOT PJ  (8001)
                                                    → BOT X   (XXXX) ← futuro

Para adicionar um novo bot: edite BOTS em config.py e reinicie o serviço.
"""

import asyncio
import logging
import time
from contextlib import asynccontextmanager
from typing import Any, Dict, List

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from config import BOTS, DISPATCHER_LOG_LEVEL, FORWARD_TIMEOUT

# ── Logging ───────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=getattr(logging, DISPATCHER_LOG_LEVEL, logging.INFO),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("dispatcher")


# ── Deduplicação (RD Conversas dispara o mesmo evento várias vezes) ──────────
_SEEN: Dict[str, float] = {}
_DEDUP_TTL = 60  # segundos


def _is_duplicate(event_id: str) -> bool:
    if not event_id:
        return False
    now = time.time()
    # limpa entradas antigas
    expired = [k for k, v in _SEEN.items() if now - v > _DEDUP_TTL]
    for k in expired:
        _SEEN.pop(k, None)
    if event_id in _SEEN:
        return True
    _SEEN[event_id] = now
    return False


# ── Extração de dados do payload Tallos ──────────────────────────────────────

def _extract_event_id(body: Dict) -> str:
    """Tenta extrair um ID único do evento para deduplicação."""
    return (
        body.get("message_id")
        or body.get("id")
        or (body.get("message") or {}).get("id", "")
        or ""
    )


def _extract_routing_info(body: Dict) -> Dict[str, Any]:
    """Extrai campos relevantes para o roteamento."""
    contact = body.get("contact") or {}
    dept    = (contact.get("department") or {})
    tags    = [
        (t.get("name") or t if isinstance(t, str) else "").lower()
        for t in (contact.get("tags") or [])
    ]
    dept_name  = (dept.get("name") or "").lower()
    channel    = (body.get("channel") or body.get("source") or "").lower()
    event_type = (body.get("type") or body.get("event_type") or body.get("action") or "").lower()

    return {
        "tags":       tags,
        "dept":       dept_name,
        "channel":    channel,
        "event_type": event_type,
        "contact_id": contact.get("id") or contact.get("contact_id") or "",
        "phone":      contact.get("phone") or contact.get("number") or "",
    }


# ── Lógica de roteamento ──────────────────────────────────────────────────────

def _matches(bot_cfg: Dict, info: Dict) -> bool:
    """
    Verifica se um bot deve receber este evento.

    Cada bot em config.py pode ter:
      match_tags   : list[str]  — qualquer tag do contato que contenha um desses strings
      match_dept   : list[str]  — departamento contém algum desses strings
      match_channel: list[str]  — canal contém algum desses strings
      default      : bool       — recebe tudo que não foi roteado para outro bot específico
    """
    match_tags    = bot_cfg.get("match_tags", [])
    match_dept    = bot_cfg.get("match_dept", [])
    match_channel = bot_cfg.get("match_channel", [])

    if match_tags and any(
        any(m in tag for m in match_tags)
        for tag in info["tags"]
    ):
        return True

    if match_dept and any(m in info["dept"] for m in match_dept):
        return True

    if match_channel and any(m in info["channel"] for m in match_channel):
        return True

    return False


def _select_bots(body: Dict) -> List[Dict]:
    """Retorna a lista de bots que devem receber este evento."""
    info = _extract_routing_info(body)
    logger.debug(f"[ROUTE] info={info}")

    # Primeiro tenta match específico
    specific = [b for b in BOTS if _matches(b, info)]

    if specific:
        logger.info(
            f"[ROUTE] Roteando para bots específicos: {[b['name'] for b in specific]}"
            f" | dept={info['dept']} tags={info['tags']}"
        )
        return specific

    # Fallback: bots marcados como default
    defaults = [b for b in BOTS if b.get("default", False)]
    if defaults:
        logger.info(
            f"[ROUTE] Sem match — usando default: {[b['name'] for b in defaults]}"
        )
        return defaults

    # Último recurso: todos os bots
    logger.warning("[ROUTE] Sem match e sem default — enviando para todos os bots")
    return BOTS


# ── Envio assíncrono ──────────────────────────────────────────────────────────

async def _forward(client: httpx.AsyncClient, bot: Dict, payload: Dict, headers: Dict) -> None:
    """Encaminha o payload para um bot. Erros são logados mas não propagados."""
    url = bot["url"]
    try:
        resp = await client.post(url, json=payload, headers=headers, timeout=FORWARD_TIMEOUT)
        logger.info(f"[FWD] {bot['name']} ← HTTP {resp.status_code} | {url}")
    except Exception as e:
        logger.error(f"[FWD] {bot['name']} ERRO: {e} | {url}")


# ── FastAPI ───────────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("=== Webhook Dispatcher iniciado ===")
    for b in BOTS:
        logger.info(f"  Bot registrado: {b['name']} → {b['url']}")
    yield
    logger.info("=== Webhook Dispatcher encerrado ===")


app = FastAPI(title="Webhook Dispatcher", lifespan=lifespan)


@app.post("/webhook/tallos")
async def dispatch_tallos(request: Request):
    """Recebe webhook do RD Conversas e roteia para os bots corretos."""
    try:
        body = await request.json()
    except Exception:
        body = {}

    # Deduplicação
    event_id = _extract_event_id(body)
    if _is_duplicate(event_id):
        logger.debug(f"[DEDUP] Evento duplicado ignorado: {event_id}")
        return JSONResponse({"status": "duplicate", "ok": True})

    # Seleciona bots destino
    targets = _select_bots(body)

    if not targets:
        logger.warning("[ROUTE] Nenhum bot destino encontrado — descartando evento")
        return JSONResponse({"status": "no_targets", "ok": True})

    # Repassa headers relevantes (secret, content-type)
    forward_headers = {"Content-Type": "application/json"}
    for h in ("x-tallos-secret", "x-hub-signature", "x-hub-signature-256"):
        val = request.headers.get(h)
        if val:
            forward_headers[h] = val

    # Envia para todos os bots destino de forma concorrente (fire-and-forget)
    async with httpx.AsyncClient() as client:
        await asyncio.gather(
            *[_forward(client, bot, body, forward_headers) for bot in targets],
            return_exceptions=True,
        )

    return JSONResponse({"status": "ok", "routed_to": [b["name"] for b in targets]})


@app.post("/webhook/tallospj")
async def dispatch_tallospj(request: Request):
    """Registro de lead PJ — encaminha diretamente para o BOT PJ."""
    try:
        body = await request.json()
    except Exception:
        body = {}

    pj_bots = [b for b in BOTS if "pj" in b["name"].lower()]
    if not pj_bots:
        logger.error("[ROUTE] Nenhum bot PJ registrado para /webhook/tallospj")
        return JSONResponse({"status": "no_pj_bot", "ok": False}, status_code=500)

    forward_headers = {"Content-Type": "application/json"}
    for h in ("x-tallos-secret",):
        val = request.headers.get(h)
        if val:
            forward_headers[h] = val

    async with httpx.AsyncClient() as client:
        for bot in pj_bots:
            url = bot["url"].replace("/webhook/tallos", "/webhook/tallospj")
            try:
                resp = await client.post(url, json=body, headers=forward_headers, timeout=FORWARD_TIMEOUT)
                logger.info(f"[FWD-PJ] {bot['name']} ← HTTP {resp.status_code}")
            except Exception as e:
                logger.error(f"[FWD-PJ] {bot['name']} ERRO: {e}")

    return JSONResponse({"status": "ok"})


@app.post("/webhook/tallosmba")
async def dispatch_tallosmba(request: Request):
    """Registro de lead MBA — encaminha diretamente para o BOT MBA."""
    try:
        body = await request.json()
    except Exception:
        body = {}

    mba_bots = [b for b in BOTS if "mba" in b["name"].lower()]
    if not mba_bots:
        logger.error("[ROUTE] Nenhum bot MBA registrado para /webhook/tallosmba")
        return JSONResponse({"status": "no_mba_bot", "ok": False}, status_code=500)

    forward_headers = {"Content-Type": "application/json"}
    async with httpx.AsyncClient() as client:
        for bot in mba_bots:
            url = bot["url"].replace("/webhook/tallos", "/webhook/tallosmba")
            try:
                resp = await client.post(url, json=body, headers=forward_headers, timeout=FORWARD_TIMEOUT)
                logger.info(f"[FWD-MBA] {bot['name']} ← HTTP {resp.status_code}")
            except Exception as e:
                logger.error(f"[FWD-MBA] {bot['name']} ERRO: {e}")

    return JSONResponse({"status": "ok"})


@app.get("/health")
async def health():
    return {"status": "ok", "bots": [{"name": b["name"], "url": b["url"]} for b in BOTS]}
