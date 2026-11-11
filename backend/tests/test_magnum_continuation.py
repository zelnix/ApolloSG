import pytest
from services.higgins.ai_request import Part
from services.higgins.magnum_continuation import plan_batches

def rebuild(batches, count):
    outputs = [""] * count
    for batch in batches:
        for part, (index, start, end) in zip(batch.parts, batch.source_spans):
            assert part.text is not None
            assert len(part.text) == end - start
            outputs[index] += part.text
    return outputs

def test_long_sources_lossless_and_bounded():
    sources = ["invoice " * 3000, "urgent? " * 4000, "A" * 10000]
    batches = plan_batches([Part(text=s) for s in sources])
    assert 1 < len(batches) <= 4
    assert rebuild(batches, len(sources)) == sources
    assert len({b.digest for b in batches}) == len(batches)

def test_too_many_windows_fails_closed():
    with pytest.raises(ValueError, match="magnum_window_budget_exceeded"):
        plan_batches([Part(text="abc " * 40000)])

def test_binary_is_not_split():
    data = b"binary" * 100
    batches = plan_batches([Part.from_bytes(data=data, mime_type="image/png")])
    assert len(batches) == 1
    assert batches[0].parts[0].data == data

def test_oversized_binary_is_rejected():
    with pytest.raises(ValueError, match="oversized_binary_evidence"):
        plan_batches([Part.from_bytes(data=b"x" * 30001, mime_type="image/png")])

def test_whitespace_and_long_tokens_preserved():
    value = "x" * 5000 + "\n\t  " + "a b c " * 100
    batches = plan_batches([Part(text=value)])
    assert rebuild(batches, 1) == [value]
