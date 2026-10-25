"""脚本沙箱：语法校验（返回行号列号）+ 受限执行（60s 超时 / 异常带 traceback）。

信任边界（PRD Q-08）：本机可信用户，仅做超时与异常捕获，**不做进程级隔离**；
通过受限 ``__builtins__`` 与模块白名单降低误用风险。
"""

from __future__ import annotations

import ast
import importlib
import inspect
import threading
from dataclasses import dataclass
from typing import Any, Final

from app.common.errors import BizError, ErrCode
from app.common.logger import format_exc, get_logger
from app.config import DEFAULTS
from app.downloader.http_client import HttpClient

logger = get_logger(__name__)

#: 允许脚本导入的模块白名单
ALLOWED_MODULES: Final[frozenset[str]] = frozenset(
    {
        "re",
        "json",
        "math",
        "time",
        "datetime",
        "hashlib",
        "random",
        "string",
        "textwrap",
        "urllib.parse",
        "html",
        "base64",
    }
)


@dataclass
class SyntaxResult:
    """语法校验结果。"""

    valid: bool = True
    line: int | None = None
    column: int | None = None
    message: str = "语法正确"


class ScriptSandbox:
    """自定义解析脚本的校验与执行。"""

    def __init__(self, http: HttpClient | None = None, timeout: int | None = None) -> None:
        self.http: HttpClient = http or HttpClient()
        self.timeout: int = int(DEFAULTS["script.timeout_s"] if timeout is None else timeout)

    # ------------------------------------------------------------------
    # 校验
    # ------------------------------------------------------------------
    def validate(self, script: str, entry: str = "parse") -> SyntaxResult:
        """语法校验 + 入口函数存在性检查。"""
        text = str(script or "")
        if not text.strip():
            return SyntaxResult(valid=False, message="脚本内容为空")
        try:
            tree = ast.parse(text, filename="<script>")
        except SyntaxError as exc:
            return SyntaxResult(
                valid=False,
                line=exc.lineno,
                column=exc.offset,
                message=f"语法错误：{exc.msg}",
            )
        except ValueError as exc:  # 例如源码含空字节
            return SyntaxResult(valid=False, message=f"脚本无法解析：{exc}")
        entry_name = str(entry or "parse").strip()
        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == entry_name:
                return SyntaxResult(valid=True, message="语法正确")
        return SyntaxResult(
            valid=False,
            message=f"未找到入口函数 {entry_name}（请定义 def {entry_name}(args): ...）",
        )

    # ------------------------------------------------------------------
    # 执行
    # ------------------------------------------------------------------
    def execute(
        self,
        script: str,
        entry: str,
        args: dict[str, Any],
        timeout: int | None = None,
    ) -> dict[str, Any]:
        """在受限命名空间中执行脚本入口函数。

        Raises:
            BizError: ``4001`` 执行异常 / ``4002`` 超时。
        """
        limit = int(self.timeout if timeout is None else timeout)
        entry_name = str(entry or "parse").strip()
        namespace: dict[str, Any] = {
            "__builtins__": self._restricted_builtins(),
            "__name__": "crawlerhub_script",
        }
        try:
            code = compile(str(script or ""), "<script>", "exec")
            exec(code, namespace)  # noqa: S102 - 受控沙箱执行
        except SyntaxError as exc:
            raise BizError(
                ErrCode.SCRIPT_ERROR,
                f"脚本语法错误（第 {exc.lineno} 行）：{exc.msg}",
                retryable=False,
            ) from exc
        except Exception as exc:  # noqa: BLE001
            raise BizError(
                ErrCode.SCRIPT_ERROR,
                f"脚本初始化失败：{exc}",
                retryable=False,
                detail=format_exc(exc),
            ) from exc

        function = namespace.get(entry_name)
        if not callable(function):
            raise BizError(
                ErrCode.SCRIPT_ERROR,
                f"脚本未定义入口函数 {entry_name}",
                retryable=False,
            )

        result: dict[str, Any] = {}
        error: dict[str, BaseException] = {}

        def runner() -> None:
            try:
                result["value"] = self._invoke(function, args)
            except BaseException as exc:  # noqa: BLE001 - 需捕获全部异常交给主线程
                error["value"] = exc

        thread = threading.Thread(target=runner, name="script-sandbox", daemon=True)
        thread.start()
        thread.join(limit)
        if thread.is_alive():
            raise BizError(
                ErrCode.SCRIPT_TIMEOUT,
                f"解析脚本执行超过 {limit}s，已中断",
                retryable=False,
            )
        if "value" in error:
            exc = error["value"]
            raise BizError(
                ErrCode.SCRIPT_ERROR,
                f"解析脚本执行异常：{exc}",
                retryable=False,
                detail=format_exc(exc),
            )
        value = result.get("value")
        if not isinstance(value, dict):
            raise BizError(
                ErrCode.SCRIPT_ERROR,
                "解析脚本必须返回 dict（list 模式返回 {'items': [...]}）",
                retryable=False,
            )
        return value

    # ------------------------------------------------------------------
    # 受限运行环境
    # ------------------------------------------------------------------
    @staticmethod
    def _invoke(function: Any, args: dict[str, Any]) -> Any:
        """按入口函数签名决定传 dict 还是关键字参数。"""
        try:
            signature = inspect.signature(function)
        except (TypeError, ValueError):
            return function(args)
        params = [
            param
            for param in signature.parameters.values()
            if param.kind in (param.POSITIONAL_ONLY, param.POSITIONAL_OR_KEYWORD)
        ]
        has_var_kw = any(
            param.kind == param.VAR_KEYWORD for param in signature.parameters.values()
        )
        if len(params) == 1 and not has_var_kw:
            return function(args)
        return function(**args)

    def _restricted_builtins(self) -> dict[str, Any]:
        """受限内置函数集合（含网络/解析辅助）。"""
        from bs4 import BeautifulSoup

        def _safe_import(name: str, *args: Any, **kwargs: Any) -> Any:
            if name not in ALLOWED_MODULES:
                raise ImportError(f"沙箱不允许导入模块：{name}")
            return importlib.import_module(name)

        def http_get(url: str, **kwargs: Any) -> str:
            """抓取网页文本（带统一 UA / 超时）。"""
            return self.http.get_text(url, **kwargs)

        def http_get_json(url: str, **kwargs: Any) -> Any:
            """抓取并解析 JSON。"""
            import json as _json

            return _json.loads(self.http.get_text(url, **kwargs))

        def parse_html(markup: str) -> BeautifulSoup:
            """解析 HTML。"""
            try:
                return BeautifulSoup(markup, "lxml")
            except Exception:  # noqa: BLE001
                return BeautifulSoup(markup, "html.parser")

        def log(message: Any) -> None:
            """脚本日志（写入应用日志）。"""
            logger.info("[script] %s", message)

        return {
            "__import__": _safe_import,
            "abs": abs,
            "all": all,
            "any": any,
            "bool": bool,
            "bytes": bytes,
            "dict": dict,
            "enumerate": enumerate,
            "filter": filter,
            "float": float,
            "int": int,
            "isinstance": isinstance,
            "len": len,
            "list": list,
            "map": map,
            "max": max,
            "min": min,
            "print": log,
            "range": range,
            "repr": repr,
            "reversed": reversed,
            "round": round,
            "set": set,
            "sorted": sorted,
            "str": str,
            "sum": sum,
            "tuple": tuple,
            "zip": zip,
            "Exception": Exception,
            "ValueError": ValueError,
            "KeyError": KeyError,
            "TypeError": TypeError,
            "IndexError": IndexError,
            "RuntimeError": RuntimeError,
            "http_get": http_get,
            "http_get_json": http_get_json,
            "parse_html": parse_html,
            "log": log,
        }


__all__ = ["ALLOWED_MODULES", "ScriptSandbox", "SyntaxResult"]
