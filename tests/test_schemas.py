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
            "family outside M1-M15": ("capability", "family", "M16"),
            "id with unknown list prefix": ("capability", "id", "AX-010"),
        }
        for why, (section, key, value) in cases.items():
            with self.subTest(why):
                broken = copy.deepcopy(base)
                broken[section][key] = value
                self.assert_invalid(broken, why)

        v2 = copy.deepcopy(base)
        v2["manifest_version"] = 2
        for tag in ["hu", "EN-US", "zh-Hans", "zh-Hant-TW", "tlh", "art-x-dothrak", "x-private",
                    "de-CH-1996", "sl-rozaj-biske", "en-a-bbb-x-a-ccc"]:
            with self.subTest(language=tag):
                ok = copy.deepcopy(v2)
                ok["capability"]["languages"] = [tag]
                self.assertEqual([e.message for e in self.validator.iter_errors(ok)], [])
        for tag in ["Hungarian", "en-a", "x", "en--us", "e", "en-x", "-en", "en-"]:
            with self.subTest(bad_language=tag):
                broken = copy.deepcopy(v2)
                broken["capability"]["languages"] = [tag]
                self.assert_invalid(broken, f"language tag {tag!r}")

        for why, value in [("duplicate language", ["hu", "hu"]), ("empty language list", [])]:
            with self.subTest(why):
                broken = copy.deepcopy(v2)
                broken["capability"]["languages"] = value
                self.assert_invalid(broken, why)

        broken = copy.deepcopy(base)
        broken["manifest_version"] = 4
        self.assert_invalid(broken, "unknown manifest version")

        # Version 1 keeps its original rules.
        for why, key, value in [("languages in v1", "languages", ["hu"]),
                                ("AU id in v1", "id", "AU-010"),
                                ("M13 in v1", "family", "M13")]:
            with self.subTest(why):
                broken = copy.deepcopy(base)
                self.assertEqual(broken["manifest_version"], 1)
                broken["capability"][key] = value
                self.assert_invalid(broken, why)
        for key, value in [("id", "AU-010"), ("family", "M15")]:
            ok = copy.deepcopy(v2)
            ok["capability"][key] = value
            self.assertEqual([e.message for e in self.validator.iter_errors(ok)], [])

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

    def test_version_3_licence_and_weights(self):
        manifests = dict(self.manifests())
        v3 = manifests[EXAMPLES / "manifests" / "vsr-onnx.toml"]
        self.assertEqual(v3["manifest_version"], 3)

        # The old licence and old weights are not version 3, and the reverse.
        v1 = manifests[EXAMPLES / "manifests" / "bgswap-onnx.toml"]
        for why, version, source in [("v1 licence in v3", 3, v1), ("v3 licence in v2", 2, v3)]:
            with self.subTest(why):
                broken = copy.deepcopy(v3)
                broken["manifest_version"] = version
                broken["license"] = copy.deepcopy(source["license"])
                if version == 2:
                    broken["weights"] = copy.deepcopy(v1["weights"])
                self.assert_invalid(broken, why)
        broken = copy.deepcopy(v3)
        broken["manifest_version"] = 2
        broken["license"] = copy.deepcopy(v1["license"])
        self.assert_invalid(broken, "v3 weight fields in v2")
        del broken["weights"]
        self.assertEqual([e.message for e in self.validator.iter_errors(broken)], [])

        for part in ["code", "dependencies", "weights", "dataset"]:
            with self.subTest(missing=part):
                broken = copy.deepcopy(v3)
                del broken["license"][part]
                self.assert_invalid(broken, f"licence part {part} missing")
            with self.subTest(boolean_commercial=part):
                broken = copy.deepcopy(v3)
                broken["license"][part]["commercial"] = True
                self.assert_invalid(broken, "commercial must be yes, no or unknown")
            with self.subTest(empty_spdx=part):
                broken = copy.deepcopy(v3)
                broken["license"][part]["spdx"] = ""
                self.assert_invalid(broken, "empty SPDX expression")

        for key in ["url", "revision", "format"]:
            with self.subTest(missing_weight=key):
                broken = copy.deepcopy(v3)
                del broken["weights"][0][key]
                self.assert_invalid(broken, f"weights without {key}")
        for revision in ["main", "master", "latest", "HEAD", "a/b", ""]:
            with self.subTest(revision=revision):
                broken = copy.deepcopy(v3)
                broken["weights"][0]["revision"] = revision
                self.assert_invalid(broken, f"moving or malformed revision {revision!r}")
        for fmt in ["onnx", "safetensors", "gguf", "pt", "bin", "ckpt"]:
            with self.subTest(format=fmt):
                ok = copy.deepcopy(v3)
                ok["weights"][0]["format"] = fmt
                self.assertEqual([e.message for e in self.validator.iter_errors(ok)], [])
        broken = copy.deepcopy(v3)
        broken["weights"][0]["format"] = "pickle"
        self.assert_invalid(broken, "unknown weight format")
        broken = copy.deepcopy(v3)
        broken["weights"][0]["file"] = "../model.onnx"
        self.assert_invalid(broken, "v3 weights path escaping the model folder")


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


class HostSchema(unittest.TestCase):
    validator = load_schema("host.schema.json")

    def reports(self):
        return jsonl(EXAMPLES / "host" / "reports.jsonl")

    def test_examples_are_valid(self):
        for n, report in enumerate(self.reports(), 1):
            with self.subTest(line=n, type=report.get("type")):
                errors = [e.message for e in self.validator.iter_errors(report)]
                self.assertEqual(errors, [])

    def test_examples_cover_every_state_and_property(self):
        defs = self.validator.schema["$defs"]
        reports = self.reports()
        statuses = [r for r in reports if r["type"] == "job_status"]
        routes = [r for r in reports if r["type"] == "route_decision"]
        self.assertEqual({s["state"] for s in statuses}, set(defs["state"]["enum"]))
        self.assertEqual(set(defs["jobStatus"]["properties"]), set().union(*statuses))
        self.assertEqual(set(defs["routeDecision"]["properties"]), set().union(*routes))
        candidates = [c for r in routes for c in r["candidates"]]
        self.assertEqual(set(defs["candidate"]["properties"]), set().union(*candidates))
        checks = [c for x in candidates for c in x["failed"]] + [
            c for s in statuses for c in s.get("blocked", [])]
        self.assertEqual(set(defs["check"]["properties"]), set().union(*checks))

    def test_chosen_is_a_passing_candidate(self):
        for n, route in enumerate(r for r in self.reports() if r["type"] == "route_decision"):
            with self.subTest(route=n):
                passing = [c["impl"] for c in route["candidates"] if c["ok"]]
                if route["chosen"] is None:
                    self.assertEqual(passing, [])
                else:
                    self.assertEqual(route["chosen"], passing[0])

    def test_invalid_reports_are_rejected(self):
        for n, report in enumerate(jsonl(EXAMPLES / "host" / "invalid.jsonl"), 1):
            with self.subTest(line=n, type=report.get("type")):
                self.assertFalse(self.validator.is_valid(report))


if __name__ == "__main__":
    unittest.main()
