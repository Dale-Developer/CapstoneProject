"""ESSCAN shared runtime helpers for fast OMR / OCR / Ollama processing.

Why this module exists
----------------------
Before V7.9 every upload paid for a number of avoidable costs:

1. ``ollama_available()`` performed a real HTTP round-trip (2s timeout) and
   was called 3-5 times per upload, on top of the actual OCR work.
2. ``easyocr_available()`` walked the filesystem and could build the reader
   on the *first* request, so the first professor to upload after a restart
   waited ~20-40s for model load inside their request.
3. Every page was processed strictly one after another even though page 1
   (OMR) and the essay pages (OCR) are completely independent.
4. Blocking OpenCV/torch work ran directly inside ``async def`` endpoints,
   which pins FastAPI's event loop: while one sheet was processing the whole
   server stopped answering *any* request, including health checks.

This module centralises the fixes: short-lived TTL caches for availability
probes, a bounded worker pool for page-level parallelism, sane torch thread
counts, and a warmup hook that loads the heavy models at server startup
instead of inside the first user request.
"""
from __future__ import annotations

import logging
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable, Iterable, TypeVar

logger = logging.getLogger("esscan.runtime")

T = TypeVar("T")


# ---------------------------------------------------------------------------
# Environment helpers
# ---------------------------------------------------------------------------

def env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def env_int(name: str, default: int, minimum: int = 0, maximum: int = 1_000_000) -> int:
    try:
        value = int(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        value = default
    return max(minimum, min(maximum, value))


def env_float(name: str, default: float, minimum: float = 0.0, maximum: float = 1e9) -> float:
    try:
        value = float(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        value = default
    return max(minimum, min(maximum, value))


# ---------------------------------------------------------------------------
# TTL cache for availability probes
# ---------------------------------------------------------------------------

class TTLValue:
    """A single value refreshed at most once per ``ttl`` seconds.

    Availability probes (Ollama reachable? EasyOCR loadable?) are stable over
    the lifetime of a request but were being re-evaluated several times per
    upload. Caching them for a few seconds removes that overhead without
    making the system blind to a service that goes down mid-session.
    """

    __slots__ = ("_producer", "_ttl", "_value", "_expires_at", "_lock")

    def __init__(self, producer: Callable[[], T], ttl: float):
        self._producer = producer
        self._ttl = float(ttl)
        self._value: Any = None
        self._expires_at = 0.0
        self._lock = threading.Lock()

    def get(self) -> Any:
        now = time.monotonic()
        if now < self._expires_at:
            return self._value
        with self._lock:
            # Another thread may have refreshed while we waited for the lock.
            now = time.monotonic()
            if now < self._expires_at:
                return self._value
            try:
                self._value = self._producer()
            except Exception as exc:  # pragma: no cover - defensive
                logger.warning("TTL producer failed: %s", exc)
                self._value = None
            self._expires_at = time.monotonic() + self._ttl
            return self._value

    def invalidate(self) -> None:
        with self._lock:
            self._expires_at = 0.0


# ---------------------------------------------------------------------------
# Worker pool for page-level parallelism
# ---------------------------------------------------------------------------

_pool: ThreadPoolExecutor | None = None
_pool_lock = threading.Lock()


def page_workers() -> int:
    """How many answer-sheet pages may be processed at the same time.

    EasyOCR/torch already use several threads internally for a single page,
    so oversubscribing here makes things slower, not faster. The default is
    deliberately small and can be tuned with ``ESSCAN_PAGE_WORKERS``.
    """
    cpu = os.cpu_count() or 4
    default = 2 if cpu <= 4 else 3
    return env_int("ESSCAN_PAGE_WORKERS", default, 1, 8)


def get_pool() -> ThreadPoolExecutor:
    global _pool
    if _pool is None:
        with _pool_lock:
            if _pool is None:
                _pool = ThreadPoolExecutor(
                    max_workers=page_workers(),
                    thread_name_prefix="esscan-page",
                )
    return _pool


def map_pages(fn: Callable[[T], Any], items: Iterable[T]) -> list[Any]:
    """Run ``fn`` over ``items`` in parallel, preserving input order.

    Exceptions are returned in place of a result rather than raised, so one
    unreadable essay page can never abort the whole submission. Callers are
    expected to check for ``Exception`` instances.
    """
    items = list(items)
    if not items:
        return []
    if len(items) == 1:
        try:
            return [fn(items[0])]
        except Exception as exc:
            return [exc]

    pool = get_pool()
    futures = [pool.submit(fn, item) for item in items]
    results: list[Any] = []
    for future in futures:
        try:
            results.append(future.result())
        except Exception as exc:
            results.append(exc)
    return results


# ---------------------------------------------------------------------------
# Torch / OpenCV thread tuning
# ---------------------------------------------------------------------------

_threads_configured = False


def configure_threads() -> dict[str, Any]:
    """Pick thread counts that suit CPU-only inference on a laptop.

    Torch defaults to one thread per logical core. On a 4-core dev machine
    that leaves nothing for OpenCV or FastAPI itself and causes heavy context
    switching during OCR. Leaving one core free measurably improves wall-clock
    time for a single upload and keeps the UI responsive.
    """
    global _threads_configured
    info: dict[str, Any] = {"configured": _threads_configured}
    if _threads_configured:
        return info

    cpu = os.cpu_count() or 4
    default_threads = max(1, cpu - 1) if cpu > 2 else 1
    threads = env_int("ESSCAN_TORCH_THREADS", default_threads, 1, 32)

    try:
        import torch

        torch.set_num_threads(threads)
        try:
            torch.set_num_interop_threads(max(1, threads // 2))
        except Exception:
            # set_num_interop_threads raises if called after parallel work
            # has already started; that is harmless here.
            pass
        try:
            torch.set_grad_enabled(False)
        except Exception:
            pass
        info["torch_threads"] = threads
    except Exception as exc:
        info["torch_error"] = f"{type(exc).__name__}: {exc}"

    try:
        import cv2

        # OpenCV's own pool competes with torch's during OCR. Bound it.
        cv2.setNumThreads(env_int("ESSCAN_OPENCV_THREADS", max(1, threads // 2), 1, 32))
        try:
            cv2.setUseOptimized(True)
        except Exception:
            pass
        info["opencv_threads"] = cv2.getNumThreads()
    except Exception as exc:
        info["opencv_error"] = f"{type(exc).__name__}: {exc}"

    _threads_configured = True
    info["configured"] = True
    return info


# ---------------------------------------------------------------------------
# Startup warmup
# ---------------------------------------------------------------------------

_warmup_state: dict[str, Any] = {"started": False, "done": False, "detail": {}}
_warmup_lock = threading.Lock()


def warmup_state() -> dict[str, Any]:
    return dict(_warmup_state)


def _run_warmup() -> None:
    detail: dict[str, Any] = {}
    started = time.monotonic()

    detail["threads"] = configure_threads()

    # EasyOCR: build the reader and push one tiny image through it so the
    # detector and recognizer graphs are fully materialised.
    if env_bool("ESSCAN_WARMUP_EASYOCR", True):
        try:
            import numpy as np

            from services.ocr_match import _get_reader

            reader = _get_reader()
            if reader is not None:
                blank = np.full((64, 256, 3), 255, dtype=np.uint8)
                try:
                    reader.readtext(blank, detail=1, paragraph=False)
                except Exception:
                    pass
                detail["easyocr"] = "ready"
            else:
                detail["easyocr"] = "unavailable"
        except Exception as exc:
            detail["easyocr"] = f"error: {type(exc).__name__}: {exc}"

    # spaCy: loading en_core_web_sm takes a second or two; do it up front.
    if env_bool("ESSCAN_WARMUP_SPACY", True):
        try:
            from services.nlp_spacy import warmup as spacy_warmup

            detail["spacy"] = spacy_warmup()
        except Exception as exc:
            detail["spacy"] = f"error: {type(exc).__name__}: {exc}"

    # Sentence-BERT: loading the fine-tuned model takes a few seconds, so do
    # it at startup rather than inside the first essay that needs grading.
    if env_bool("ESSCAN_WARMUP_SBERT", True):
        try:
            from services.nlp_spacy import warmup_sbert

            detail["sbert"] = warmup_sbert()
        except Exception as exc:
            detail["sbert"] = f"error: {type(exc).__name__}: {exc}"

    # Ollama: ask the daemon to resident-load the vision model so the first
    # real verification request does not pay the model-load cost.
    if env_bool("ESSCAN_WARMUP_OLLAMA", True):
        try:
            from services.ocr_hybrid import preload_ollama

            detail["ollama"] = preload_ollama()
        except Exception as exc:
            detail["ollama"] = f"error: {type(exc).__name__}: {exc}"

    detail["seconds"] = round(time.monotonic() - started, 2)
    _warmup_state["detail"] = detail
    _warmup_state["done"] = True
    logger.info("ESSCAN warmup finished in %ss: %s", detail["seconds"], detail)


def start_warmup(background: bool = True) -> None:
    """Load heavy models once, at startup, instead of inside a user request."""
    global _warmup_state
    with _warmup_lock:
        if _warmup_state["started"]:
            return
        _warmup_state["started"] = True

    if not background:
        _run_warmup()
        return

    thread = threading.Thread(target=_run_warmup, name="esscan-warmup", daemon=True)
    thread.start()


__all__ = [
    "TTLValue",
    "configure_threads",
    "env_bool",
    "env_float",
    "env_int",
    "get_pool",
    "map_pages",
    "page_workers",
    "start_warmup",
    "warmup_state",
]
