"""HTTP 客户端：统一 UA / Referer / 超时 / 连接复用，404/403 不重试（4005）。

线程安全说明：``requests.Session`` 不是完全线程安全的，因此内部按线程持有独立
Session（``threading.local``），既复用连接又避免并发串扰。
"""

from __future__ import annotations

import threading
import time
from pathlib import Path
from typing import Any

import requests

from app.common.errors import BizError, ErrCode
from app.common.logger import get_logger
from app.config import DEFAULTS

logger = get_logger(__name__)

DEFAULT_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36 CrawlerHub/1.0"
)

#: 不重试的 HTTP 状态码（PRD 9.5）
NO_RETRY_STATUS = frozenset({403, 404, 410, 401})


class HttpClient:
    """带重试与统一请求头的轻量 HTTP 客户端。"""

    def __init__(
        self,
        timeout: float | None = None,
        retries: int | None = None,
        headers: dict[str, str] | None = None,
        user_agent: str | None = None,
    ) -> None:
        self.timeout: float = float(DEFAULTS["http.timeout_s"] if timeout is None else timeout)
        self.retries: int = int(DEFAULTS["http.retries"] if retries is None else retries)
        self.user_agent: str = user_agent or DEFAULT_UA
        self._extra_headers: dict[str, str] = dict(headers or {})
        self._local = threading.local()

    # ------------------------------------------------------------------
    # 内部
    # ------------------------------------------------------------------
    def _session(self) -> requests.Session:
        """获取当前线程的 Session。"""
        session = getattr(self._local, "session", None)
        if session is None:
            session = requests.Session()
            self._local.session = session
        return session

    def _referer(self) -> str | None:
        return getattr(self._local, "referer", None)

    def set_referer(self, url: str | None) -> None:
        """设置当前线程后续请求的 Referer（部分站点防盗链必需）。"""
        self._local.referer = url

    def _headers(self, headers: dict[str, str] | None = None) -> dict[str, str]:
        """合并默认头、Referer 与调用方自定义头。"""
        merged: dict[str, str] = {
            "User-Agent": self.user_agent,
            "Accept": "*/*",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
            "Connection": "keep-alive",
        }
        merged.update(self._extra_headers)
        referer = self._referer()
        if referer:
            merged.setdefault("Referer", referer)
        if headers:
            merged.update(headers)
        return merged

    @staticmethod
    def _sleep_backoff(attempt: int) -> None:
        time.sleep(min(2 ** max(0, attempt - 1), 5))

    # ------------------------------------------------------------------
    # 公共 API
    # ------------------------------------------------------------------
    def get(
        self,
        url: str,
        *,
        params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
        timeout: float | None = None,
        stream: bool = False,
        retries: int | None = None,
        allow_redirects: bool = True,
    ) -> requests.Response:
        """GET 请求（5xx / 超时 / 连接错误自动重试，404/403 立即失败）。"""
        attempts = max(0, int(self.retries if retries is None else retries))
        last_error: BizError | None = None
        for index in range(attempts + 1):
            try:
                response = self._session().get(
                    url,
                    params=params,
                    headers=self._headers(headers),
                    timeout=timeout or self.timeout,
                    stream=stream,
                    allow_redirects=allow_redirects,
                )
            except requests.Timeout:
                last_error = BizError(
                    ErrCode.HTTP_ERROR, f"请求超时：{url}", retryable=True
                )
            except requests.RequestException as exc:
                last_error = BizError(
                    ErrCode.HTTP_ERROR, f"请求失败：{url}（{exc}）", retryable=True
                )
            else:
                status = response.status_code
                if status in NO_RETRY_STATUS:
                    response.close()
                    raise BizError(
                        ErrCode.HTTP_ERROR,
                        f"HTTP {status}：{url}",
                        retryable=False,
                        detail=f"status={status}",
                    )
                if status >= 500:
                    last_error = BizError(
                        ErrCode.HTTP_ERROR, f"HTTP {status}：{url}", retryable=True
                    )
                elif status >= 400:
                    response.close()
                    raise BizError(
                        ErrCode.HTTP_ERROR,
                        f"HTTP {status}：{url}",
                        retryable=False,
                        detail=f"status={status}",
                    )
                else:
                    return response
            if index < attempts:
                logger.warning("HTTP 重试 %s/%s：%s", index + 1, attempts, last_error)
                self._sleep_backoff(index + 1)
        raise last_error or BizError(ErrCode.HTTP_ERROR, f"请求失败：{url}")

    def get_text(self, url: str, *, encoding: str | None = None, **kwargs: Any) -> str:
        """GET 并解码为文本（自动探测编码，缺省 UTF-8）。"""
        response = self.get(url, **kwargs)
        try:
            if encoding:
                return response.content.decode(encoding, errors="replace")
            if response.encoding and response.encoding.lower() not in ("iso-8859-1",):
                return response.text
            apparent = response.apparent_encoding or "utf-8"
            return response.content.decode(apparent, errors="replace")
        finally:
            response.close()

    def get_bytes(self, url: str, **kwargs: Any) -> bytes:
        """GET 并返回二进制内容。"""
        response = self.get(url, **kwargs)
        try:
            return response.content
        finally:
            response.close()

    def stream_to(self, url: str, file_path: str | Path, **kwargs: Any) -> int:
        """流式下载到文件，返回写入字节数（调用方负责 .part → replace）。"""
        target = Path(file_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        response = self.get(url, stream=True, **kwargs)
        written = 0
        try:
            with target.open("wb") as handle:
                for chunk in response.iter_content(chunk_size=64 * 1024):
                    if not chunk:
                        continue
                    handle.write(chunk)
                    written += len(chunk)
        finally:
            response.close()
        return written

    def close(self) -> None:
        """关闭当前线程的 Session。"""
        session = getattr(self._local, "session", None)
        if session is not None:
            session.close()
            self._local.session = None
