# SPDX-License-Identifier: MIT OR Apache-2.0
"""The Python SDK: it agrees with the reference validator, frames lines like the
Rust crate, and drives the example worker through a whole session."""

import copy
import io
import json
import os
import socket
import subprocess
import sys
import tempfile
import threading
import unittest
import uuid
from pathlib import Path

from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "python" / "src"))

import cfa4_ai  # noqa: E402
from cfa4_ai import ProtocolError, decode, encode  # noqa: E402
from cfa4_ai._schema import Validator  # noqa: E402

SCHEMA = json.loads((ROOT / "schemas" / "protocol.schema.json").read_text(encoding="utf-8"))
MESSAGES = ROOT / "examples" / "messages"


def jsonl(name):
    return [json.loads(line) for line in (MESSAGES / name).read_text(encoding="utf-8").splitlines() if line.strip()]


def mutations(message):
    """Every message with one field removed or replaced by an odd value."""
    odd = [None, -1, 0, 1.5, 2**53, True, "", "x" * 2100, "/cfa4-ai-../x", {}, [], ["a", "a"]]

    def walk(node, path):
        if isinstance(node, dict):
            for key in list(node):
                yield path + [key], None
                yield from walk(node[key], path + [key])
        elif isinstance(node, list):
            for i, item in enumerate(node):
                yield from walk(item, path + [i])

    for path, _ in walk(message, []):
        parent = message
        for key in path[:-1]:
            parent = parent[key]
        removed = copy.deepcopy(message)
        target = removed
        for key in path[:-1]:
            target = target[key]
        del target[path[-1]]
        yield removed
        for value in odd:
            changed = copy.deepcopy(message)
            target = changed
            for key in path[:-1]:
                target = target[key]
            target[path[-1]] = value
            yield changed
    extra = copy.deepcopy(message)
    extra["surprise"] = 1
    yield extra


class SchemaAgreement(unittest.TestCase):
    def test_packaged_schema_is_the_repository_schema(self):
        packaged = ROOT / "python" / "src" / "cfa4_ai" / "protocol.schema.json"
        self.assertEqual(packaged.read_bytes(), (ROOT / "schemas" / "protocol.schema.json").read_bytes())

    def test_validator_agrees_with_jsonschema(self):
        ours, reference = Validator(SCHEMA), Draft202012Validator(SCHEMA)
        cases = jsonl("session.jsonl") + jsonl("full.jsonl") + jsonl("invalid.jsonl")
        checked = 0
        for message in cases:
            for candidate in [message, *mutations(message)]:
                with self.subTest(candidate=json.dumps(candidate)[:200]):
                    self.assertEqual(ours.is_valid(candidate), reference.is_valid(candidate))
                checked += 1
        self.assertGreater(checked, 4000)


class Codec(unittest.TestCase):
    def test_examples_round_trip(self):
        for message in jsonl("session.jsonl") + jsonl("full.jsonl"):
            self.assertEqual(decode(encode(message)), message)

    def test_invalid_examples_are_rejected(self):
        for line in (MESSAGES / "invalid.jsonl").read_text(encoding="utf-8").splitlines():
            with self.subTest(line=line), self.assertRaises(ProtocolError):
                decode(line)

    def test_non_json_input_is_rejected(self):
        for line in [b'{"type":"shutdown","id":NaN}', b'{"type":"shutdown","id":1,"id":2}',
                     b"\xff\xfe", b"[" * 100000, b"not json"]:
            with self.subTest(line=line[:40]), self.assertRaises(ProtocolError):
                decode(line)

    def test_numbers_compare_as_json_values(self):
        caps = {"type": "caps", "id": 0, "reply_to": 0, "protocol": 1,
                "worker": {"name": "w", "version": "1"}, "impls": ["a"],
                "limits": {"max_jobs": 1}, "devices": [0, 0.0]}
        self.assertFalse(Draft202012Validator(SCHEMA).is_valid(caps))
        with self.assertRaises(ProtocolError):
            decode(json.dumps(caps))

    def test_deep_nesting_is_a_protocol_error(self):
        for line in ['{"type":' + "[" * 500 + "]" * 500 + ',"id":1}',
                     '{"type":"run","id":1,"params":' + '{"a":' * 900 + "1" + "}" * 900 + "}"]:
            with self.subTest(line=line[:30]), self.assertRaises(ProtocolError) as e:
                decode(line)
            self.assertEqual(e.exception.code, "json")

    def test_unpaired_surrogates_are_rejected(self):
        for line in ['{"type":"shutdown","id":1,"\\ud800":0}',
                     '{"type":"error","id":1,"code":"crash","message":"\\udfff"}']:
            with self.subTest(line=line), self.assertRaises(ProtocolError) as e:
                decode(line)
            self.assertEqual(e.exception.code, "json")
        with self.assertRaises(ProtocolError):
            encode({"type": "error", "id": 1, "code": "crash", "message": "\ud800"})

    def test_integral_floats_become_ints(self):
        run = jsonl("session.jsonl")[4]
        line = json.dumps(run).replace('"offset": 0', '"offset": 0.0').replace('"stride": 5760', '"stride": 5760.0')
        decoded = decode(line)
        self.assertEqual(type(decoded["inputs"]["src"]["offset"]), int)
        self.assertEqual(type(decoded["inputs"]["src"]["stride"]), int)
        params = decode(line.replace('"refine": true', '"scale": 2.0'))["params"]
        self.assertEqual(type(params["scale"]), float)

    def test_field_of_a_validation_error(self):
        with self.assertRaises(ProtocolError) as e:
            decode('{"type":"load","id":1,"impl":"x","device":0,"weights_dir":"rel"}')
        self.assertEqual((e.exception.code, e.exception.field), ("invalid", "$.weights_dir"))

    def test_reader_limits(self):
        line = encode({"type": "shutdown", "id": 1})
        reader = cfa4_ai.MessageReader(io.BytesIO(b"\n  \n" + line))
        self.assertEqual(reader.next_message()["type"], "shutdown")
        self.assertIsNone(reader.next_message())
        with self.assertRaises(ProtocolError) as e:
            cfa4_ai.MessageReader(io.BytesIO(line[:-1])).next_message()
        self.assertEqual(e.exception.code, "truncated")
        with self.assertRaises(ProtocolError) as e:
            cfa4_ai.MessageReader(io.BytesIO(b" " * cfa4_ai.MAX_LINE_BYTES + b"\n")).next_message()
        self.assertEqual(e.exception.code, "line_too_long")

    def test_negotiation(self):
        self.assertEqual(cfa4_ai.negotiate(1, 3), 2)
        self.assertEqual(cfa4_ai.negotiate(1, 1), 1)
        self.assertEqual(cfa4_ai.negotiate(2, 3), 2)
        self.assertIsNone(cfa4_ai.negotiate(3, 4))
        self.assertIsNone(cfa4_ai.negotiate(0, 0, 0, 1))
        self.assertTrue(cfa4_ai.accepts(1, 3, 1))
        self.assertFalse(cfa4_ai.accepts(0, 1, 0))


@unittest.skipUnless(os.path.isdir("/dev/shm"), "needs /dev/shm")
class ExampleWorkerSession(unittest.TestCase):
    """Plays the host against python/examples/invert_worker.py."""

    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        os.chmod(self.dir.name, 0o700)
        path = os.path.join(self.dir.name, "s")
        self.server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.server.bind(path)
        self.server.listen(1)
        self.server.settimeout(20)
        env = dict(os.environ, CFA4_AI_SOCKET=path,
                   PYTHONPATH=str(ROOT / "python" / "src"))
        self.proc = subprocess.Popen([sys.executable, str(ROOT / "python" / "examples" / "invert_worker.py")],
                                     env=env)
        self.conn, _ = self.server.accept()
        self.conn.settimeout(20)
        self.reader = cfa4_ai.MessageReader(self.conn.makefile("rb"))
        self.segments = []
        self.next_id = 0

    def tearDown(self):
        self.conn.close()
        self.server.close()
        if self.proc.poll() is None:
            self.proc.kill()
        self.proc.wait()
        for name in self.segments:
            try:
                os.unlink(f"/dev/shm/{name[1:]}")
            except FileNotFoundError:
                pass
        self.dir.cleanup()

    def send(self, message):
        message["id"] = self.next_id
        self.next_id += 1
        self.conn.sendall(encode(message))
        return message["id"]

    def receive(self, *skip):
        while True:
            message = self.reader.next_message()
            if message is None or message["type"] not in skip:
                return message

    def segment(self, data):
        name = f"/cfa4-ai-test-{uuid.uuid4().hex[:12]}"
        self.segments.append(name)
        with open(f"/dev/shm/{name[1:]}", "wb") as f:
            f.write(data)
        return name

    def frame_buffer(self, name, length, frames=1):
        return {"shm": name, "offset": 0, "len": length, "kind": "frame", "width": 2,
                "height": 2, "stride": 6, "frames": frames, "format": "rgb8"}

    def handshake(self):
        self.send({"type": "hello", "id": 0, "protocol": {"min": 1, "max": 2}, "host": "test"})
        caps = self.receive()
        self.assertEqual((caps["type"], caps["protocol"], caps["impls"]), ("caps", 2, ["invert-rgb8"]))
        self.assertEqual(caps["features"], ["cancel", "progress"])
        self.send({"type": "load", "id": 0, "impl": "invert-rgb8", "device": "cpu"})
        self.assertEqual(self.receive()["type"], "loaded")

    def run_job(self, job, src, dst, frames=1):
        return self.send({"type": "run", "id": 0, "job": job, "impl": "invert-rgb8", "device": "cpu",
                          "inputs": {"src": self.frame_buffer(src, 12 * frames, frames)},
                          "outputs": {"out": self.frame_buffer(dst, 12 * frames, frames)},
                          "params": {}, "tier": "final"})

    def test_whole_session(self):
        self.handshake()
        pixels = bytes(range(12)) * 3
        src, dst = self.segment(pixels), self.segment(bytes(36))
        run_id = self.run_job("j-1", src, dst, frames=3)
        result = self.receive("progress")
        self.assertEqual((result["type"], result["reply_to"], result["job"]), ("result", run_id, "j-1"))
        with open(f"/dev/shm/{dst[1:]}", "rb") as f:
            self.assertEqual(f.read(), bytes(255 - b for b in pixels))

        # The job slot (max_jobs = 2) is free as soon as the reply arrives: run back to back.
        for i in range(4):
            self.run_job(f"k-{i}", src, dst, frames=3)
            self.assertEqual(self.receive("progress")["type"], "result")
        self.run_job("k-a", src, dst, frames=3)
        self.run_job("k-b", src, dst, frames=3)
        replies = [self.receive("progress"), self.receive("progress")]
        self.assertEqual(sorted(r["type"] for r in replies), ["result", "result"])

        # Frame counts must match.
        self.send({"type": "run", "id": 0, "job": "j-f", "impl": "invert-rgb8", "device": "cpu",
                   "inputs": {"src": self.frame_buffer(src, 12, 1)},
                   "outputs": {"out": self.frame_buffer(dst, 36, 3)}, "params": {}, "tier": "final"})
        self.assertEqual(self.receive("progress")["code"], "invalid_input")

        # A buffer outside its segment is invalid input, and the worker keeps serving.
        short = self.segment(bytes(4))
        self.run_job("j-2", short, dst)
        error = self.receive("progress")
        self.assertEqual((error["type"], error["code"], error["job"]), ("error", "invalid_input", "j-2"))

        # A GPU is not offered by this worker.
        self.send({"type": "load", "id": 0, "impl": "invert-rgb8", "device": 0})
        self.assertEqual(self.receive()["code"], "unsupported")

        self.send({"type": "unload", "id": 0, "impl": "invert-rgb8"})
        stats = self.receive()
        self.assertEqual((stats["type"], stats["loaded"]), ("stats", []))
        self.run_job("j-3", src, dst)
        self.assertEqual(self.receive()["code"], "unsupported")

        self.send({"type": "shutdown", "id": 0})
        self.assertEqual(self.proc.wait(timeout=20), 0)

    def test_invalid_host_message_closes_with_protocol_error(self):
        self.handshake()
        self.conn.sendall(b'{"type":"teleport","id":9}\n')
        error = self.receive()
        self.assertEqual((error["type"], error["code"]), ("error", "protocol"))
        self.assertEqual(self.proc.wait(timeout=20), 2)

    def test_unpaired_surrogate_gets_a_protocol_error(self):
        self.handshake()
        self.conn.sendall(b'{"type":"shutdown","id":1,"\\ud800":0}\n')
        error = self.receive()
        self.assertEqual((error["type"], error["code"]), ("error", "protocol"))
        self.assertEqual(self.proc.wait(timeout=20), 2)

    def test_deeply_nested_message_gets_a_protocol_error(self):
        self.handshake()
        self.conn.sendall(b'{"type":' + b"[" * 500 + b"]" * 500 + b',"id":1}\n')
        self.assertEqual(self.receive()["code"], "protocol")
        self.assertEqual(self.proc.wait(timeout=20), 2)

    def test_message_before_hello_is_refused(self):
        self.send({"type": "shutdown", "id": 0})
        self.assertEqual(self.receive()["code"], "protocol")
        self.assertEqual(self.proc.wait(timeout=20), 2)


class CapsVersions(unittest.TestCase):
    """Version 2 caps fields are sent only when version 2 is negotiated."""

    class Paid(cfa4_ai.Worker):
        impls = ("upscale", "watermark")
        limits = {"max_jobs": 1, "watermark_above_height": 1080}
        features = ("cancel", "progress")
        post_export = "watermark"

    def caps_for(self, host_max):
        from cfa4_ai.worker import _Loop

        host, worker = socket.socketpair()
        thread = threading.Thread(target=lambda: _Loop(self.Paid(), worker).serve(), daemon=True)
        thread.start()
        reader = cfa4_ai.MessageReader(host.makefile("rb"))
        host.sendall(encode({"type": "hello", "id": 0, "protocol": {"min": 1, "max": host_max},
                             "host": "t"}))
        caps = reader.next_message()
        host.sendall(encode({"type": "shutdown", "id": 1}))
        thread.join(timeout=10)
        host.close()
        worker.close()
        return caps

    def test_version_2(self):
        caps = self.caps_for(2)
        self.assertEqual(caps["protocol"], 2)
        self.assertEqual(caps["features"], ["cancel", "progress"])
        self.assertEqual(caps["post_export"], "watermark")
        self.assertEqual(caps["limits"]["watermark_above_height"], 1080)

    def test_version_1_host(self):
        caps = self.caps_for(1)
        self.assertEqual(caps["protocol"], 1)
        self.assertNotIn("features", caps)
        self.assertNotIn("post_export", caps)
        self.assertEqual(caps["limits"], {"max_jobs": 1})
        self.assertEqual(self.Paid.limits["watermark_above_height"], 1080)

    def test_version_1_rejects_version_2_fields(self):
        caps = {"type": "caps", "id": 0, "reply_to": 0, "protocol": 1,
                "worker": {"name": "w", "version": "1"}, "impls": ["a"],
                "limits": {"max_jobs": 1}}
        decode(json.dumps(caps))
        for key, value in [("features", ["cancel"]), ("post_export", "a")]:
            with self.subTest(key):
                with self.assertRaises(ProtocolError):
                    decode(json.dumps({**caps, key: value}))
        with self.assertRaises(ProtocolError):
            decode(json.dumps({**caps, "limits": {"max_jobs": 1, "watermark_above_height": 1}}))
        decode(json.dumps({**caps, "protocol": 2, "features": ["cancel"], "post_export": "a"}))


class UnloadFailure(unittest.TestCase):
    """A failed unload keeps the model listed, so the host can retry."""

    def test_failed_unload_keeps_residency(self):
        from cfa4_ai.worker import _Loop

        class Flaky(cfa4_ai.Worker):
            impls = ("m",)
            fail = True

            def load(self, impl, device, precision, weights_dir):
                return 10

            def unload(self, impl, device):
                if Flaky.fail:
                    Flaky.fail = False
                    raise RuntimeError("driver busy")

        host, worker = socket.socketpair()
        thread = threading.Thread(target=lambda: _Loop(Flaky(), worker).serve(), daemon=True)
        thread.start()
        reader = cfa4_ai.MessageReader(host.makefile("rb"))
        for message in [{"type": "hello", "id": 0, "protocol": {"min": 1, "max": 1}, "host": "t"},
                        {"type": "load", "id": 1, "impl": "m", "device": "cpu"},
                        {"type": "unload", "id": 2, "impl": "m"}]:
            host.sendall(encode(message))
        self.assertEqual([reader.next_message()["type"] for _ in range(2)], ["caps", "loaded"])
        error, stats = reader.next_message(), reader.next_message()
        self.assertEqual((error["code"], stats["loaded"][0]["impl"]), ("model_error", "m"))
        host.sendall(encode({"type": "unload", "id": 3, "impl": "m"}))
        self.assertEqual(reader.next_message()["loaded"], [])
        host.sendall(encode({"type": "shutdown", "id": 4}))
        thread.join(timeout=10)
        host.close()
        worker.close()


if __name__ == "__main__":
    unittest.main()
