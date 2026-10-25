"""产物 DTO。"""

from __future__ import annotations

from pydantic import Field

from app.schemas.common import CamelModel


class ArtifactItem(CamelModel):
    """产物列表项。"""

    id: int
    task_id: int
    data_source_id: int
    data_source_name: str
    type: str
    name: str
    category: str | None = None
    path: str
    size: int = 0
    status: str
    is_file_exists: bool = False
    created_at: str | None = None


class ArtifactDetail(CamelModel):
    """产物详情。"""

    id: int
    task_id: int
    task_result_id: int | None = None
    data_source_id: int
    data_source_name: str
    type: str
    name: str
    category: str | None = None
    path: str
    size: int = 0
    status: str
    error_msg: str | None = None
    is_file_exists: bool = False
    created_at: str | None = None
    updated_at: str | None = None


class OpenDirResp(CamelModel):
    """打开目录出参（失败时降级返回路径）。"""

    opened: bool = False
    path: str = ""


class RedownloadResp(CamelModel):
    """重新下载出参。"""

    task_id: int
    status: str = "pending"


class ArtifactRedownloadPayload(CamelModel):
    """预留：批量重新下载入参（P2-05）。"""

    artifact_ids: list[int] = Field(default_factory=list)
