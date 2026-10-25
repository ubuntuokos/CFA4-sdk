# SPDX-License-Identifier: MIT OR Apache-2.0
"""Schema checks: the schemas are valid, the examples pass, broken input fails."""

import copy
import json
import tomllib
import unittest
from pathlib import Path

from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parent.parent
SCHEMAS = ROOT / "schemas"
EXAMPLES = ROOT / "examples"


def load_schema(name):
    schema = json.loads((SCHEMAS / name).read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema)


def jsonl(path):
    lines = path.read_text(encoding="utf-8").splitlines()
    return [json.loads(line) for line in lines if line.strip()]


class ManifestSchema(unittest.TestCase):
    validator = load_schema("manifest.schema.json")

    def manifests(self):
        paths = sorted((EXAMPLES / "manifests").glob("*.toml"))
        self.assertTrue(paths, "no example manifests")
        return [(p, tomllib.loads(p.read_text(encoding="utf-8"))) for p in paths]

    def assert_invalid(self, manifest, why):
        errors = list(self.validator.iter_errors(manifest))
        self.assertTrue(errors, f"accepted: {why}")

    def test_examples_are_valid(self):
        for path, manifest in self.manifests():
            with self.subTest(path.name):
                errors = [e.message for e in self.validator.iter_errors(manifest)]
                self.assertEqual(errors, [])

    def test_broken_manifests_are_rejected(self):
        base = dict(self.manifests())[EXAMPLES / "manifests" / "bgswap-onnx.toml"]
        cases = {
            "id outside the 200-type list format": ("capability", "id", "AI-76"),
            "unknown scope": ("capability", "scope", "everything"),
            "unknown runtime": ("runtime", "kind", "tensorflow"),
            "bad resolution key": ("resources", "vram_mb", {"huge": 100}),
            "negative VRAM": ("resources", "vram_mb", {"1080p": -1}),
            "commercial flag missing type": ("license", "commercial", "yes"),
        }
        for why, (section, key, value) in cases.items():
            with self.subTest(why):
                broken = copy.deepcopy(base)
                broken[section][key] = value
                self.assert_invalid(broken, why)

        broken = copy.deepcopy(base)
        del broken["capability"]["window"]
        self.assert_invalid(broken, "window scope without window")

        broken = copy.deepcopy(base)
        broken["weights"][0]["file"] = "../../etc/passwd"
        self.assert_invalid(broken, "weights path escaping the model folder")

        broken = copy.deepcopy(base)
        del broken["license"]["model"]
        self.assert_invalid(broken, "model licence missing")

        broken = copy.deepcopy(base)
        broken["capability"]["surprise"] = 1
        self.assert_invalid(broken, "unknown key")


class ProtocolSchema(unittest.TestCase):
    validator = load_schema("protocol.schema.json")

    def test_session_example_is_valid(self):
        for n, message in enumerate(jsonl(EXAMPLES / "messages" / "session.jsonl"), 1):
            with self.subTest(line=n, type=message.get("type")):
                errors = [e.message for e in self.validator.iter_errors(message)]
                self.assertEqual(errors, [])

    def test_full_example_is_valid(self):
        for n, message in enumerate(jsonl(EXAMPLES / "messages" / "full.jsonl"), 1):
            with self.subTest(line=n, type=message.get("type")):
                errors = [e.message for e in self.validator.iter_errors(message)]
                self.assertEqual(errors, [])

    def test_session_example_covers_every_message_type(self):
        schema = self.validator.schema
        defined = {schema["$defs"][ref["$ref"].rsplit("/", 1)[-1]]["properties"]["type"]["const"]
                   for ref in schema["oneOf"]}
        used = {m["type"] for m in jsonl(EXAMPLES / "messages" / "session.jsonl")}
        self.assertEqual(defined, used)

    def test_full_example_uses_every_property(self):
        """full.jsonl sets every optional field, so typed SDKs round-trip all of them."""
        defs = self.validator.schema["$defs"]
        messages = jsonl(EXAMPLES / "messages" / "full.jsonl")
        for ref in self.validator.schema["oneOf"]:
            name = ref["$ref"].rsplit("/", 1)[-1]
            kind = defs[name]["properties"]["type"]["const"]
            used = set().union(*(m.keys() for m in messages if m["type"] == kind))
            with self.subTest(type=kind):
                self.assertEqual(set(defs[name]["properties"]), used)
        buffers = [b for m in messages for key in ("inputs", "outputs") for b in m.get(key, {}).values()]
        self.assertEqual(set(defs["buffer"]["properties"]), set().union(*(b.keys() for b in buffers)))

    def test_invalid_messages_are_rejected(self):
        for n, message in enumerate(jsonl(EXAMPLES / "messages" / "invalid.jsonl"), 1):
            with self.subTest(line=n, type=message.get("type")):
                self.assertFalse(self.validator.is_valid(message))


if __name__ == "__main__":
    unittest.main()
