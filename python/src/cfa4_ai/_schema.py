# SPDX-License-Identifier: MIT OR Apache-2.0
"""A validator for the JSON Schema keywords that ``protocol.schema.json`` uses.

The SDK has no dependencies, so that it installs into any model environment
without version conflicts. This module implements only the keywords the
protocol schema needs; an unknown keyword raises ``SchemaError`` so that a
schema change cannot be silently ignored. ``tests/test_python_sdk.py`` checks
that it agrees with the reference ``jsonschema`` package.
"""

import re

_ANNOTATIONS = {"$schema", "$id", "$defs", "title", "description"}
_KNOWN = _ANNOTATIONS | {
    "$ref", "type", "const", "enum", "properties", "required", "additionalProperties",
    "propertyNames", "items", "uniqueItems", "minimum", "maximum", "exclusiveMinimum",
    "maxLength", "pattern", "oneOf", "if", "then",
}


class SchemaError(Exception):
    """The schema uses a keyword this validator does not implement."""


def _is_type(value, name):
    if name == "object":
        return isinstance(value, dict)
    if name == "array":
        return isinstance(value, list)
    if name == "string":
        return isinstance(value, str)
    if name == "boolean":
        return isinstance(value, bool)
    if name == "null":
        return value is None
    if isinstance(value, bool):
        return False
    if name == "integer":
        return isinstance(value, int) or (isinstance(value, float) and value.is_integer())
    if name == "number":
        return isinstance(value, (int, float))
    raise SchemaError(f"unknown type {name!r}")


def _canonical(value):
    """A hashable form in which JSON-equal values are equal (``1 == 1.0``, ``true != 1``)."""
    if isinstance(value, bool) or value is None or isinstance(value, str):
        return (type(value).__name__, value)
    if isinstance(value, (int, float)):
        return ("number", int(value) if isinstance(value, float) and value.is_integer() else value)
    if isinstance(value, list):
        return ("array", tuple(_canonical(v) for v in value))
    if isinstance(value, dict):
        return ("object", tuple(sorted((k, _canonical(v)) for k, v in value.items())))
    raise SchemaError(f"not a JSON value: {type(value).__name__}")


def _json_equal(a, b):
    return _canonical(a) == _canonical(b)


class Validator:
    def __init__(self, schema):
        self.root = schema
        self._patterns = {}

    def _resolve(self, ref):
        if not ref.startswith("#/"):
            raise SchemaError(f"only local references are supported: {ref}")
        node = self.root
        for part in ref[2:].split("/"):
            node = node[part]
        return node

    def _pattern(self, pattern):
        compiled = self._patterns.get(pattern)
        if compiled is None:
            compiled = self._patterns[pattern] = re.compile(pattern)
        return compiled

    def errors(self, value, schema=None, path="$"):
        """Yields ``(path, reason)`` for every violation."""
        schema = self.root if schema is None else schema
        if schema is True:
            return
        if schema is False:
            yield path, "not allowed"
            return
        unknown = set(schema) - _KNOWN
        if unknown:
            raise SchemaError(f"unsupported keywords: {sorted(unknown)}")
        if "$ref" in schema:
            yield from self.errors(value, self._resolve(schema["$ref"]), path)
        if "type" in schema:
            types = schema["type"] if isinstance(schema["type"], list) else [schema["type"]]
            if not any(_is_type(value, t) for t in types):
                yield path, f"expected {'/'.join(types)}"
                return
        if "const" in schema and not _json_equal(value, schema["const"]):
            yield path, f"must be {schema['const']!r}"
        if "enum" in schema and not any(_json_equal(value, e) for e in schema["enum"]):
            yield path, f"must be one of {schema['enum']}"
        if isinstance(value, dict):
            yield from self._object(value, schema, path)
        if isinstance(value, list):
            yield from self._array(value, schema, path)
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            if "minimum" in schema and value < schema["minimum"]:
                yield path, f"must be at least {schema['minimum']}"
            if "maximum" in schema and value > schema["maximum"]:
                yield path, f"must be at most {schema['maximum']}"
            if "exclusiveMinimum" in schema and value <= schema["exclusiveMinimum"]:
                yield path, f"must be greater than {schema['exclusiveMinimum']}"
        if isinstance(value, str):
            if "maxLength" in schema and len(value) > schema["maxLength"]:
                yield path, f"longer than {schema['maxLength']} characters"
            if "pattern" in schema and not self._pattern(schema["pattern"]).search(value):
                yield path, f"must match {schema['pattern']}"
        if "oneOf" in schema:
            matching = [s for s in schema["oneOf"] if self.is_valid(value, s)]
            if len(matching) > 1:
                yield path, f"matches {len(matching)} of the alternatives, not exactly one"
            elif not matching:
                chosen = self._discriminated(value, schema["oneOf"])
                if chosen is None:
                    yield path, "matches none of the alternatives"
                else:
                    yield from self.errors(value, chosen, path)
        if "if" in schema and self.is_valid(value, schema["if"]):
            yield from self.errors(value, schema.get("then", True), path)

    def _discriminated(self, value, alternatives):
        """The one alternative whose ``type`` constant names this message, if any."""
        if not isinstance(value, dict):
            return None
        found = []
        for alternative in alternatives:
            target = self._resolve(alternative["$ref"]) if "$ref" in alternative else alternative
            const = target.get("properties", {}).get("type", {}).get("const")
            if const is not None and const == value.get("type"):
                found.append(alternative)
        return found[0] if len(found) == 1 else None

    def _object(self, value, schema, path):
        properties = schema.get("properties", {})
        for name in schema.get("required", []):
            if name not in value:
                yield f"{path}.{name}", "required"
        for name, item in value.items():
            if "propertyNames" in schema:
                for _, reason in self.errors(name, schema["propertyNames"], path):
                    yield f"{path}.{name}", f"name {reason}"
            if name in properties:
                yield from self.errors(item, properties[name], f"{path}.{name}")
            elif "additionalProperties" in schema:
                yield from self.errors(item, schema["additionalProperties"], f"{path}.{name}")

    def _array(self, value, schema, path):
        if "items" in schema:
            for i, item in enumerate(value):
                yield from self.errors(item, schema["items"], f"{path}[{i}]")
        if schema.get("uniqueItems"):
            seen = set()
            for item in value:
                key = _canonical(item)
                if key in seen:
                    yield path, "items must be unique"
                    break
                seen.add(key)

    def is_valid(self, value, schema=None):
        return next(iter(self.errors(value, schema)), None) is None
