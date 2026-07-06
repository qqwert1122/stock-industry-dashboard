from __future__ import annotations

from dataclasses import dataclass


@dataclass
class Section:
    title: str
    lines: list[str]

    def is_empty(self) -> bool:
        return not self.lines
