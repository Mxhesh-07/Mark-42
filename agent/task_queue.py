import threading
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Callable, Any

from agent import task_store


# Re-queue tasks that were still pending/running when the process last stopped,
# so an interrupted task resumes instead of vanishing. Set False to disable.
RESTORE_INTERRUPTED = True


def _think(kind: str, text: str) -> None:
    """Best-effort feed to the THINKING pane (the UI may not be loaded)."""
    try:
        from ui import jarvis_think
        jarvis_think(kind, text)
    except Exception:
        pass


class TaskStatus(Enum):
    PENDING    = "pending"
    RUNNING    = "running"
    COMPLETED  = "completed"
    FAILED     = "failed"
    CANCELLED  = "cancelled"


class TaskPriority(Enum):
    LOW    = 3
    NORMAL = 2
    HIGH   = 1   


@dataclass(order=True)
class Task:
    priority:    int                       
    created_at:  float = field(compare=False)
    task_id:     str   = field(compare=False)
    goal:        str   = field(compare=False)
    status:      TaskStatus = field(compare=False, default=TaskStatus.PENDING)
    result:      Any        = field(compare=False, default=None)
    error:       str        = field(compare=False, default="")
    speak:       Any        = field(compare=False, default=None)   
    on_complete: Any        = field(compare=False, default=None)  
    cancel_flag: threading.Event = field(compare=False, default_factory=threading.Event)


class TaskQueue:
    def __init__(self, max_concurrent: int = 1):
        self._queue:        list[Task]       = []
        self._lock:         threading.Lock   = threading.Lock()
        self._condition:    threading.Condition = threading.Condition(self._lock)
        self._tasks:        dict[str, Task]  = {} 
        self._running:      bool             = False
        self._worker_thread: threading.Thread | None = None
        self._max_concurrent = max_concurrent
        self._active_count   = 0
        self._executor       = None
        self._approver       = None

    def set_approver(self, approver) -> None:
        """Register the callable that answers confirmation prompts (A1).

        ``approver(tool, params, effect) -> bool`` is handed the *effect* of the
        action, not just its tool name, so the yes it returns can be bound to
        exactly that effect. Passing ``None`` restores fail-closed behaviour:
        every confirmation-level action is denied.
        """
        self._approver  = approver
        self._executor  = None   # rebuilt with the new approver

    def _get_executor(self):
        if self._executor is None:
            from agent.executor import AgentExecutor
            self._executor = AgentExecutor(approver=self._approver)
        return self._executor

    def start(self) -> None:
        if self._running:
            return
        self._running      = True
        self._worker_thread = threading.Thread(
            target=self._worker_loop,
            daemon=True,
            name="AgentTaskQueue"
        )
        self._worker_thread.start()
        print("[TaskQueue] ✅ Started")
        self._restore_interrupted()

    def _restore_interrupted(self) -> None:
        """Re-queue tasks that were pending/running when the process last stopped."""
        if not RESTORE_INTERRUPTED:
            return
        try:
            records = task_store.resumable()
        except Exception as e:
            print(f"[TaskQueue] ⚠️ Could not restore tasks: {e}")
            return
        if not records:
            return

        print(f"[TaskQueue] ♻️ Restoring {len(records)} interrupted task(s)")
        for rec in records:
            goal = rec.get("goal")
            if not goal:
                continue
            task_store.mark_interrupted(rec["task_id"])
            self.submit(goal, task_id=rec["task_id"], resumed=True)

    def stop(self) -> None:
        self._running = False
        with self._condition:
            self._condition.notify_all()
        print("[TaskQueue] 🔴 Stopped")

    def submit(
        self,
        goal:        str,
        priority:    TaskPriority = TaskPriority.NORMAL,
        speak:       Callable | None = None,
        on_complete: Callable | None = None,
        task_id:     str | None = None,
        resumed:     bool = False,
    ) -> str:

        task_id = task_id or str(uuid.uuid4())[:8]

        # Kill switch: refuse to accept new work while it is engaged.
        try:
            from agent import policy
            if policy.kill_requested():
                print(f"[TaskQueue] 🛑 Kill switch engaged — refusing task: {goal[:60]}")
                _think("err", "kill switch engaged — refused new task")
                return ""
        except Exception:
            pass

        # Rate limit: at most `max_tasks_per_hour` background tasks per hour.
        try:
            from agent import policy, audit
            cap = int(policy.limits().get("max_tasks_per_hour", 0) or 0)
            if cap > 0:
                cutoff = time.time() - 3600
                recent = sum(1 for r in task_store.all_tasks()
                             if r.get("created", 0) >= cutoff)
                if recent >= cap:
                    print(f"[TaskQueue] ⏳ Rate limit reached ({recent}/{cap} tasks/hour) "
                          f"— refusing: {goal[:50]}")
                    audit.record("task_start", outcome="blocked", goal=goal,
                                 detail=f"rate limit {recent}/{cap} per hour")
                    _think("err", f"rate limit {recent}/{cap} tasks/hour — refused")
                    return ""
        except Exception:
            pass

        task    = Task(
            priority    = priority.value,
            created_at  = time.time(),
            task_id     = task_id,
            goal        = goal,
            speak       = speak,
            on_complete = on_complete,
        )

        with self._condition:
            self._queue.append(task)
            self._queue.sort(key=lambda t: (t.priority, t.created_at))
            self._tasks[task_id] = task
            self._condition.notify()

        try:
            task_store.upsert(
                task_id,
                goal=goal,
                status="pending",
                priority=priority.name,
                resumed=resumed,
            )
        except Exception as e:
            print(f"[TaskQueue] ⚠️ Could not persist task: {e}")

        label = "resumed task" if resumed else "Task queued"
        print(f"[TaskQueue] 📥 {label}: [{task_id}] {goal[:60]}")
        _think("sys", f"queued background task [{task_id}]: {goal[:60]}")
        return task_id

    def cancel(self, task_id: str) -> bool:

        with self._lock:
            task = self._tasks.get(task_id)
            if not task:
                return False
            if task.status in (TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELLED):
                return False

            task.cancel_flag.set()
            task.status = TaskStatus.CANCELLED
            try:
                self._queue.remove(task)
            except ValueError:
                pass
            self._condition.notify()
            print(f"[TaskQueue] 🚫 Task cancelled: [{task_id}]")
            try:
                task_store.set_status(task_id, "cancelled")
            except Exception:
                pass
            return True

    def get_status(self, task_id: str) -> dict | None:
        with self._lock:
            task = self._tasks.get(task_id)
            if not task:
                return None
            return {
                "task_id": task.task_id,
                "goal":    task.goal,
                "status":  task.status.value,
                "result":  task.result,
                "error":   task.error,
            }

    def get_all_statuses(self) -> list[dict]:
        with self._lock:
            return [
                {
                    "task_id": t.task_id,
                    "goal":    t.goal[:50],
                    "status":  t.status.value,
                }
                for t in self._tasks.values()
            ]

    def pending_count(self) -> int:
        with self._lock:
            return sum(1 for t in self._queue if t.status == TaskStatus.PENDING)

    def _worker_loop(self) -> None:
        while self._running:
            task = None

            with self._condition:
                while self._running and not self._next_task():
                    self._condition.wait(timeout=1.0)
                task = self._next_task()
                if task:
                    task.status = TaskStatus.RUNNING
                    self._active_count += 1
                    try:
                        self._queue.remove(task)
                    except ValueError:
                        pass

            if task:
                threading.Thread(
                    target=self._run_task,
                    args=(task,),
                    daemon=True,
                    name=f"AgentTask-{task.task_id}"
                ).start()

    def _next_task(self) -> Task | None:
        if self._active_count >= self._max_concurrent:
            return None
        # Purge any cancelled tasks that are still lingering in the queue
        self._queue[:] = [
            t for t in self._queue
            if not (t.status == TaskStatus.CANCELLED or t.cancel_flag.is_set())
        ]
        for task in self._queue:
            if task.status == TaskStatus.PENDING:
                return task
        return None

    def _run_task(self, task: Task) -> None:
        print(f"[TaskQueue] ▶️ Running: [{task.task_id}] {task.goal[:60]}")
        _think("tool", f"[{task.task_id}] {task.goal[:60]}")
        try:
            task_store.set_status(task.task_id, "running")
        except Exception:
            pass
        try:
            from agent.executor import AgentExecutor
            executor = AgentExecutor(task_id=task.task_id, approver=self._approver)
            result   = executor.execute(
                goal        = task.goal,
                speak       = task.speak,
                cancel_flag = task.cancel_flag,
            )

            with self._lock:
                if task.cancel_flag.is_set():
                    task.status = TaskStatus.CANCELLED
                else:
                    task.status = TaskStatus.COMPLETED
                    task.result = result
                self._active_count -= 1

            try:
                if task.cancel_flag.is_set():
                    task_store.set_status(task.task_id, "cancelled")
                else:
                    task_store.set_status(task.task_id, "completed",
                                          result=str(result)[:2000])
            except Exception as e:
                print(f"[TaskQueue] ⚠️ Could not persist result: {e}")

            if task.on_complete and not task.cancel_flag.is_set():
                try:
                    task.on_complete(task.task_id, result)
                except Exception as e:
                    print(f"[TaskQueue] ⚠️ on_complete callback error: {e}")

            print(f"[TaskQueue] ✅ Completed: [{task.task_id}]")
            _think("result", f"[{task.task_id}] task completed")

        except Exception as e:
            with self._lock:
                task.status = TaskStatus.FAILED
                task.error  = str(e)
                self._active_count -= 1
            try:
                task_store.set_status(task.task_id, "failed", error=str(e)[:2000])
            except Exception:
                pass
            print(f"[TaskQueue] ❌ Failed: [{task.task_id}] {e}")
            _think("err", f"[{task.task_id}] task failed: {e}")

        with self._condition:
            self._condition.notify()

_queue        = TaskQueue()
_queue_started = False
_queue_lock    = threading.Lock()


def get_queue() -> TaskQueue:
    global _queue_started
    with _queue_lock:
        if not _queue_started:
            _queue.start()
            _queue_started = True
    return _queue