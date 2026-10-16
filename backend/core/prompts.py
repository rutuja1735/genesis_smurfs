"""Prompt serialization helpers. Tool output always enters as sanitized data."""

from __future__ import annotations

import json
from typing import Any


def json_text(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)


def untrusted_block(value: Any) -> str:
    # Prevent content from terminating the wrapper while leaving neutralizer
    # annotations readable to the model.
    payload = json_text(value).replace("</untrusted_data", "<\\/untrusted_data")
    return f"<untrusted_data>\n{payload}\n</untrusted_data>"


def unknown_value(value: Any) -> bool:
    return isinstance(value, str) and value.strip().startswith("<unknown>")
