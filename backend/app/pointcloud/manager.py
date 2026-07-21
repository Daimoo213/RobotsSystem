"""Point-cloud runtime intentionally disabled until a mapping gateway is configured."""

class PointCloudManager:
    """Compatibility surface that never manufactures a scene."""

    async def start(self) -> None:
        return None

    async def stop(self) -> None:
        return None

    def status(self) -> dict:
        return {"source": "not_configured", "active": False, "points_count": 0, "progress": 0.0}
