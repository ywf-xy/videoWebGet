"""批次执行器：阶段一解析建任务 → 阶段二线程池执行 → 终结与游标推进。

并发模型：
- 每批次一个 ``ThreadPoolExecutor``（线程数 = 批次申请线程数）；
- 全局并发由 ``CrawlerEngine.limiter`` 约束：提交任务前先拿令牌，实际并发
  = ``min(batch.threads, 全局剩余令牌)``，因此两个批次不会突破 ``max_threads``；
- 暂停时主循环停止领取新任务，运行中任务在原子步骤结束后回退 pending。
"""

from __future__ import annotations

import json
import traceback
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from typing import Any

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.common.errors import BizError, ErrCode
from app.common.logger import error_message, format_exc, get_logger
from app.common.timeutil import now_iso
from app.config import DEFAULTS, E
from app.db.base import session_scope
from app.db.models import CrawlBatch, CrawlTask, DataSource, TaskLog, TaskResult
from app.engine.pause_control import pause_controller
from app.engine.scheduler import TaskScheduler, log_batch
from app.engine.strategy import StrategyResolver, StrategyResult
from app.parsers.base import ListItem
from app.parsers.registry import build_parser
from app.services import health_service

logger = get_logger(__name__)


class BatchRunner:
    """单个批次的执行体（一个实例对应一次运行）。"""

    def __init__(self, batch_id: int, threads: int, engine: Any) -> None:
        self.batch_id: int = int(batch_id)
        self.threads: int = max(1, int(threads))
        self.engine = engine
        self.pause = pause_controller
        self.running: bool = False
        self.phase: str = E.PHASE_PARSE
        self.strategy: str = E.STRATEGY_COUNT
        self.strategy_params: dict[str, Any] = {}
        self.export_format: str | None = None
        self.data_source_id: int = 0
        #: 由引擎在提交时注入，用于退出时准确关闭自己那个池
        self.pool: ThreadPoolExecutor | None = None

    # ------------------------------------------------------------------
    # 主流程
    # ------------------------------------------------------------------
    def run(self) -> None:
        """执行批次（异常一律落库为 failed，绝不让线程静默退出）。"""
        self.running = True
        logger.info("批次 %s 开始执行（线程数 %s）", self.batch_id, self.threads)
        try:
            self._load()
            if self.phase == E.PHASE_PARSE:
                if not self._phase_parse():
                    return
            self._phase_execute()
        except BizError as exc:
            self._fail_batch(exc)
        except Exception as exc:  # noqa: BLE001
            self._fail_batch(
                BizError(ErrCode.INTERNAL, f"批次执行异常：{exc}", detail=format_exc(exc))
            )
        finally:
            self.running = False
            self.engine.on_runner_exit(self.batch_id, self)

    # ------------------------------------------------------------------
    # 阶段准备
    # ------------------------------------------------------------------
    def _load(self) -> None:
        """读取批次配置并把状态推进为 running。"""
        with session_scope() as db:
            batch = db.get(CrawlBatch, self.batch_id)
            if batch is None:
                raise BizError(ErrCode.BATCH_NOT_FOUND)
            self.phase = str(batch.phase or E.PHASE_PARSE)
            self.strategy = str(batch.strategy)
            self.strategy_params = dict(batch.strategy_params or {})
            self.export_format = batch.export_format
            self.data_source_id = int(batch.data_source_id)
            if batch.status != E.BATCH_RUNNING:
                batch.status = E.BATCH_RUNNING
            if not batch.started_at:
                batch.started_at = now_iso()
            batch.updated_at = now_iso()

    # ------------------------------------------------------------------
    # 阶段一：解析列表 → 建任务
    # ------------------------------------------------------------------
    def _phase_parse(self) -> bool:
        """解析列表并建任务；返回是否进入阶段二。"""
        with session_scope() as db:
            batch = db.get(CrawlBatch, self.batch_id)
            if batch is None:
                raise BizError(ErrCode.BATCH_NOT_FOUND)
            ds = db.get(DataSource, int(batch.data_source_id))
            if ds is None or int(ds.is_deleted) == 1:
                raise BizError(ErrCode.DS_NOT_FOUND, "数据源不存在或已删除")
            if int(ds.enabled) != 1:
                raise BizError(ErrCode.PARAM_INVALID, "数据源已停用，无法采集")
            cursor_before = {
                "last_item_no": int(ds.cursor_last_item_no or 0),
                "last_page": int(ds.cursor_last_page or 0),
                "last_success_date": ds.cursor_last_success_date,
            }
            if not batch.cursor_before:
                batch.cursor_before = cursor_before
            batch.request_url = str(ds.current_url or ds.homepage_url)
            batch.phase = E.PHASE_PARSE
            batch.updated_at = now_iso()
            db.add(
                TaskLog(
                    batch_id=self.batch_id,
                    task_id=None,
                    level=E.LOG_INFO,
                    message=f"阶段一开始：地址 {batch.request_url}，策略 {self.strategy}",
                    created_at=now_iso(),
                )
            )
            known = self._known_fingerprints(db, int(ds.id)) if self.strategy == E.STRATEGY_DATE else set()
            _ = (ds.name, ds.config_json, ds.script, ds.is_novel, ds.category, ds.current_url)
            db.expunge(ds)

        parser = build_parser(ds)
        resolver = StrategyResolver(ds, parser, known_fingerprints=known, log=self._log)
        result = resolver.resolve(self.strategy, self.strategy_params)
        self._log(
            E.LOG_INFO if result.ok else E.LOG_ERROR,
            f"阶段一结束：解析到 {len(result.items)} 条，跳过 {result.skipped} 条"
            + (f"，状态 {result.status}" if result.ok else f"，失败 {result.error}"),
        )

        if result.error is not None:
            # 阶段一失败：不建任务、不推进游标
            with session_scope() as db:
                batch = db.get(CrawlBatch, self.batch_id)
                if batch is not None:
                    batch.status = E.BATCH_FAILED
                    batch.phase = E.PHASE_DONE
                    batch.error_code = str(result.error.code)
                    batch.error_msg = str(result.error.message)[:500]
                    batch.warnings = list(result.warnings)
                    batch.cursor_after = dict(batch.cursor_before or {})
                    batch.finished_at = now_iso()
                    batch.updated_at = now_iso()
                    db.add(
                        TaskLog(
                            batch_id=self.batch_id,
                            task_id=None,
                            level=E.LOG_ERROR,
                            message=error_message(
                                result.error.code, result.error.message, result.error.detail
                            ),
                            created_at=now_iso(),
                        )
                    )
            logger.warning("批次 %s 阶段一失败：%s", self.batch_id, result.error)
            return False

        if not result.items:
            self._complete_empty(result)
            return False

        created = self._create_tasks(result.items)
        with session_scope() as db:
            batch = db.get(CrawlBatch, self.batch_id)
            if batch is None:
                raise BizError(ErrCode.BATCH_NOT_FOUND)
            batch.total_tasks = created
            batch.skipped_tasks = int(result.skipped)
            batch.warnings = list(result.warnings)
            batch.cursor_after = dict(result.cursor_after)
            batch.phase = E.PHASE_EXECUTE
            batch.status = E.BATCH_RUNNING
            batch.updated_at = now_iso()
        self.phase = E.PHASE_EXECUTE
        self._log(E.LOG_INFO, f"已生成 {created} 个任务，进入执行阶段")
        return created > 0

    def _known_fingerprints(self, db: Session, ds_id: int) -> set[str]:
        """S3 去重依据：该数据源历史成功任务的指纹集合。"""
        rows = db.execute(
            select(TaskResult.fingerprint)
            .join(CrawlTask, CrawlTask.id == TaskResult.task_id)
            .where(
                CrawlTask.data_source_id == int(ds_id),
                CrawlTask.status == E.TASK_SUCCESS,
                TaskResult.fingerprint.is_not(None),
            )
        ).all()
        return {str(row[0]) for row in rows if row[0]}

    def _create_tasks(self, items: list[ListItem]) -> int:
        """批量建任务（seq_no 单调递增，payload 存阶段一附加字段）。"""
        created = 0
        with session_scope() as db:
            previous = 0
            objects: list[CrawlTask] = []
            for item in items:
                seq = max(int(item.seq_no or 0), previous + 1)
                previous = seq
                payload = item.to_payload()
                objects.append(
                    CrawlTask(
                        batch_id=self.batch_id,
                        data_source_id=self.data_source_id,
                        seq_no=seq,
                        title=str(item.title)[:500],
                        source_url=str(item.url),
                        payload=payload,
                        status=E.TASK_PENDING,
                        attempt_count=0,
                        step_total=1,
                        step_done=0,
                    )
                )
                created += 1
            db.add_all(objects)
        return created

    def _complete_empty(self, result: StrategyResult) -> None:
        """去重/解析后 0 条：批次 success、0 任务（S2 仍推进 last_page）。"""
        message = "没有需要采集的新内容"
        with session_scope() as db:
            batch = db.get(CrawlBatch, self.batch_id)
            if batch is None:
                return
            batch.status = E.BATCH_SUCCESS
            batch.phase = E.PHASE_DONE
            batch.total_tasks = 0
            batch.skipped_tasks = int(result.skipped)
            batch.warnings = list(result.warnings)
            batch.cursor_after = dict(result.cursor_after)
            batch.finished_at = now_iso()
            batch.updated_at = now_iso()
            ds = db.get(DataSource, int(batch.data_source_id))
            if ds is not None and self.strategy == E.STRATEGY_PAGE:
                # 阶段一 0 条时仅 S2 推进 last_page
                last_page = int(result.cursor_after.get("last_page") or 0)
                if last_page > int(ds.cursor_last_page or 0):
                    ds.cursor_last_page = last_page
                    ds.updated_at = now_iso()
            _ = (ds.name if ds is not None else "")
            db.add(
                TaskLog(
                    batch_id=self.batch_id,
                    task_id=None,
                    level=E.LOG_INFO,
                    message=message,
                    created_at=now_iso(),
                )
            )
        logger.info("批次 %s 无新内容（success, 0 任务）", self.batch_id)

    # ------------------------------------------------------------------
    # 阶段二：并发执行
    # ------------------------------------------------------------------
    def _phase_execute(self) -> None:
        """并发执行 pending 任务，处理暂停与终止。"""
        scheduler = TaskScheduler(self.batch_id, self.export_format, self.pause)
        pool = ThreadPoolExecutor(
            max_workers=max(1, self.threads), thread_name_prefix=f"bt{self.batch_id}"
        )
        futures: set[Future[None]] = set()
        paused = False
        try:
            while True:
                if self.pause.is_paused(self.batch_id):
                    paused = True
                    break
                # 填充线程池（每个任务先抢占全局令牌，保证全局并发不超限）
                while len(futures) < self.threads:
                    if not self.engine.limiter.acquire(timeout=0.5):
                        if self.pause.is_paused(self.batch_id):
                            paused = True
                        break
                    task_id = scheduler.take_next()
                    if task_id is None:
                        self.engine.limiter.release()
                        break
                    futures.add(pool.submit(self._run_one, scheduler, task_id))
                if paused:
                    break
                if not futures:
                    break
                done, not_done = wait(futures, timeout=1.0, return_when=FIRST_COMPLETED)
                for future in done:
                    error = future.exception()
                    if error is not None:  # pragma: no cover - _run_one 已内部兜底
                        logger.error("任务线程异常：%s", error)
                        self._log(E.LOG_ERROR, f"任务线程异常：{error}")
                futures = set(not_done)
        finally:
            pool.shutdown(wait=True)

        if paused:
            # 暂停请求可能落在「最后一条任务刚完成」之后：此时已无待执行任务，
            # 直接走终结流程，避免批次卡在 paused 而进度其实是 100%。
            if self._unfinished_count() == 0:
                self._finalize()
            else:
                self._handle_paused()
            return
        self._finalize()

    def _unfinished_count(self) -> int:
        """统计批次内仍为 pending / running 的任务数。"""
        with session_scope() as db:
            value = db.execute(
                select(func.count(CrawlTask.id)).where(
                    CrawlTask.batch_id == self.batch_id,
                    CrawlTask.status.in_((E.TASK_PENDING, E.TASK_RUNNING)),
                )
            ).scalar()
        return int(value or 0)

    def _run_one(self, scheduler: TaskScheduler, task_id: int) -> None:
        """线程池工作单元：执行任务并保证归还全局令牌。"""
        self.pause.enter(self.batch_id)
        try:
            scheduler.run_task(task_id)
        except Exception as exc:  # noqa: BLE001 - 兜底避免任务悬在 running
            logger.error("任务 %s 执行崩溃：%s", task_id, exc)
            try:
                scheduler.safe_fail(task_id, exc)
            except Exception:  # noqa: BLE001
                logger.error("任务 %s 兜底置失败也失败：%s", task_id, traceback.format_exc())
        finally:
            self.engine.limiter.release()
            self.pause.leave(self.batch_id)

    def _handle_paused(self) -> None:
        """暂停收尾：30s 内活跃归零 → paused；否则 paused_with_warning。

        用条件更新（``WHERE status='paused'``）避免覆盖「用户已恢复」的新状态。
        """
        timeout = float(DEFAULTS["pause.timeout_s"])
        zero = self.pause.wait_zero_active(self.batch_id, timeout)
        finished = now_iso()
        target = E.BATCH_PAUSED if zero else E.BATCH_PAUSED_WITH_WARNING
        with session_scope() as db:
            result = db.execute(
                update(CrawlBatch)
                .where(
                    CrawlBatch.id == self.batch_id,
                    CrawlBatch.status == E.BATCH_PAUSED,
                )
                .values(status=target, updated_at=finished)
            )
            if int(result.rowcount or 0) == 0:
                logger.info("批次 %s 已被恢复，跳过暂停收尾", self.batch_id)
                return
            if not zero:
                leftovers = db.execute(
                    select(CrawlTask.id)
                    .where(
                        CrawlTask.batch_id == self.batch_id,
                        CrawlTask.status == E.TASK_RUNNING,
                    )
                    .limit(50)
                ).all()
                ids = [str(row[0]) for row in leftovers]
                db.add(
                    TaskLog(
                        batch_id=self.batch_id,
                        task_id=None,
                        level=E.LOG_WARN,
                        message=(
                            f"暂停超时（{timeout:.0f}s），仍有活跃任务未归零："
                            f"{', '.join(ids) or '未知'}"
                        ),
                        created_at=finished,
                    )
                )
        logger.info("批次 %s 已暂停（归零=%s）", self.batch_id, zero)

    # ------------------------------------------------------------------
    # 终结
    # ------------------------------------------------------------------
    def _finalize(self) -> None:
        """统计终态、推进游标、刷新健康度。"""
        finished = now_iso()
        with session_scope() as db:
            batch = db.get(CrawlBatch, self.batch_id)
            if batch is None:
                return
            counts = dict(
                db.execute(
                    select(CrawlTask.status, func.count(CrawlTask.id))
                    .where(CrawlTask.batch_id == self.batch_id)
                    .group_by(CrawlTask.status)
                ).all()
            )
            success = int(counts.get(E.TASK_SUCCESS, 0))
            failed = int(counts.get(E.TASK_FAILED, 0))
            skipped = int(counts.get(E.TASK_SKIPPED, 0))
            total = int(batch.total_tasks or (success + failed + skipped))

            batch.done_tasks = success
            batch.failed_tasks = failed
            batch.skipped_tasks = max(int(batch.skipped_tasks or 0), skipped)
            batch.phase = E.PHASE_DONE
            batch.finished_at = finished
            batch.pause_requested_at = None
            batch.updated_at = finished

            if total == 0:
                batch.status = E.BATCH_SUCCESS
            elif failed >= total:
                batch.status = E.BATCH_FAILED
                batch.error_code = str(int(ErrCode.HTTP_ERROR))
                batch.error_msg = "本次批次全部任务失败，请查看任务日志"
            elif failed > 0 or batch.skipped_tasks > 0 or batch.warnings:
                batch.status = E.BATCH_SUCCESS_WITH_WARNING
            else:
                batch.status = E.BATCH_SUCCESS

            ds = db.get(DataSource, int(batch.data_source_id))
            cursor = self._compute_cursor(db, batch, advanced=batch.status != E.BATCH_FAILED)
            batch.cursor_after = cursor
            if ds is not None:
                ds.last_crawled_at = finished
                if batch.status != E.BATCH_FAILED:
                    ds.cursor_last_item_no = int(cursor.get("last_item_no") or 0)
                    ds.cursor_last_page = int(cursor.get("last_page") or 0)
                    ds.cursor_last_success_date = cursor.get("last_success_date")
                ds.updated_at = finished
                health_service.compute_and_store(db, ds)

            db.add(
                TaskLog(
                    batch_id=self.batch_id,
                    task_id=None,
                    level=E.LOG_INFO
                    if batch.status in (E.BATCH_SUCCESS, E.BATCH_SUCCESS_WITH_WARNING)
                    else E.LOG_ERROR,
                    message=(
                        f"批次结束：状态 {batch.status}，成功 {success}，失败 {failed}，"
                        f"跳过 {batch.skipped_tasks}"
                    ),
                    created_at=finished,
                )
            )
        logger.info(
            "批次 %s 结束：成功 %s / 失败 %s", self.batch_id, success, failed
        )
        self.pause.release(self.batch_id)

    def _compute_cursor(
        self, db: Session, batch: CrawlBatch, *, advanced: bool
    ) -> dict[str, Any]:
        """计算批次结束游标：S1 按成功任务最大 seq_no，S2/S3 用阶段一计划值。"""
        before = dict(batch.cursor_before or {})
        planned = dict(batch.cursor_after or {})
        if not advanced:
            return before

        cursor = {
            "last_item_no": int(planned.get("last_item_no", before.get("last_item_no", 0)) or 0),
            "last_page": int(planned.get("last_page", before.get("last_page", 0)) or 0),
            "last_success_date": planned.get(
                "last_success_date", before.get("last_success_date")
            ),
        }
        if batch.strategy == E.STRATEGY_COUNT:
            row = db.execute(
                select(func.max(CrawlTask.seq_no)).where(
                    CrawlTask.batch_id == self.batch_id,
                    CrawlTask.status == E.TASK_SUCCESS,
                )
            ).first()
            max_seq = int(row[0]) if row and row[0] is not None else 0
            cursor["last_item_no"] = max(max_seq, int(before.get("last_item_no", 0) or 0))
        elif batch.strategy == E.STRATEGY_DATE:
            rows = db.execute(
                select(CrawlTask.payload).where(
                    CrawlTask.batch_id == self.batch_id,
                    CrawlTask.status == E.TASK_SUCCESS,
                )
            ).all()
            dates: list[str] = []
            for (payload,) in rows:
                data = payload if isinstance(payload, dict) else _load_json(payload)
                value = str(data.get("date") or "") if isinstance(data, dict) else ""
                if value:
                    dates.append(value)
            if dates:
                cursor["last_success_date"] = max(dates)
        return cursor

    # ------------------------------------------------------------------
    # 失败与日志
    # ------------------------------------------------------------------
    def _fail_batch(self, error: BizError) -> None:
        """批次级失败落库（含阶段一异常、全地址不可用等）。"""
        finished = now_iso()
        with session_scope() as db:
            batch = db.get(CrawlBatch, self.batch_id)
            if batch is None:
                return
            batch.status = E.BATCH_FAILED
            batch.phase = E.PHASE_DONE
            batch.error_code = str(error.code)
            batch.error_msg = str(error.message)[:500]
            batch.finished_at = finished
            batch.pause_requested_at = None
            batch.updated_at = finished
            if batch.cursor_before:
                batch.cursor_after = dict(batch.cursor_before)
            db.add(
                TaskLog(
                    batch_id=self.batch_id,
                    task_id=None,
                    level=E.LOG_ERROR,
                    message=error_message(error.code, error.message, error.detail),
                    created_at=finished,
                )
            )
        logger.error("批次 %s 失败：[%s] %s", self.batch_id, error.code, error.message)
        self.pause.release(self.batch_id)

    def _log(self, level: str, message: str) -> None:
        """批次级日志写入。"""
        try:
            with session_scope() as db:
                log_batch(db, self.batch_id, level, message)
        except Exception as exc:  # noqa: BLE001 - 日志失败不影响主流程
            logger.warning("写批次日志失败：%s", exc)


def _load_json(value: Any) -> Any:
    """兼容 payload 以字符串形式返回的情况。"""
    if isinstance(value, str):
        try:
            return json.loads(value)
        except (TypeError, ValueError):
            return {}
    return value or {}


__all__ = ["BatchRunner"]
