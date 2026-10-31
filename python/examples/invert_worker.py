# SPDX-License-Identifier: MIT OR Apache-2.0
"""Minimal worker: inverts rgb8 frames. Shows the SDK without any model.

Run by the host with ``CFA4_AI_SOCKET`` set:  python3 invert_worker.py
"""

import sys

from cfa4_ai import Worker, WorkerError, serve

_INVERT = bytes(255 - i for i in range(256))


class InvertWorker(Worker):
    name = "cfa4-invert-example"
    version = "0.1.0"
    license = "MIT OR Apache-2.0"
    impls = ("invert-rgb8",)
    devices = ("cpu",)
    limits = {"max_jobs": 2}
    features = ("cancel", "progress")

    def load(self, impl, device, precision, weights_dir):
        if device != "cpu":
            raise WorkerError("unsupported", "this example runs on the CPU only")
        return 0

    def run(self, job):
        src = job.message["inputs"].get("src")
        dst = job.message["outputs"].get("out")
        if not src or not dst or src.get("format") != "rgb8" or dst.get("format") != "rgb8":
            raise WorkerError("invalid_input", "needs an rgb8 input 'src' and an rgb8 output 'out'")
        if (src["width"], src["height"], src["stride"]) != (dst["width"], dst["height"], dst["stride"]):
            raise WorkerError("invalid_input", "input and output geometry differ")
        frames = src.get("frames", 1)
        if dst.get("frames", 1) != frames:
            raise WorkerError("invalid_input", "input and output frame counts differ")
        frame_len = src["stride"] * src["height"]
        if frame_len * frames > min(src["len"], dst["len"]):
            raise WorkerError("invalid_input", "buffers are shorter than their frames")
        inp, out = job.inputs["src"], job.outputs["out"]
        for i in range(frames):
            if job.cancelled:
                return None
            a, b = i * frame_len, (i + 1) * frame_len
            out[a:b] = bytes(inp[a:b]).translate(_INVERT)
            job.progress(i + 1, frames, "invert")
        return None


if __name__ == "__main__":
    sys.exit(serve(InvertWorker()))
