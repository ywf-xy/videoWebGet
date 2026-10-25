"""暂停控制器（D-03）。

语义：**不杀线程**。``Event`` 置位 = 运行中；清除 = 已请求暂停。
任务在原子步骤结束时调用 ``checkpoint()``，返回 False 后自行回退 ``pending``。

``active`` 计数用于「暂停后 30s 内活跃线程是否归零」判定：
未归零则批次落库为 ``paused_with_warning`` 并记录残留任务。
"""

from __future__ import annotations

import threading
import time

from app.common.logger import get_logger

logger = get_logger(__name__)


class PauseController:
    """批次级暂停登记表（线程安全）。"""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._events: dict[int, threading.Event] = {}
        self._active: dict[int, int] = {}

    # ------------------------------------------------------------------
    # 登记
    # ------------------------------------------------------------------
    def register(self, batch_id: int) -> None:
        """登记批次并**无条件**置为运行中（未暂停）。

        无条件 ``set()`` 很重要：若同一 batch_id 的历史事件仍停留在「已暂停」，
        新提交的执行体会继承该状态而直接卡在 paused_with_warning。
        """
        with self._lock:
            event = self._events.get(int(batch_id))
            if event is None:
                event = threading.Event()
                self._events[int(batch_id)] = event
            event.set()
            self._active.setdefault(int(batch_id), 0)

    def request(self, batch_id: int) -> None:
        """请求暂停（清除事件）。"""
        with self._lock:
            event = self._events.get(int(batch_id))
            if event is None:
                event = threading.Event()
                self._events[int(batch_id)] = event
            event.clear()
            self._active.setdefault(int(batch_id), 0)

    def clear(self, batch_id: int) -> None:
        """恢复运行（置位事件）。"""
        with self._lock:
            event = self._events.get(int(batch_id))
            if event is None:
                event = threading.Event()
                self._events[int(batch_id)] = event
            event.set()
            self._active.setdefault(int(batch_id), 0)

    def release(self, batch_id: int) -> None:
        """批次彻底结束，回收登记。"""
        with self._lock:
            self._events.pop(int(batch_id), None)
            self._active.pop(int(batch_id), None)

    # ------------------------------------------------------------------
    # 查询
    # ------------------------------------------------------------------
    def is_paused(self, batch_id: int) -> bool:
        """批次是否处于暂停请求状态。"""
        with self._lock:
            event = self._events.get(int(batch_id))
            return bool(event is not None and not event.is_set())

    def checkpoint(self, batch_id: int) -> bool:
        """原子步骤检查点：返回 True 表示可继续，False 表示应立即回退。"""
        return not self.is_paused(batch_id)

    def active(self, batch_id: int) -> int:
        """批次内活跃任务数。"""
        with self._lock:
            return int(self._active.get(int(batch_id), 0))

    def paused_batches(self) -> list[int]:
        """当前处于暂停请求状态的批次列表。"""
        with self._lock:
            return [bid for bid, event in self._events.items() if not event.is_set()]

    # ------------------------------------------------------------------
    # 活跃计数
    # ------------------------------------------------------------------
    def enter(self, batch_id: int) -> None:
        """任务开始执行。"""
        with self._lock:
            self._active[int(batch_id)] = int(self._active.get(int(batch_id), 0)) + 1

    def leave(self, batch_id: int) -> None:
        """任务执行结束。"""
        with self._lock:
            current = int(self._active.get(int(batch_id), 0))
            self._active[int(batch_id)] = max(0, current - 1)

    def wait_zero_active(self, batch_id: int, timeout: float = 30.0) -> bool:
        """等待活跃任务归零，返回是否在超时前归零。"""
        deadline = time.monotonic() + max(0.0, float(timeout))
        while time.monotonic() < deadline:
            if self.active(batch_id) <= 0:
                return True
            time.sleep(0.05)
        remaining = self.active(batch_id)
        if remaining > 0:
            logger.warning("批次 %s 暂停超时，仍有 %s 个活跃任务", batch_id, remaining)
        return remaining <= 0


#: 全局单例（进程内共享）
pause_controller = PauseController()

__all__ = ["PauseController", "pause_controller"]
