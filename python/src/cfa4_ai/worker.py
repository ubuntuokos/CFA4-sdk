# SPDX-License-Identifier: MIT OR Apache-2.0
"""A worker loop: subclass ``Worker``, implement ``load`` and ``run``, call ``serve``.

The loop answers ``hello``, ``load``, ``run``, ``cancel``, ``unload`` and
``shutdown`` as ``docs/protocol.md`` describes. Jobs run in threads, at most
``limits["max_jobs"]`` at a time, so a ``cancel`` is read while a job runs.
An exception in your code becomes an ``error`` message, never a crash of the
loop: ``WorkerError`` keeps its code, an out-of-memory error becomes ``oom``,
a missing file during ``load`` becomes ``model_missing``, anything else
``model_error``.
"""

import os
import socket
import threading
import time

from .protocol import (
    MAX_SAFE_INTEGER, PROTOCOL_VERSION, SOCKET_ENV, MessageReader, ProtocolError, encode,
    negotiate,
)
from .shm import MappedBuffer

_RETRYABLE = {"oom", "model_error", "crash"}


class WorkerError(Exception):
    """Raise from ``load`` or ``run`` to send an ``error`` with this code."""

    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


class Job:
    """One ``run`` request, as handed to ``Worker.run``."""

    def __init__(self, message, send_progress):
        self.message = message
        self.id = message["job"]
        self.impl = message["impl"]
        self.device = message["device"]
        self.params = message["params"]
        self.tier = message["tier"]
        self.inputs = {}
        self.outputs = {}
        self._cancelled = threading.Event()
        self._send_progress = send_progress

    @property
    def cancelled(self):
        """True once the host sent ``cancel``; stop at the next chunk or step."""
        return self._cancelled.is_set()

    def progress(self, done, total, stage=None):
        self._send_progress(self, done, total, stage)


def _error_code(exc, during_load):
    if isinstance(exc, WorkerError):
        return exc.code
    if isinstance(exc, MemoryError) or "OutOfMemory" in type(exc).__name__:
        return "oom"
    if during_load and isinstance(exc, FileNotFoundError):
        return "model_missing"
    return "model_error"


class Worker:
    """Base class. Set ``name``, ``version`` and ``impls``; override the hooks."""

    name = "worker"
    version = "0.0.0"
    license = None
    impls = ()
    devices = None
    limits = {"max_jobs": 1}

    def load(self, impl, device, precision, weights_dir):
        """Loads a model; returns the VRAM it uses in MiB."""
        raise WorkerError("unsupported", f"{impl} cannot be loaded")

    def run(self, job):
        """Reads ``job.inputs`` and writes ``job.outputs`` (``memoryview``s).
        Returns optional metrics, e.g. ``{"peak_vram_mb": 900}``."""
        raise WorkerError("unsupported", f"{job.impl} cannot run")

    def unload(self, impl, device):
        """Frees a model."""


class _Loop:
    def __init__(self, worker, sock):
        self.worker = worker
        self.sock = sock
        self.reader = MessageReader(sock.makefile("rb"))
        self.send_lock = threading.Lock()
        self.next_id = 0
        self.jobs = {}
        self.jobs_lock = threading.Lock()
        self.loaded = {}

    def send(self, message):
        with self.send_lock:
            message["id"] = self.next_id
            self.next_id = min(self.next_id + 1, MAX_SAFE_INTEGER)
            try:
                data = encode(message)
            except (ProtocolError, TypeError, ValueError) as e:
                data = encode({"type": "error", "id": message["id"], "code": "crash",
                               "message": f"worker built an invalid message: {e}"[:2000],
                               "retryable": True})
            self.sock.sendall(data)

    def error(self, code, text, reply_to=None, job=None):
        text = str(text).encode("utf-8", "replace").decode("utf-8")[:2000]
        message = {"type": "error", "id": 0, "code": code, "message": text,
                   "retryable": code in _RETRYABLE}
        if reply_to is not None:
            message["reply_to"] = reply_to
        if job is not None:
            message["job"] = job
        self.send(message)

    def serve(self):
        hello = self.reader.next_message()
        if hello is None:
            return 0
        if hello["type"] != "hello":
            self.error("protocol", "the first message must be hello")
            return 2
        version = negotiate(hello["protocol"]["min"], hello["protocol"]["max"])
        if version is None:
            self.error("unsupported", f"protocol {PROTOCOL_VERSION} not offered", hello["id"])
            return 2
        caps = {"type": "caps", "id": 0, "reply_to": hello["id"], "protocol": version,
                "worker": {"name": self.worker.name, "version": self.worker.version},
                "impls": list(self.worker.impls), "limits": dict(self.worker.limits)}
        if self.worker.license:
            caps["worker"]["license"] = self.worker.license
        if self.worker.devices is not None:
            caps["devices"] = list(self.worker.devices)
        self.send(caps)
        for message in self.reader:
            kind = message["type"]
            if kind == "shutdown":
                self.cancel_all()
                return 0
            handler = getattr(self, f"on_{kind}", None)
            if handler is None:
                self.error("protocol", f"{kind} is not a host message", message["id"])
                return 2
            handler(message)
        self.cancel_all()
        return 0

    def on_load(self, m):
        impl, device = m["impl"], m["device"]
        if impl not in self.worker.impls:
            self.error("unsupported", f"unknown implementation {impl}", m["id"])
            return
        try:
            vram = int(self.worker.load(impl, device, m.get("precision"), m.get("weights_dir")))
        except Exception as e:  # the worker's code must not stop the loop
            self.error(_error_code(e, during_load=True), e, m["id"])
            return
        self.loaded[(impl, _device_key(device))] = {"impl": impl, "device": device,
                                                     "vram_mb": max(vram, 0)}
        self.send({"type": "loaded", "id": 0, "reply_to": m["id"], "impl": impl,
                   "vram_mb": max(vram, 0)})

    def on_unload(self, m):
        impl = m["impl"]
        keys = [k for k in self.loaded if k[0] == impl
                and ("device" not in m or k[1] == _device_key(m["device"]))]
        for key in keys:
            try:
                self.worker.unload(impl, self.loaded[key]["device"])
            except Exception as e:  # the model stays resident, so a later unload can retry
                self.error(_error_code(e, during_load=False), e, m["id"])
                continue
            self.loaded.pop(key, None)
        self.send({"type": "stats", "id": 0, "reply_to": m["id"],
                   "loaded": list(self.loaded.values())})

    def on_run(self, m):
        if (m["impl"], _device_key(m["device"])) not in self.loaded:
            self.error("unsupported", f"{m['impl']} is not loaded on {m['device']}", m["id"], m["job"])
            return
        with self.jobs_lock:
            if m["job"] in self.jobs:
                self.error("invalid_input", "job id already running", m["id"], m["job"])
                return
            if len(self.jobs) >= self.worker.limits.get("max_jobs", 1):
                self.error("unsupported", "too many jobs at once", m["id"], m["job"])
                return
            job = Job(m, self.send_progress)
            self.jobs[job.id] = job
        threading.Thread(target=self.run_job, args=(job,), daemon=True).start()

    def on_cancel(self, m):
        with self.jobs_lock:
            job = self.jobs.get(m["job"])
        if job is not None:
            job._cancelled.set()

    def send_progress(self, job, done, total, stage):
        message = {"type": "progress", "id": 0, "reply_to": job.message["id"], "job": job.id,
                   "done": int(done), "total": int(total)}
        if stage is not None:
            message["stage"] = str(stage)[:64]
        self.send(message)

    def run_job(self, job):
        m = job.message
        try:
            reply = self.execute(job)
        except Exception as e:
            code = "cancelled" if job.cancelled else _error_code(e, during_load=False)
            reply = ("error", code, e)
        finally:
            # Free the mappings and the job slot before the host can see the outcome,
            # so it may send the next chunk as soon as it reads the reply.
            for mapped in [*job.inputs.values(), *job.outputs.values()]:
                if isinstance(mapped, MappedBuffer):
                    mapped.close()
            with self.jobs_lock:
                self.jobs.pop(job.id, None)
        try:
            if reply[0] == "result":
                self.send(reply[1])
            else:
                self.error(reply[1], reply[2], m["id"], job.id)
        except OSError:
            pass

    def execute(self, job):
        m = job.message
        started = time.monotonic()
        try:
            for name, buffer in m["inputs"].items():
                job.inputs[name] = MappedBuffer(buffer, writable=False)
            for name, buffer in m["outputs"].items():
                job.outputs[name] = MappedBuffer(buffer, writable=True)
        except (OSError, ValueError, ProtocolError) as e:
            raise WorkerError("invalid_input", f"cannot map buffer: {e}") from None
        mapped = job.inputs, job.outputs
        job.inputs = {k: v.view for k, v in mapped[0].items()}
        job.outputs = {k: v.view for k, v in mapped[1].items()}
        try:
            metrics = self.worker.run(job) or {}
        finally:
            job.inputs, job.outputs = mapped
        if job.cancelled:
            return ("error", "cancelled", "cancelled by host")
        metrics = dict(metrics)
        metrics.setdefault("elapsed_ms", int((time.monotonic() - started) * 1000))
        return ("result", {"type": "result", "id": 0, "reply_to": m["id"], "job": job.id,
                           "outputs": m["outputs"], "metrics": metrics})

    def cancel_all(self):
        with self.jobs_lock:
            for job in self.jobs.values():
                job._cancelled.set()


def _device_key(device):
    return ("cpu",) if device == "cpu" else ("gpu", device)


def serve(worker, socket_path=None):
    """Connects to the host and serves until ``shutdown``. Returns the exit code."""
    path = socket_path or os.environ.get(SOCKET_ENV)
    if not path:
        raise SystemExit(f"{SOCKET_ENV} is not set")
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        sock.connect(path)
        loop = _Loop(worker, sock)
        try:
            return loop.serve()
        except ProtocolError as e:
            try:
                loop.error("protocol", e)
            except OSError:
                pass
            return 2
        except OSError:
            return 1
    finally:
        sock.close()
