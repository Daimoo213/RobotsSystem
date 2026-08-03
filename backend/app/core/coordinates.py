"""Shared project-map coordinate contract."""

from fastapi import HTTPException, status


MAP_FRAME_CONVENTION = (
    "项目地图使用右手笛卡尔坐标系，单位为米：+Z 竖直向上；从 +Z 俯视时，"
    "+Y 位于 +X 逆时针 90 度方向。"
)


def ensure_map_frame(frame_id: str, project_map_frame: str) -> None:
    """Reject coordinates that have not been transformed into the project map frame."""

    if frame_id != project_map_frame:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"坐标系必须与当前项目地图坐标系一致：{project_map_frame}",
        )
