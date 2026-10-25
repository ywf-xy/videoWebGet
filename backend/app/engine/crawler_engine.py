"""全局爬虫引擎（D-01）：线程池注册表 + 可动态调整的全局并发限制器。

``GlobalLimiter`` 说明：``threading.BoundedSemaphore`` 无法在运行期改容量，
而 PRD 要求「修改 max_threads 后新取任务立即生效」，因此用 ``Condition`` 实现了
等价的计数信号量语义（acquire/release/set_limit），行为与 BoundedSemaphore 一致。
"""

from __future__ import annotations

import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError

from app.common.errors import BizError, ErrCode
from app.common.logger import get_logger
from app.common.timeutil import now_iso
from app.config import DEFAULTS, E
from app.db.base import session_scope
from app.db.models import Artifact, CrawlBatch, CrawlTask, TaskLog
from app.downloader.ffmpeg import get_ffmpeg
from app.engine.batch_runner import BatchRunner
from app.engine.pause_control import pause_controller
from app.services.setting_service import get_runtime

logger = get_logger(__name__)


class GlobalLimiter:
    """可动态调整上限的计数信号量（全局任务并发上限）。"""

    def __init__(self, limit: int = int(DEFAULTS["max_threads"])) -> None:
        self._condition = threading.Condition()
        self._limit = max(1, int(limit))
        self._active = 0

    @property
    def limit(self) -> int:
        """当前上限。"""
        with self._condition:
            return self._limit

    @property
    def active(self) -> int:
        """当前占用数。"""
        with self._condition:
            return self._active

    def set_limit(self, limit: int) -> None:
        """调整上限（对已运行任务无影响，只影响后续 acquire）。"""
        with self._condition:
            self._limit = max(1, min(int(DEFAULTS["max_threads_limit"]), int(limit)))
            self._condition.notify_all()

    def acquire(self, timeout: float | None = None) -> bool:
        """获取令牌（超时返回 False）。"""
        with self._condition:
            if timeout is None:
                while self._active >= self._limit:
                    self._condition.wait()
                self._active += 1
                return True
            remaining = max(0.0, float(timeout))
            while self._active >= self._limit:
                if remaining <= 0:
                    return False
                self._condition.wait(remaining)
                remaining -= 0.05
            self._active += 1
            return True

    def release(self) -> None:
        """归还令牌。"""
        with self._condition:
            if self._active > 0:
                self._active -= 1
            self._condition.notify()


@dataclass(frozen=True)
class ThreadStat:
    """线程占用快照。"""

    active: int
    max: int


class CrawlerEngine:
    """进程内全局引擎单例：管理批次执行体与全局并发。"""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._runners: dict[int, BatchRunner] = {}
        self._pools: dict[int, ThreadPoolExecutor] = {}
        self.limiter = GlobalLimiter(int(DEFAULTS["max_threads"]))
        self._started = False

    # ------------------------------------------------------------------
    # 生命周期
    # ------------------------------------------------------------------
    def start(self) -> None:
        """启动：复位孤儿状态 + 同步并发上限 + 探测 ffmpeg（幂等）。"""
        with self._lock:
            if self._started:
                return
            self._started = True
        self._recover_orphans()
        with session_scope() as db:
            runtime = get_runtime(db)
        self.limiter.set_limit(runtime.max_threads)
        get_ffmpeg().detect()
        logger.info("爬虫引擎已启动，全局并发上限 %s", runtime.max_threads)

    def _recover_orphans(self) -> None:
        """NFR-05：进程重启后把孤儿 running 任务复位 pending，running 批次转暂停告警。

        同时清理「僵尸产物」：重启后已无任何 running 任务，所有仍为 ``processing`` 的
        产物都属于被中断的尝试，统一标记 ``failed``，避免产物页永久停在「处理中」。
        """
        stamp = now_iso()
        with session_scope() as db:
            tasks = db.execute(
                update(CrawlTask)
                .where(CrawlTask.status == E.TASK_RUNNING)
                .values(status=E.TASK_PENDING, started_at=None, updated_at=stamp)
            )
            task_count = int(tasks.rowcount or 0)
            batches = db.execute(
                select(CrawlBatch.id).where(CrawlBatch.status == E.BATCH_RUNNING)
            ).all()
            for (batch_id,) in batches:
                db.execute(
                    update(CrawlBatch)
                    .where(CrawlBatch.id == int(batch_id))
                    .values(
                        status=E.BATCH_PAUSED_WITH_WARNING,
                        updated_at=stamp,
                    )
                )
                db.add(
                    TaskLog(
                        batch_id=int(batch_id),
                        task_id=None,
                        level=E.LOG_WARN,
                        message="进程重启导致批次中断，已置为「暂停(有残留)」，请手动恢复",
                        created_at=stamp,
                    )
                )
            # 僵尸产物复位：重启后已无 running 任务，仍为 processing 的记录都属于
            # 被中断的尝试。有落盘文件的按 success 收口（文件确实在），否则 failed，
            # 避免产物页永久停在「处理中」（BUG-03）。
            zombie_rows = db.execute(
                select(Artifact.id, Artifact.path).where(
                    Artifact.status == E.ARTIFACT_PROCESSING,
                    ~Artifact.task_id.in_(
                        select(CrawlTask.id).where(CrawlTask.status == E.TASK_RUNNING)
                    ),
                )
            ).all()
            recovered_success = 0
            recovered_failed = 0
            for artifact_id, path in zombie_rows:
                exists = bool(path) and Path(str(path)).exists()
                db.execute(
                    update(Artifact)
                    .where(Artifact.id == int(artifact_id))
                    .values(
                        status=E.ARTIFACT_SUCCESS if exists else E.ARTIFACT_FAILED,
                        error_msg=(
                            None
                            if exists
                            else "服务重启导致任务中断，已标记为失败（重试会复用该记录）"
                        ),
                        updated_at=stamp,
                    )
                )
                if exists:
                    recovered_success += 1
                else:
                    recovered_failed += 1
            zombie_count = recovered_success + recovered_failed
            if task_count or batches or zombie_count:
                logger.warning(
                    "启动复位：%s 个 running 任务→pending，%s 个 running 批次→paused_with_warning，"
                    "%s 条僵尸产物已复位（success=%s / failed=%s）",
                    task_count,
                    len(batches),
                    zombie_count,
                    recovered_success,
                    recovered_failed,
                )

    def shutdown(self) -> None:
        """停止引擎：请求暂停所有批次并关闭线程池。"""
        with self._lock:
            batch_ids = list(self._pools.keys())
            pools = list(self._pools.values())
            self._pools.clear()
            self._runners.clear()
        for batch_id in batch_ids:
            pause_controller.request(batch_id)
        for pool in pools:
            pool.shutdown(wait=False, cancel_futures=True)
        logger.info("爬虫引擎已停止（关闭 %s 个批次池）", len(pools))

    # ------------------------------------------------------------------
    # 批次提交
    # ------------------------------------------------------------------
    def submit_batch(self, batch_id: int, threads: int | None = None) -> bool:
        """提交批次执行（幂等：同 batch_id 已有运行体时不重复起线程）。"""
        batch_key = int(batch_id)
        with self._lock:
            runner = self._runners.get(batch_key)
            if runner is not None and runner.running:
                logger.info("批次 %s 已在运行，忽略重复提交", batch_key)
                return False
            worker_count = max(1, int(threads or DEFAULTS["max_threads"]))
            pause_controller.register(batch_key)
            new_runner = BatchRunner(batch_key, worker_count, self)
            pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix=f"runner{batch_key}")
            new_runner.pool = pool
            self._runners[batch_key] = new_runner
            self._pools[batch_key] = pool
            pool.submit(new_runner.run)
        logger.info("批次 %s 已提交（线程数 %s）", batch_key, worker_count)
        return True

    def on_runner_exit(self, batch_id: int, runner: BatchRunner | None = None) -> None:
        """执行体退出回调：只回收自己那一份注册（避免误删新执行体）。"""
        batch_key = int(batch_id)
        pool_to_close = getattr(runner, "pool", None)
        with self._lock:
            if runner is None or self._runners.get(batch_key) is runner:
                self._runners.pop(batch_key, None)
                if pool_to_close is not None and self._pools.get(batch_key) is pool_to_close:
                    self._pools.pop(batch_key, None)
        if pool_to_close is not None:
            pool_to_close.shutdown(wait=False, cancel_futures=True)

    def wait_runner_exit(self, batch_id: int, timeout: float = 30.0) -> bool:
        """等待批次执行体完全退出（暂停收尾保护），返回是否已退出。"""
        deadline = time.monotonic() + max(0.0, float(timeout))
        while time.monotonic() < deadline:
            with self._lock:
                runner = self._runners.get(int(batch_id))
                finished = runner is None or not runner.running
            if finished:
                return True
            time.sleep(0.05)
        return False

    # ------------------------------------------------------------------
    # 暂停 / 恢复
    # ------------------------------------------------------------------
    def pause_batch(self, batch_id: int) -> bool:
        """登记暂停请求（不杀线程）。"""
        pause_controller.request(int(batch_id))
        logger.info("批次 %s 已登记暂停", batch_id)
        return True

    def resume_batch(self, batch_id: int) -> bool:
        """清除暂停标记。"""
        pause_controller.clear(int(batch_id))
        logger.info("批次 %s 已清除暂停标记", batch_id)
        return True

    # ------------------------------------------------------------------
    # 重试
    # ------------------------------------------------------------------
    def retry_tasks(self, task_ids: list[int]) -> int:
        """批量重试失败任务（复用原 task 记录，不清零 attempt_count）。"""
        submitted = 0
        batch_threads: dict[int, int] = {}
        stamp = now_iso()
        try:
            with session_scope() as db:
                # 先收集「需要复活」的批次，并做 single-flight 预检：
                # 若同数据源已有另一个活跃批次，复活旧批次会违反 uq_batch_active，
                # 语义上也不允许（PRD P0-15③），此处直接拒绝并回滚全部变更。
                revive: set[int] = set()
                for raw_id in task_ids:
                    task = db.get(CrawlTask, int(raw_id))
                    if task is None or task.status != E.TASK_FAILED:
                        continue
                    revive.add(int(task.batch_id))

                for batch_id in list(revive):
                    batch = db.get(CrawlBatch, batch_id)
                    if batch is None:
                        revive.discard(batch_id)
                        continue
                    if batch.status in E.BATCH_TERMINAL_STATUSES:
                        conflict = db.execute(
                            select(CrawlBatch.id)
                            .where(
                                CrawlBatch.data_source_id == int(batch.data_source_id),
                                CrawlBatch.id != int(batch.id),
                                CrawlBatch.status.in_(E.BATCH_BUSY_STATUSES),
                            )
                            .limit(1)
                        ).first()
                        if conflict is not None:
                            raise BizError(
                                ErrCode.BATCH_SINGLE_FLIGHT,
                                "该数据源已有其他运行中的批次，请先暂停或等待完成后再重试历史批次",
                            )
                        batch.status = E.BATCH_RUNNING
                        batch.updated_at = stamp

                for raw_id in task_ids:
                    task = db.get(CrawlTask, int(raw_id))
                    if task is None or task.status != E.TASK_FAILED:
                        continue
                    task.status = E.TASK_PENDING
                    task.error_code = None
                    task.error_msg = None
                    task.started_at = None
                    task.finished_at = None
                    task.duration_ms = 0
                    task.updated_at = stamp
                    submitted += 1
                    batch_threads.setdefault(int(task.batch_id), 0)

                for batch_id in list(batch_threads):
                    batch = db.get(CrawlBatch, batch_id)
                    if batch is None:
                        batch_threads.pop(batch_id, None)
                        continue
                    batch_threads[batch_id] = int(batch.threads or DEFAULTS["max_threads"])
                runtime = get_runtime(db)
                for batch_id, threads in batch_threads.items():
                    batch_threads[batch_id] = min(threads, runtime.max_threads)
        except IntegrityError as exc:
            # 极端并发（重试与新建同时发生）时由唯一索引兜底，统一转 3001
            logger.info("重试与新建批次并发冲突，按 single-flight 拒绝：%s", exc)
            raise BizError(ErrCode.BATCH_SINGLE_FLIGHT, "该数据源已有运行中的批次，请稍后重试") from exc
        for batch_id, threads in batch_threads.items():
            self.submit_batch(batch_id, threads)
        logger.info("重试提交 %s 个任务，涉及 %s 个批次", submitted, len(batch_threads))
        return submitted

    # ------------------------------------------------------------------
    # 指标
    # ------------------------------------------------------------------
    def active_count(self) -> int:
        """当前活跃任务数（受全局上限约束）。"""
        return int(self.limiter.active)

    def thread_stat(self) -> ThreadStat:
        """线程占用快照。"""
        return ThreadStat(active=self.active_count(), max=self.limiter.limit)

    def sync_limit(self) -> int:
        """从设置表同步全局上限（设置保存后调用）。"""
        with session_scope() as db:
            runtime = get_runtime(db)
        self.limiter.set_limit(runtime.max_threads)
        return runtime.max_threads

    def is_running(self, batch_id: int) -> bool:
        """批次是否仍有运行体。"""
        with self._lock:
            runner = self._runners.get(int(batch_id))
            return bool(runner is not None and runner.running)


#: 进程级单例
crawler_engine = CrawlerEngine()


def get_engine() -> CrawlerEngine:
    """获取全局引擎。"""
    return crawler_engine


__all__ = ["CrawlerEngine", "GlobalLimiter", "ThreadStat", "crawler_engine", "get_engine"]
