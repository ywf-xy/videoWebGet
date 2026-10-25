"""数据源 DTO。"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import Field, field_validator

from app.schemas.common import CamelModel, validate_http_url

SourceType = Literal["video", "text", "image"]


class DataSourceItem(CamelModel):
    """列表项。"""

    id: int
    name: str
    type: str
    category: str | None = None
    homepage_url: str
    alt_urls_count: int = 0
    health_score: int | None = None
    last_crawled_at: str | None = None
    total_items: int = 0
    enabled: bool = True
    has_script: bool = False
    created_at: str | None = None
    updated_at: str | None = None


class DataSourceDetail(CamelModel):
    """详情（含脚本全文、config_json 与游标三字段）。"""

    id: int
    name: str
    type: str
    category: str | None = None
    homepage_url: str
    alt_urls: list[str] = Field(default_factory=list)
    current_url: str | None = None
    script: str | None = None
    script_entry: str = "parse"
    config_json: dict[str, Any] = Field(default_factory=dict)
    is_novel: bool = False
    enabled: bool = True
    health_score: int | None = None
    success_rate_20: float | None = None
    last_success_at: str | None = None
    last_crawled_at: str | None = None
    total_items: int = 0
    cursor_last_item_no: int = 0
    cursor_last_page: int = 0
    cursor_last_success_date: str | None = None
    notes: str | None = None
    created_at: str | None = None
    updated_at: str | None = None


class DataSourceCreate(CamelModel):
    """新增入参。"""

    name: str = Field(min_length=1, max_length=100)
    type: SourceType
    category: str | None = Field(default=None, max_length=100)
    homepage_url: str
    alt_urls: list[str] = Field(default_factory=list)
    current_url: str | None = None
    script: str | None = None
    script_entry: str = "parse"
    config_json: dict[str, Any] = Field(default_factory=dict)
    is_novel: bool = False
    enabled: bool = True
    notes: str | None = None

    @field_validator("homepage_url")
    @classmethod
    def _check_url(cls, value: str) -> str:
        return validate_http_url(value)

    @field_validator("current_url")
    @classmethod
    def _check_current_url(cls, value: str | None) -> str | None:
        return validate_http_url(value) if value else value

    @field_validator("alt_urls")
    @classmethod
    def _check_alt_urls(cls, value: list[str]) -> list[str]:
        cleaned: list[str] = []
        for item in value:
            text = str(item or "").strip()
            if not text:
                continue
            cleaned.append(validate_http_url(text))
        return cleaned


class DataSourceUpdate(CamelModel):
    """编辑入参（全部可选，仅提交的字段生效）。"""

    name: str | None = Field(default=None, min_length=1, max_length=100)
    type: SourceType | None = None
    category: str | None = Field(default=None, max_length=100)
    homepage_url: str | None = None
    alt_urls: list[str] | None = None
    current_url: str | None = None
    script: str | None = None
    script_entry: str | None = None
    config_json: dict[str, Any] | None = None
    is_novel: bool | None = None
    enabled: bool | None = None
    notes: str | None = None

    @field_validator("homepage_url")
    @classmethod
    def _check_url(cls, value: str | None) -> str | None:
        return validate_http_url(value) if value else value

    @field_validator("current_url")
    @classmethod
    def _check_current_url(cls, value: str | None) -> str | None:
        return validate_http_url(value) if value else value

    @field_validator("alt_urls")
    @classmethod
    def _check_alt_urls(cls, value: list[str] | None) -> list[str] | None:
        if value is None:
            return None
        return [validate_http_url(str(item).strip()) for item in value if str(item).strip()]


class EnabledPayload(CamelModel):
    """启停入参。"""

    enabled: bool


class EnabledResp(CamelModel):
    """启停出参。"""

    enabled: bool


class HealthResp(CamelModel):
    """数据源健康度。"""

    health_score: int | None = None
    success_rate_20: float | None = None
    last_success_at: str | None = None
    sample_size: int = 0


class ScriptValidatePayload(CamelModel):
    """脚本语法校验入参。"""

    script: str = ""
    entry: str = "parse"


class ScriptValidateResp(CamelModel):
    """脚本语法校验出参。"""

    valid: bool = True
    line: int | None = None
    column: int | None = None
    message: str = "语法正确"


class ScriptTestPayload(CamelModel):
    """脚本试运行入参。"""

    script: str = ""
    entry: str = "parse"
    url: str


class ScriptTestResp(CamelModel):
    """脚本试运行出参（回显前 5 条）。"""

    count: int = 0
    fields: list[str] = Field(default_factory=list)
    samples: list[dict[str, Any]] = Field(default_factory=list)


class ImportRowResult(CamelModel):
    """导入逐行结果。"""

    line: int
    status: str
    reason: str = ""


class ImportResultResp(CamelModel):
    """导入结果。"""

    success: int = 0
    failed: int = 0
    rows: list[ImportRowResult] = Field(default_factory=list)


class DataSourceExportItem(CamelModel):
    """导出项（字段与导入兼容，往返无损）。"""

    name: str
    type: str
    category: str | None = None
    homepage_url: str
    alt_urls: list[str] = Field(default_factory=list)
    script: str | None = None
    script_entry: str = "parse"
    config_json: dict[str, Any] = Field(default_factory=dict)
    is_novel: bool = False
    enabled: bool = True
    notes: str | None = None
