"""WebSocket de eventos. Autenticação na primeira mensagem (token fora da URL e dos logs de acesso)."""
from __future__ import annotations

import asyncio
import contextlib
import json
import logging

from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect

from . import bus
from .auth import user_from_token

router = APIRouter()
log = logging.getLogger("papo.ws")


@router.websocket("/api/ws")
async def events(ws: WebSocket) -> None:
    await ws.accept()
    try:
        first = json.loads(await asyncio.wait_for(ws.receive_text(), timeout=10))
        user = await user_from_token(str(first.get("token", "")))
    except (TimeoutError, json.JSONDecodeError, HTTPException, AttributeError):
        await ws.close(code=4401)
        return
    await ws.send_text(json.dumps({"type": "ready"}))
    pubsub = bus.redis().pubsub()
    await pubsub.subscribe(bus.channel(user.id))

    async def pump() -> None:
        async for msg in pubsub.listen():
            if msg.get("type") == "message":
                await ws.send_text(str(msg["data"]))

    async def keepalive() -> None:
        while True:
            await asyncio.sleep(25)
            await ws.send_text('{"type":"ping"}')

    async def inbound() -> None:
        while True:
            await ws.receive_text()        # renovação de token e pings do cliente; nada a fazer

    tasks = [asyncio.create_task(t()) for t in (pump, keepalive, inbound)]
    try:
        await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
    except WebSocketDisconnect:
        pass
    finally:
        for t in tasks:
            t.cancel()
        with contextlib.suppress(Exception):
            await pubsub.unsubscribe()
            await pubsub.aclose()  # type: ignore[no-untyped-call]
