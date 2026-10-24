"""Per-phase logging with rich."""

from __future__ import annotations

import logging
import time
from contextlib import contextmanager

from rich.console import Console
from rich.logging import RichHandler

console = Console(stderr=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(message)s",
    datefmt="%H:%M:%S",
    handlers=[RichHandler(console=console, show_path=False, markup=True)],
)
log = logging.getLogger("opentranslator")
for noisy in ("httpx", "huggingface_hub"):
    logging.getLogger(noisy).setLevel(logging.WARNING)


@contextmanager
def phase(name: str):
    """Frame a pipeline phase and time it."""
    console.rule(f"[bold cyan]{name}")
    start = time.monotonic()
    yield
    log.info(f"[green]✔ {name}[/] in {time.monotonic() - start:.1f}s")
