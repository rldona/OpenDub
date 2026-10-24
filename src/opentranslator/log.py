"""Per-phase logging with rich, plus an event feed for observers (the web frontend).

Phases and progress bars report to the terminal as before; subscribers also get
them as plain dicts: {"type": "phase", ...} from `phase()` and
{"type": "progress", ...} from the `Progress` defined here, which the phases
use instead of rich's. Log records reach observers through the logging module
itself (a handler on `log`), so nothing is reported twice.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from contextlib import contextmanager
from typing import Any

from rich import progress as rich_progress
from rich.console import Console
from rich.logging import RichHandler
from rich.text import Text

console = Console(stderr=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(message)s",
    datefmt="%H:%M:%S",
    handlers=[RichHandler(console=console, show_path=False, markup=True)],
)
log = logging.getLogger("opentranslator")
# Explicit: basicConfig does nothing if something configured logging first (pytest, uvicorn)
log.setLevel(logging.INFO)
for noisy in ("httpx", "httpx2", "huggingface_hub", "filelock"):
    logging.getLogger(noisy).setLevel(logging.WARNING)

Event = dict[str, Any]
_listeners: list[Callable[[Event], None]] = []


def subscribe(listener: Callable[[Event], None]) -> Callable[[], None]:
    """Receive phase and progress events; returns the function that unsubscribes."""
    _listeners.append(listener)
    return lambda: _listeners.remove(listener)


def emit(event: Event) -> None:
    for listener in list(_listeners):
        try:
            listener(event)
        except Exception:  # an observer must never break the pipeline
            logging.getLogger(__name__).debug("event listener failed", exc_info=True)


def plain(markup: str) -> str:
    """Text without rich markup ("[bold]x[/]" → "x")."""
    try:
        return Text.from_markup(markup).plain
    except Exception:  # not valid markup: keep it as it is
        return markup


@contextmanager
def phase(name: str):
    """Frame a pipeline phase and time it."""
    console.rule(f"[bold cyan]{name}")
    emit({"type": "phase", "name": name, "state": "start"})
    start = time.monotonic()
    try:
        yield
    except BaseException:
        emit({"type": "phase", "name": name, "state": "error", "seconds": round(time.monotonic() - start, 1)})
        raise
    log.info(f"[green]✔ {name}[/] in {time.monotonic() - start:.1f}s")
    emit({"type": "phase", "name": name, "state": "done", "seconds": round(time.monotonic() - start, 1)})


class Progress(rich_progress.Progress):
    """rich's Progress, also reporting each bar to the event subscribers (at most 10 times/s per bar)."""

    MIN_INTERVAL = 0.1

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._last_emit: dict[rich_progress.TaskID, float] = {}

    def add_task(self, description: str, *args: Any, **kwargs: Any) -> rich_progress.TaskID:
        task_id = super().add_task(description, *args, **kwargs)
        self._report(task_id, force=True)
        return task_id

    def update(self, task_id: rich_progress.TaskID, **kwargs: Any) -> None:
        super().update(task_id, **kwargs)
        self._report(task_id)

    def advance(self, task_id: rich_progress.TaskID, advance: float = 1) -> None:
        super().advance(task_id, advance)
        self._report(task_id)

    def _report(self, task_id: rich_progress.TaskID, force: bool = False) -> None:
        if not _listeners:
            return
        task = self._tasks[task_id]
        now = time.monotonic()
        done = task.total is not None and task.completed >= task.total
        if not (force or done) and now - self._last_emit.get(task_id, 0.0) < self.MIN_INTERVAL:
            return
        self._last_emit[task_id] = now
        emit({"type": "progress", "task": plain(task.description), "completed": task.completed, "total": task.total})
