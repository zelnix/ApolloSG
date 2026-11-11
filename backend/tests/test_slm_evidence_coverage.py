"""FR-05 source coverage tests without database, native model or network."""
import ast
import asyncio
import unittest
from pathlib import Path
from types import SimpleNamespace


class EvidenceError(Exception):
    def __init__(self, status, code, message):
        super().__init__(message)
        self.status = status
        self.code = code


def load_source():
    path = Path(__file__).resolve().parents[1] / "routers/slm_handoff.py"
    tree = ast.parse(path.read_text())
    node = next(n for n in tree.body if isinstance(n, ast.AsyncFunctionDef) and n.name == "_source_evidence")
    store = SimpleNamespace(rows=[], data={})
    async def list_evidence(_owner, _case):
        return store.rows
    async def read_bytes(_owner, _case, evidence_id):
        return store.data[evidence_id].encode()
    scope = {"repo": SimpleNamespace(list_evidence=list_evidence, read_bytes=read_bytes),
             "SLMReference": lambda evidence_id, text: SimpleNamespace(evidence_id=evidence_id, text=text),
             "http": lambda status, code, message: EvidenceError(status, code, message)}
    exec(compile(ast.Module(body=[node], type_ignores=[]), str(path), "exec"), scope)
    return scope["_source_evidence"], store


class EvidenceCoverageTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.source, self.store = load_source()

    def add(self, evidence_id, kind, text=None, **other):
        self.store.rows.append({**{"evidence_id": evidence_id, "kind": kind,
                                  "origin": "user_submission", "availability": "available"}, **other})
        if text is not None:
            self.store.data[evidence_id] = text

    async def test_text_from_image_has_parent_provenance(self):
        self.add("IMG-1", "image")
        self.add("OCR-1", "text", "Invoice amount 500", parent_id="IMG-1")
        refs = await self.source("owner", "case")
        self.assertEqual(len(refs), 1)
        self.assertEqual(refs[0].evidence_id, "OCR-1")
        self.assertIn("image evidence IMG-1", refs[0].text)
        self.assertIn("original binary not examined by SLM", refs[0].text)

    async def test_unsupported_original_blocks_final_finding(self):
        self.add("DOC-1", "document")
        self.add("TEXT-1", "text", "Excerpt", parent_id="DOC-1")
        with self.assertRaises(EvidenceError) as raised:
            await self.source("owner", "case", include_checks=True)
        self.assertEqual(raised.exception.status, 422)
        self.assertEqual(raised.exception.code, "unsupported_evidence")

    async def test_unrelated_text_not_mislabeled(self):
        self.add("TEXT-1", "text", "Ordinary user message")
        refs = await self.source("owner", "case")
        self.assertEqual(refs[0].text, "Ordinary user message")

    async def test_derived_text_budget_not_silently_truncated(self):
        self.add("IMG-1", "image")
        self.add("OCR-1", "text", "X" * 120000, parent_id="IMG-1")
        with self.assertRaises(EvidenceError) as raised:
            await self.source("owner", "case")
        self.assertEqual(raised.exception.status, 413)

    async def test_missing_binary_parent_is_not_claimed_as_seen(self):
        self.add("AUDIO-1", "audio", availability="unavailable")
        self.add("TRANSCRIPT-1", "text", "Recorded voice", parent_id="AUDIO-1")
        refs = await self.source("owner", "case")
        self.assertIn("audio evidence AUDIO-1", refs[0].text)


if __name__ == "__main__":
    unittest.main()
