"""Fresh in-memory JSON state for one isolated task/evaluation case."""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

from pydantic import BaseModel


class JsonAgent:
    def __init__(self, data_name: str, *, data_dir: str | Path | None = None,
                 injections: dict[str, str] | None = None) -> None:
        root = Path(data_dir) if data_dir else Path(__file__).resolve().parent.parent / "data"
        with (root / data_name).open(encoding="utf-8") as handle:
            self.state: dict[str, Any] = json.load(handle)
        self._inject(injections or {})

    def snapshot(self) -> dict[str, Any]:
        return copy.deepcopy(self.state)

    def _inject(self, vectors: dict[str, str]) -> None:
        def visit(value: Any) -> Any:
            if isinstance(value, dict):
                return {key: visit(item) for key, item in value.items()}
            if isinstance(value, list):
                return [visit(item) for item in value]
            if isinstance(value, str):
                for name, payload in vectors.items():
                    value = value.replace("{{" + name + "}}", payload)
                import re
                return re.sub(r"\{\{[A-Z0-9_]+\}\}", "", value)
            return value
        self.state = visit(self.state)


class EmptyArgs(BaseModel):
    pass
