"""Authenticated Redis-to-browser WebSocket gateway."""

from __future__ import annotations

import asyncio
import json

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, status

from app.core.logging import get_logger
from app.core.redis import (
    ALL_CHANNELS, CHANNEL_ALERTS, CHANNEL_DEVICES, CHANNEL_ESTOP, CHANNEL_EVENTS,
    CHANNEL_POINTCLOUD, CHANNEL_SCRIPT, CHANNEL_TASKS, redis,
)
from app.core.security import Role, decode_token

router = APIRouter()
ws_router = router
log = get_logger("ws.router")

WS_CHANNELS = {
    "alerts": CHANNEL_ALERTS, "devices": CHANNEL_DEVICES, "estop": CHANNEL_ESTOP,
    "events": CHANNEL_EVENTS, "pointcloud": CHANNEL_POINTCLOUD, "script": CHANNEL_SCRIPT,
    "tasks": CHANNEL_TASKS,
}
REDIS_TO_WS_CHANNEL = {value: key for key, value in WS_CHANNELS.items()}
ROLE_CHANNELS = {
    Role.PM.value: {"devices", "tasks", "alerts", "events", "estop", "script"},
    Role.OM.value: {"devices", "alerts", "events", "estop", "pointcloud"},
}


def _resolve_channels(requested_channels: list[str]) -> set[str]:
    if not requested_channels or "all" in requested_channels:
        return set(ALL_CHANNELS)
    return {
        WS_CHANNELS.get(channel, channel)
        for channel in requested_channels
        if channel in WS_CHANNELS or channel in ALL_CHANNELS
    }


@router.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket) -> None:
    requested_protocols = [item.strip() for item in websocket.headers.get("sec-websocket-protocol", "").split(",")]
    token = next((item[4:] for item in requested_protocols if item.startswith("jwt.")), None)
    payload = decode_token(token or "")
    role = str(payload.get("role")) if payload else ""
    if role not in ROLE_CHANNELS:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return
    requested = [item.strip() for item in websocket.query_params.get("channels", "").split(",") if item.strip()]
    allowed = ROLE_CHANNELS[role]
    if not requested or "all" in requested:
        requested = sorted(allowed)
    if any(channel not in allowed for channel in requested):
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return
    subscribed = _resolve_channels(requested)
    await websocket.accept(subprotocol=f"jwt.{token}")
    sub_task = asyncio.create_task(_redis_subscriber(websocket, subscribed))
    try:
        while True:
            message = json.loads(await websocket.receive_text())
            channel = message.get("channel")
            if not isinstance(channel, str) or channel not in allowed:
                continue
            resolved = _resolve_channels([channel])
            if message.get("type") == "subscribe":
                subscribed.update(resolved)
            elif message.get("type") == "unsubscribe":
                subscribed.difference_update(resolved)
    except WebSocketDisconnect:
        pass
    except Exception as exc:
        log.warning("ws.error", error=str(exc))
    finally:
        sub_task.cancel()


async def _redis_subscriber(websocket: WebSocket, subscribed: set[str]) -> None:
    pubsub = redis().pubsub()
    await pubsub.subscribe(*subscribed)
    try:
        async for message in pubsub.listen():
            if message["type"] != "message" or message["channel"] not in subscribed:
                continue
            payload = json.loads(message["data"])
            payload["channel"] = REDIS_TO_WS_CHANNEL.get(message["channel"], message["channel"])
            await websocket.send_text(json.dumps(payload))
    except asyncio.CancelledError:
        pass
    finally:
        await pubsub.unsubscribe(*subscribed)
        await pubsub.aclose()


async def broadcast_to_ws(channel: str, data: dict) -> None:
    await redis().publish(channel, json.dumps({"channel": channel, "data": data}))
