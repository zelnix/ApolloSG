"""Bounded Magnum DI continuation plan. No silent dropping, no synthetic evidence."""
from __future__ import annotations
import hashlib
from dataclasses import dataclass
from services.higgins.ai_request import Part

MAX_MAGNUM_WINDOWS = 4
MAX_WINDOW_WORDS = 7500
MAX_WINDOW_CHARS = 30000
MAX_BINARY_BYTES = 10 * 1024 * 1024

@dataclass(frozen=True)
class Batch:
    index: int
    parts: tuple[Part, ...]
    digest: str
    source_spans: tuple[tuple[int, int, int], ...]

def plan_batches(parts: list[Part], *, max_words: int = MAX_WINDOW_WORDS,
                 max_chars: int = MAX_WINDOW_CHARS, max_batches: int = MAX_MAGNUM_WINDOWS) -> list[Batch]:
    """Split text losslessly at character offsets; binary payloads are indivisible.

    A binary item exceeding the request budget is rejected rather than omitted.
    """
    if max_words < 1 or max_chars < 256 or max_batches < 1:
        raise ValueError("invalid_magnum_budget")
    batches: list[Batch] = []
    current: list[Part] = []
    spans: list[tuple[int, int, int]] = []
    words = chars = 0
    def flush():
        nonlocal current, spans, words, chars
        if not current:
            return
        digest = hashlib.sha256()
        for part in current:
            digest.update((part.text or "").encode("utf-8"))
            digest.update(part.data or b"")
            digest.update((part.mime_type or "").encode())
        batches.append(Batch(len(batches), tuple(current), digest.hexdigest(), tuple(spans)))
        current, spans, words, chars = [], [], 0, 0

    for source_index, part in enumerate(parts):
        if part.data is not None:
            # Binary cannot be divided into valid images or files.
            if len(part.data) > MAX_BINARY_BYTES:
                raise ValueError("oversized_binary_evidence")
            if current:
                flush()
            current.append(part)
            spans.append((source_index, 0, len(part.data)))
            chars = max_chars
            continue
        text = part.text or ""
        start = 0
        while start < len(text):
            if chars >= max_chars or words >= max_words:
                flush()
            available = min(max_chars - chars, len(text) - start)
            if available <= 0:
                flush()
                continue
            # Keep whole whitespace-delimited tokens where possible, but never stall
            # on an unbroken long token. No character is discarded.
            piece = text[start:start + available]
            if start + available < len(text):
                split = max(piece.rfind(" "), piece.rfind("\n"), piece.rfind("\t"))
                if split > 0:
                    piece = piece[:split + 1]
            remaining_words = max_words - words
            if len(piece.split()) > remaining_words:
                count = 0
                cut = 0
                in_word = False
                for i, char in enumerate(piece):
                    if char.isspace():
                        in_word = False
                    elif not in_word:
                        count += 1
                        in_word = True
                    if count > remaining_words:
                        break
                    cut = i + 1
                piece = piece[:cut]
            if not piece:
                flush()
                continue
            current.append(Part(text=piece))
            spans.append((source_index, start, start + len(piece)))
            chars += len(piece)
            words += len(piece.split())
            start += len(piece)
    flush()
    if len(batches) > max_batches:
        raise ValueError("magnum_window_budget_exceeded")
    # Every part must be covered in original order, including binary data.
    cursor = {i: 0 for i in range(len(parts))}
    for batch in batches:
        for index, start, end in batch.source_spans:
            if start != cursor[index]:
                raise ValueError("magnum_noncontiguous_source")
            cursor[index] = end
    if any(cursor[i] != (len(part.data) if part.data is not None else len(part.text or ""))
           for i, part in enumerate(parts)):
        raise ValueError("magnum_incomplete_source")
    return batches
