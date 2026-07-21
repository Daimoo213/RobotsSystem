from app.core.redis import CHANNEL_ALERTS, CHANNEL_DEVICES
from app.ws.router import _resolve_channels


def test_browser_channel_names_map_to_redis_channels() -> None:
    assert _resolve_channels(["devices", "alerts"]) == {CHANNEL_DEVICES, CHANNEL_ALERTS}


def test_redis_channel_names_remain_supported() -> None:
    assert _resolve_channels([CHANNEL_DEVICES]) == {CHANNEL_DEVICES}
