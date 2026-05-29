from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class FieldRef:
    state_cls: type[Any]
    name: str

    @property
    def annotation(self) -> Any:
        return self.state_cls.model_fields[self.name].annotation
