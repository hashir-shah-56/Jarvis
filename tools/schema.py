"""Validate the JSON Schema subset used by the approved tools, without coercion.

Defaults are annotations: omitted arguments stay omitted so Python applies the
implementation's defaults. Unsupported schema features fail closed, even on an
omitted property. This is deliberately not a general JSON Schema implementation.
"""

from collections.abc import Mapping


class ArgumentValidationError(ValueError):
    """A contract rejection that never includes caller values."""

    def __init__(self) -> None:
        super().__init__("INVALID_TOOL_ARGUMENTS")


def _check_schema(schema: Mapping[str, object]) -> None:
    allowed = {
        "object": {"type", "properties", "required", "additionalProperties", "default", "enum"},
        "string": {"type", "minLength", "maxLength", "default", "enum"},
        "integer": {"type", "minimum", "maximum", "default", "enum"},
    }
    kind = schema["type"]
    if kind not in allowed or set(schema) - allowed[kind]:
        raise ValueError("INVALID_TOOL_SCHEMA")
    if kind == "object":
        properties = schema["properties"]
        required = schema["required"]
        if (
            not isinstance(properties, Mapping)
            or any(type(key) is not str for key in properties)
            or type(required) is not list
            or any(type(key) is not str or key not in properties for key in required)
            or schema["additionalProperties"] is not False
        ):
            raise ValueError("INVALID_TOOL_SCHEMA")
        for definition in properties.values():
            _check_schema(definition)
    for lower, upper in (("minLength", "maxLength"), ("minimum", "maximum")):
        for key in (lower, upper):
            if key in schema and (
                type(schema[key]) is not int
                or (key in {"minLength", "maxLength"} and schema[key] < 0)
            ):
                raise ValueError("INVALID_TOOL_SCHEMA")
        if lower in schema and upper in schema and schema[lower] > schema[upper]:
            raise ValueError("INVALID_TOOL_SCHEMA")
    if "enum" in schema and (type(schema["enum"]) is not list or not schema["enum"]):
        raise ValueError("INVALID_TOOL_SCHEMA")
    if "default" in schema:
        try:
            _validate_value(schema["default"], schema)
        except ArgumentValidationError:
            raise ValueError("INVALID_TOOL_SCHEMA") from None


def _validate_value(value: object, schema: Mapping[str, object]) -> object:
    kind = schema["type"]
    if kind == "object":
        if not isinstance(value, Mapping):
            raise ArgumentValidationError()
        value = dict(value)
        properties = schema["properties"]
        if (
            any(type(key) is not str or key not in properties for key in value)
            or any(key not in value for key in schema["required"])
        ):
            raise ArgumentValidationError()
        value = {key: _validate_value(item, properties[key]) for key, item in value.items()}
    elif kind == "string":
        if type(value) is not str:
            raise ArgumentValidationError()
        if len(value) < schema.get("minLength", 0) or (
            "maxLength" in schema and len(value) > schema["maxLength"]
        ):
            raise ArgumentValidationError()
    elif kind == "integer":
        # bool is an int subclass in Python, but never an integer tool argument.
        if type(value) is not int:
            raise ArgumentValidationError()
        if ("minimum" in schema and value < schema["minimum"]) or (
            "maximum" in schema and value > schema["maximum"]
        ):
            raise ArgumentValidationError()
    if "enum" in schema and not any(
        type(value) is type(option) and value == option for option in schema["enum"]
    ):
        raise ArgumentValidationError()
    return value


def validate_arguments(arguments: object, schema: Mapping[str, object]) -> dict[str, object]:
    """Return a validated copy; reject malformed payloads and never add defaults."""
    _check_schema(schema)
    if schema["type"] != "object":
        raise ValueError("INVALID_TOOL_SCHEMA")
    return _validate_value(arguments, schema)
