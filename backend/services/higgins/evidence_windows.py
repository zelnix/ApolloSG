"""Bounded, lossless text evidence windows for Wright/Higgins continuation.

Pure preparation: no provider calls, database writes, verdicts or evidence promotion.
Offsets are Python Unicode character offsets, not UTF-8 byte offsets.
"""
from __future__ import annotations
from dataclasses import dataclass

@dataclass(frozen=True)
class Window:
    evidence_id: str
    start: int
    end: int
    text: str

    @property
    def window_id(self) -> str:
        return f"{self.evidence_id}:chars:{self.start}-{self.end}"

@dataclass(frozen=True)
class WindowInventory:
    windows: tuple[Window, ...]
    total_characters: int
    complete: bool


def build_windows(sources: list[tuple[str, str]], *, max_chars: int = 1600, overlap: int = 160) -> WindowInventory:
    if not 256 <= max_chars <= 4000 or not 0 <= overlap < max_chars // 2:
        raise ValueError("invalid_window_budget")
    ids: set[str] = set()
    windows: list[Window] = []
    total = 0
    for evidence_id, text in sources:
        if not isinstance(evidence_id, str) or not evidence_id or evidence_id in ids or not isinstance(text, str):
            raise ValueError("invalid_evidence_source")
        ids.add(evidence_id)
        total += len(text)
        start = 0
        while start < len(text):
            end = min(len(text), start + max_chars)
            windows.append(Window(evidence_id, start, end, text[start:end]))
            if end == len(text):
                break
            start = end - overlap
    return WindowInventory(tuple(windows), total, True)


def validate_window_coverage(sources: list[tuple[str, str]], inventory: WindowInventory,
                             examined_window_ids: set[str]) -> bool:
    """Only mark complete when every source span has a successful, cited examination."""
    by_id = {evidence_id: text for evidence_id, text in sources}
    if len(by_id) != len(sources) or not inventory.complete:
        return False
    if inventory.total_characters != sum(len(text) for text in by_id.values()):
        return False
    for evidence_id, text in sources:
        cursor = 0
        for window in sorted((w for w in inventory.windows if w.evidence_id == evidence_id),
                             key=lambda w: (w.start, w.end)):
            if window.window_id not in examined_window_ids or window.start > cursor or window.end > len(text):
                return False
            if text[window.start:window.end] != window.text:
                return False
            cursor = max(cursor, window.end)
        if cursor != len(text):
            return False
    return True
