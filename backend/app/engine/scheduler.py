"""任务调度与执行：领取任务、按类型下载/落盘、重试退避、暂停回退、结果入库。

关键语义（PRD 9.4 / 9.5）：
- 领取任务用「条件 UPDATE」做原子比较交换，避免多线程重复领取；
- 暂停：不杀线程，``PauseRequested`` 在原子步骤结束后抛出 → 任务回退 ``pending``（保留 step_done）；
- 重试：仅 failed 可重试，``attempt_count`` 受 ``max_attempts`` 约束，
  退避 ``base_interval × 2^(n-1)``，上限 30s；404/403/脚本错误不重试；
- DB 会话不跨网络 IO：先取快照 → 执行 → 短事务写回。
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import delete, select, update
from sqlalchemy.orm import Session

from app.common.disk import ensure_free_space
from app.common.errors import BizError, ErrCode, PauseRequested
from app.common.fingerprint import item_fingerprint
from app.common.logger import error_message, format_exc, get_logger
from app.common.path_builder import PathBuilder
from app.common.timeutil import elapsed_ms, now_iso
from app.config import DEFAULTS, E
from app.db.base import session_scope
from app.db.models import Artifact, CrawlBatch, CrawlTask, DataSource, TaskLog, TaskResult
from app.downloader.http_client import HttpClient
from app.downloader.image_downloader import ImageDownloader
from app.downloader.m3u8_downloader import DegradedArtifactError, M3U8Downloader
from app.downloader.text_writer import TextWriter
from app.engine.pause_control import PauseController, pause_controller
from app.parsers.base import ListItem
from app.parsers.registry import build_parser
from app.services.setting_service import RuntimeSettings, get_runtime

logger = get_logger(__name__)


@dataclass
class TaskOutcome:
    """单次任务执行的产出。"""

    artifact_type: str
    path: str
    size: int = 0
    file_count: int = 1
    extra: dict[str, Any] = field(default_factory=dict)
    fingerprint: str | None = None


class TaskScheduler:
    """批次内任务调度器（每个批次一个实例，可被多个线程共享）。"""

    def __init__(
        self,
        batch_id: int,
        export_format: str | None = None,
        pause: PauseController | None = None,
    ) -> None:
        self.batch_id: int = int(batch_id)
        self.export_format: str | None = export_format
        self.pause: PauseController = pause or pause_controller
        self.base_interval: int = int(DEFAULTS["retry.base_interval"])
        self.max_attempts: int = int(DEFAULTS["retry.max_attempts"])

    # ------------------------------------------------------------------
    # 领取
    # ------------------------------------------------------------------
    def take_next(self) -> int | None:
        """领取一个 pending 任务并原子置为 running，返回 task_id（无任务返回 None）。"""
        stamp = now_iso()
        with session_scope() as db:
            row = db.execute(
                select(CrawlTask.id)
                .where(
                    CrawlTask.batch_id == self.batch_id,
                    CrawlTask.status == E.TASK_PENDING,
                )
                .order_by(CrawlTask.seq_no.asc())
                .limit(1)
            ).first()
            if row is None:
                return None
            task_id = int(row[0])
            result = db.execute(
                update(CrawlTask)
                .where(CrawlTask.id == task_id, CrawlTask.status == E.TASK_PENDING)
                .values(
                    status=E.TASK_RUNNING,
                    attempt_count=CrawlTask.attempt_count + 1,
                    started_at=stamp,
                    updated_at=stamp,
                )
            )
            if int(result.rowcount or 0) != 1:
                return None  # 竞争失败，交由下一轮重试
            return task_id

    # ------------------------------------------------------------------
    # 执行
    # ------------------------------------------------------------------
    def run_task(self, task_id: int) -> None:
        """执行单个任务（含重试循环），保证任务最终落在 success / failed / pending。"""
        context = self._load_context(task_id)
        if context is None:
            logger.warning("任务 %s 不存在，跳过", task_id)
            return
        task, ds, runtime = context
        self.base_interval = runtime.base_interval
        self.max_attempts = runtime.max_attempts
        artifact_id = self._create_artifact(task, ds)
        started_at = str(task.started_at or now_iso())
        attempt = int(task.attempt_count or 1)

        while True:
            try:
                outcome = self._execute_once(task, ds, runtime, started_at)
            except PauseRequested:
                self._revert_pending(task_id, started_at)
                return
            except DegradedArtifactError as exc:
                # ffmpeg 缺失：分片已下载并产出 .ts，仍按 PRD 标 failed(3003)
                self._finish_failed(
                    task, artifact_id, exc, started_at, path=exc.artifact_path, size=exc.file_size
                )
                return
            except BizError as exc:
                if self.should_retry(exc, attempt):
                    self._log(
                        E.LOG_WARN,
                        f"任务失败将重试（第 {attempt} 次）：{exc.message}",
                        task_id,
                    )
                    attempt += 1
                    self._bump_attempt(task_id)
                    self.backoff_sleep(attempt)
                    continue
                self._finish_failed(task, artifact_id, exc, started_at)
                return
            except Exception as exc:  # noqa: BLE001 - 兜底，避免线程静默死亡
                wrapped = BizError(
                    ErrCode.INTERNAL,
                    f"任务执行异常：{exc}",
                    retryable=False,
                    detail=format_exc(exc),
                )
                self._finish_failed(task, artifact_id, wrapped, started_at)
                return
            else:
                self._finish_success(task, ds, outcome, artifact_id, started_at)
                return

    # ------------------------------------------------------------------
    # 单次执行
    # ------------------------------------------------------------------
    def _execute_once(
        self,
        task: CrawlTask,
        ds: DataSource,
        runtime: RuntimeSettings,
        started_at: str,
    ) -> TaskOutcome:
        """按数据源类型执行一次（不含重试）。"""
        ensure_free_space(runtime.output_root)
        builder = PathBuilder(runtime.output_root)
        http = HttpClient()
        parser = build_parser(ds, http)
        item = ListItem(
            title=task.title,
            url=task.source_url,
            seq_no=int(task.seq_no or 0),
            date=(task.payload or {}).get("date"),
            payload=dict(task.payload or {}),
        )

        if ds.type == E.TYPE_VIDEO:
            return self._run_video(task, ds, parser, item, builder, runtime, http, started_at)
        if ds.type == E.TYPE_TEXT:
            return self._run_text(task, ds, parser, item, builder)
        return self._run_image(task, ds, parser, item, builder, runtime, http, started_at)

    # ---- 视频 ----
    def _run_video(
        self,
        task: CrawlTask,
        ds: DataSource,
        parser: Any,
        item: ListItem,
        builder: PathBuilder,
        runtime: RuntimeSettings,
        http: HttpClient,
        started_at: str,
    ) -> TaskOutcome:
        """视频：解析 m3u8 → 分片下载 → 转 MP4。"""
        detail = parser.parse_detail(item)
        if not detail.video_url:
            raise BizError(
                ErrCode.M3U8_PARSE,
                "未解析到 m3u8 地址",
                retryable=False,
                detail=f"url={item.url}",
            )
        output_path = builder.build_video(ds, task.title)
        ts_path = builder.build_video_ts(ds, task.title)
        work_dir = builder.temp_dir(task.id)
        downloader = M3U8Downloader(
            http=http, max_segment_workers=min(int(DEFAULTS["segment.concurrency"]), runtime.max_threads)
        )
        result = downloader.download(
            detail.video_url,
            task.id,
            work_dir,
            output_path=output_path,
            ts_fallback_path=ts_path,
            checkpoint=lambda: self.pause.checkpoint(self.batch_id),
            on_step=lambda done, total: self._on_step(task.id, done, total, started_at),
        )
        builder.cleanup_temp(task.id)
        return TaskOutcome(
            artifact_type=E.ARTIFACT_VIDEO,
            path=result.path,
            size=result.size,
            file_count=1,
            extra={
                "duration_s": round(float(result.duration_s), 3),
                "segment_count": result.segment_count,
                "video_url": detail.video_url,
            },
            fingerprint=item_fingerprint(item.url, item.title),
        )

    # ---- 文字 ----
    def _run_text(
        self,
        task: CrawlTask,
        ds: DataSource,
        parser: Any,
        item: ListItem,
        builder: PathBuilder,
    ) -> TaskOutcome:
        """文字：正文落 TXT（必须成功），按导出格式追加 PDF（失败仅 WARN）。"""
        detail = parser.parse_detail(item)
        content = detail.content or ""
        title = detail.title or task.title
        if not content.strip():
            raise BizError(
                ErrCode.SCRIPT_ERROR,
                "正文为空，可能是解析选择器未命中",
                retryable=False,
                detail=f"url={item.url}",
            )

        payload = dict(task.payload or {})
        book = str(payload.get("book") or payload.get("novel") or "") or None
        novel = bool(ds.is_novel)
        txt_path = builder.build_text(
            ds, title=book or title, chapter=title, fmt=E.FORMAT_TXT, is_novel=novel, book=book
        )
        writer = TextWriter()
        size = writer.write_txt(txt_path, title, content)
        word_count = len(content)

        artifact_type = E.ARTIFACT_TEXT
        final_path = txt_path
        final_size = size
        extra: dict[str, Any] = {"word_count": word_count, "format": E.FORMAT_TXT}

        if (self.export_format or E.FORMAT_TXT) == E.FORMAT_PDF:
            pdf_path = builder.build_text(
                ds, title=book or title, chapter=title, fmt=E.FORMAT_PDF, is_novel=novel, book=book
            )
            try:
                final_size = writer.write_pdf(pdf_path, title, content)
            except Exception as exc:  # noqa: BLE001 - PDF 失败不影响任务成功
                self._log(
                    E.LOG_WARN,
                    f"PDF 生成失败，已保留 TXT：{exc}",
                    task.id,
                )
                logger.warning("任务 %s PDF 生成失败：%s", task.id, exc)
            else:
                artifact_type = E.ARTIFACT_PDF
                final_path = pdf_path
                extra["format"] = E.FORMAT_PDF
                extra["txt_path"] = txt_path

        return TaskOutcome(
            artifact_type=artifact_type,
            path=final_path,
            size=final_size,
            file_count=1,
            extra=extra,
            fingerprint=item_fingerprint(item.url, item.title),
        )

    # ---- 图片 ----
    def _run_image(
        self,
        task: CrawlTask,
        ds: DataSource,
        parser: Any,
        item: ListItem,
        builder: PathBuilder,
        runtime: RuntimeSettings,
        http: HttpClient,
        started_at: str,
    ) -> TaskOutcome:
        """图片：按列表顺序下载整组图片，单图失败不阻断。"""
        detail = parser.parse_detail(item)
        images = list(detail.images or [])
        if not images:
            raise BizError(ErrCode.SCRIPT_ERROR, "图集未解析到图片", retryable=False)
        name = detail.title or task.title
        out_dir = builder.build_image_dir(ds, name)
        downloader = ImageDownloader(http=http)
        result = downloader.download_set(
            images,
            out_dir,
            on_step=lambda done, total: self._on_step(task.id, done, total, started_at),
            checkpoint=lambda: self.pause.checkpoint(self.batch_id),
        )
        if result.count == 0:
            raise BizError(
                ErrCode.HTTP_ERROR,
                "图集内所有图片下载失败",
                retryable=True,
                detail=f"failed={len(result.failed)}",
            )
        if result.failed:
            self._log(
                E.LOG_WARN,
                f"{len(result.failed)}/{len(images)} 张图片下载失败（已跳过）",
                task.id,
            )
        return TaskOutcome(
            artifact_type=E.ARTIFACT_IMAGE,
            path=out_dir,
            size=result.size,
            file_count=result.count,
            extra={"image_count": result.count, "image_total": len(images)},
            fingerprint=item_fingerprint(item.url, item.title),
        )

    # ------------------------------------------------------------------
    # 重试
    # ------------------------------------------------------------------
    def should_retry(self, err: BizError, attempt: int) -> bool:
        """是否继续自动重试：可重试错误 + 未达上限 + 批次未被暂停。"""
        if self.pause.is_paused(self.batch_id):
            return False
        if not err.retryable:
            return False
        return int(attempt) < int(self.max_attempts)

    def backoff_sleep(self, attempt: int) -> None:
        """退避 ``base_interval × 2^(attempt-1)``，上限 30s。"""
        cap = int(DEFAULTS["retry.backoff_cap_s"])
        seconds = min(cap, int(self.base_interval) * (2 ** max(0, int(attempt) - 1)))
        logger.info("重试退避 %ss（第 %s 次）", seconds, attempt)
        time.sleep(seconds)

    # ------------------------------------------------------------------
    # 上下文加载
    # ------------------------------------------------------------------
    def _load_context(self, task_id: int) -> tuple[CrawlTask, DataSource, RuntimeSettings] | None:
        """加载任务 / 数据源快照与运行期配置（离线对象，脱离会话使用）。"""
        with session_scope() as db:
            task = db.get(CrawlTask, int(task_id))
            if task is None:
                return None
            ds = db.get(DataSource, int(task.data_source_id))
            if ds is None:
                return None
            runtime = get_runtime(db)
            # 触发属性加载，确保脱离会话后仍可读取
            _ = (task.title, task.payload, ds.name, ds.config_json, ds.script, ds.is_novel)
            db.expunge(task)
            db.expunge(ds)
        return task, ds, runtime

    # ------------------------------------------------------------------
    # 状态写回
    # ------------------------------------------------------------------
    def _on_step(self, task_id: int, done: int, total: int, _started_at: str) -> None:
        """原子步骤进度落库（暂停/崩溃后 step_done 可用）。"""
        with session_scope() as db:
            db.execute(
                update(CrawlTask)
                .where(CrawlTask.id == int(task_id))
                .values(
                    step_done=int(done),
                    step_total=max(1, int(total)),
                    updated_at=now_iso(),
                )
            )

    def _bump_attempt(self, task_id: int) -> None:
        """自动重试时累加 attempt_count。"""
        with session_scope() as db:
            db.execute(
                update(CrawlTask)
                .where(CrawlTask.id == int(task_id))
                .values(attempt_count=CrawlTask.attempt_count + 1, updated_at=now_iso())
            )

    def _revert_pending(self, task_id: int, started_at: str) -> None:
        """暂停：任务回退 pending，保留 step_done 供断点续传。"""
        with session_scope() as db:
            db.execute(
                update(CrawlTask)
                .where(CrawlTask.id == int(task_id))
                .values(
                    status=E.TASK_PENDING,
                    started_at=None,
                    duration_ms=elapsed_ms(started_at),
                    updated_at=now_iso(),
                )
            )
        self._log(E.LOG_INFO, "已暂停，任务回退待执行", task_id)
        logger.info("任务 %s 因暂停回退为 pending", task_id)

    def safe_fail(self, task_id: int, exc: BaseException) -> None:
        """兜底：执行体自身崩溃时把仍处于 running 的任务置为 failed。"""
        finished = now_iso()
        detail = format_exc(exc)
        with session_scope() as db:
            task = db.get(CrawlTask, int(task_id))
            if task is None or task.status != E.TASK_RUNNING:
                return
            task.status = E.TASK_FAILED
            task.error_code = str(int(ErrCode.INTERNAL))
            task.error_msg = f"任务执行异常：{exc}"[:500]
            task.finished_at = finished
            task.updated_at = finished
            batch = db.get(CrawlBatch, self.batch_id)
            if batch is not None:
                batch.failed_tasks = int(batch.failed_tasks or 0) + 1
                batch.updated_at = finished
        self._log(
            E.LOG_ERROR,
            error_message(ErrCode.INTERNAL, f"任务执行异常：{exc}", detail),
            task_id,
        )
        logger.error("任务 %s 兜底置为失败：%s", task_id, exc)

    def _create_artifact(self, task: CrawlTask, ds: DataSource) -> int:
        """登记「处理中」产物（P1-05）：按 ``(task_id, name)`` **幂等 upsert**。

        重跑（暂停恢复 / 失败重试 / 重新下载 / 重启后恢复）必须复用同一行并重置为
        processing，否则会累积 path 为空、size 为 0 的僵尸「处理中」产物（BUG-03）。
        """
        artifact_type = {
            E.TYPE_VIDEO: E.ARTIFACT_VIDEO,
            E.TYPE_IMAGE: E.ARTIFACT_IMAGE,
        }.get(ds.type, E.ARTIFACT_PDF if (self.export_format == E.FORMAT_PDF) else E.ARTIFACT_TEXT)
        artifact_name = str(task.title)
        stamp = now_iso()
        with session_scope() as db:
            existing = db.execute(
                select(Artifact)
                .where(
                    Artifact.task_id == int(task.id),
                    Artifact.name == artifact_name,
                )
                .order_by(Artifact.id.asc())
                .limit(1)
            ).scalar_one_or_none()

            if existing is not None:
                # 顺带清理同一 (task_id, name) 下历史遗留的重复行
                db.execute(
                    delete(Artifact).where(
                        Artifact.task_id == int(task.id),
                        Artifact.name == artifact_name,
                        Artifact.id != int(existing.id),
                    )
                )
                existing.task_result_id = None
                existing.data_source_id = int(ds.id)
                existing.data_source_name = str(ds.name)
                existing.type = artifact_type
                existing.category = ds.category
                existing.path = ""
                existing.size = 0
                existing.status = E.ARTIFACT_PROCESSING
                existing.error_msg = None
                existing.updated_at = stamp
                return int(existing.id)

            artifact = Artifact(
                task_id=int(task.id),
                task_result_id=None,
                data_source_id=int(ds.id),
                data_source_name=str(ds.name),
                type=artifact_type,
                name=artifact_name,
                category=ds.category,
                path="",
                size=0,
                status=E.ARTIFACT_PROCESSING,
            )
            db.add(artifact)
            db.flush()
            return int(artifact.id)

    def _finish_success(
        self,
        task: CrawlTask,
        ds: DataSource,
        outcome: TaskOutcome,
        artifact_id: int,
        started_at: str,
    ) -> None:
        """成功：写 task_result（upsert）+ 产物 + 计数 + 数据源累计。"""
        finished = now_iso()
        duration = elapsed_ms(started_at, finished)
        with session_scope() as db:
            db.execute(
                update(CrawlTask)
                .where(CrawlTask.id == int(task.id))
                .values(
                    status=E.TASK_SUCCESS,
                    step_done=CrawlTask.step_total,
                    error_code=None,
                    error_msg=None,
                    duration_ms=duration,
                    finished_at=finished,
                    updated_at=finished,
                )
            )
            # 重试覆盖旧结果（task_id 唯一）
            db.execute(delete(TaskResult).where(TaskResult.task_id == int(task.id)))
            result = TaskResult(
                task_id=int(task.id),
                artifact_type=outcome.artifact_type,
                output_path=outcome.path,
                file_size=int(outcome.size),
                file_count=int(outcome.file_count),
                fingerprint=outcome.fingerprint,
                extra=dict(outcome.extra or {}),
                created_at=finished,
            )
            db.add(result)
            db.flush()
            db.execute(
                update(Artifact)
                .where(Artifact.id == int(artifact_id))
                .values(
                    task_result_id=int(result.id),
                    # 以实际落盘类型为准：PDF 生成失败降级 TXT 时这里会回写 text（BUG-01）
                    type=outcome.artifact_type,
                    path=outcome.path,
                    size=int(outcome.size),
                    status=E.ARTIFACT_SUCCESS,
                    error_msg=None,
                    updated_at=finished,
                )
            )
            db.execute(
                update(CrawlBatch)
                .where(CrawlBatch.id == int(self.batch_id))
                .values(done_tasks=CrawlBatch.done_tasks + 1, updated_at=finished)
            )
            db.execute(
                update(DataSource)
                .where(DataSource.id == int(ds.id))
                .values(
                    total_items=DataSource.total_items + 1,
                    last_success_at=finished,
                    updated_at=finished,
                )
            )
        self._log(E.LOG_INFO, f"任务成功：{outcome.path}", task.id)
        logger.info("任务 %s 成功：%s（%s 字节）", task.id, outcome.path, outcome.size)

    def _finish_failed(
        self,
        task: CrawlTask,
        artifact_id: int,
        err: BizError,
        started_at: str,
        *,
        path: str | None = None,
        size: int = 0,
    ) -> None:
        """失败：写 error_code/error_msg、产物失败态、计数、ERROR 日志（含 traceback）。"""
        finished = now_iso()
        duration = elapsed_ms(started_at, finished)
        with session_scope() as db:
            db.execute(
                update(CrawlTask)
                .where(CrawlTask.id == int(task.id))
                .values(
                    status=E.TASK_FAILED,
                    error_code=str(err.code),
                    error_msg=str(err.message)[:500],
                    duration_ms=duration,
                    finished_at=finished,
                    updated_at=finished,
                )
            )
            values: dict[str, Any] = {
                "status": E.ARTIFACT_FAILED,
                "error_msg": str(err.message)[:500],
                "updated_at": finished,
            }
            if path:
                values["path"] = path
                values["size"] = int(size)
            db.execute(update(Artifact).where(Artifact.id == int(artifact_id)).values(**values))
            db.execute(
                update(CrawlBatch)
                .where(CrawlBatch.id == int(self.batch_id))
                .values(failed_tasks=CrawlBatch.failed_tasks + 1, updated_at=finished)
            )
        self._log(
            E.LOG_ERROR,
            error_message(err.code, err.message, err.detail),
            task.id,
        )
        logger.warning("任务 %s 失败：[%s] %s", task.id, err.code, err.message)

    # ------------------------------------------------------------------
    # 日志
    # ------------------------------------------------------------------
    def _log(self, level: str, message: str, task_id: int | None = None) -> None:
        """写 task_log（用户可读业务日志，不含调试栈）。"""
        with session_scope() as db:
            db.add(
                TaskLog(
                    batch_id=self.batch_id,
                    task_id=None if task_id is None else int(task_id),
                    level=level,
                    message=str(message)[:4000],
                    created_at=now_iso(),
                )
            )


def log_batch(db: Session, batch_id: int, level: str, message: str) -> None:
    """批次级日志（task_id=NULL），供 runner / service 复用。"""
    db.add(
        TaskLog(
            batch_id=int(batch_id),
            task_id=None,
            level=level,
            message=str(message)[:4000],
            created_at=now_iso(),
        )
    )


__all__ = ["TaskOutcome", "TaskScheduler", "log_batch"]
