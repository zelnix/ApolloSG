"""Evidence ingress: inventory, secret handling, safe extraction, coverage ledger and model-context parts (spec §6).

Originals are stored as encrypted chunks for the case lifetime only. Extraction never executes content.
"""
from __future__ import annotations

import io
import json
import re
import uuid
import zipfile
from datetime import datetime
from typing import Optional

from services.higgins.ai_request import Part

from core.db import now_utc
from core.redaction import redact_investigation_secrets
from services.higgins import repository as repo
from services.higgins.contracts import Coverage, EvidenceItem, OmittedRange, Range, Transformation
from services.higgins.repository import http

MAX_FILE_BYTES = 10 * 1024 * 1024
MAX_CASE_BYTES = 64 * 1024 * 1024
MAX_PAGES = 200
MAX_IMAGE_PIXELS = 40_000_000
MAX_EXPANDED = 64 * 1024 * 1024
READ_CHARS = 12_000  # Fix 2: capped from 30K; full text accessible via range pagination
SUPPORTED = {"application/pdf": "document", "image/png": "image", "image/jpeg": "image", "text/plain": "text",
             "application/vnd.openxmlformats-officedocument.wordprocessingml.document": "document"}
URL_RE = re.compile(r"https?://[^\s<>\"')\]]+", re.I)
PHONE_RE = re.compile(r"(?<![\w@.])(?:\+?\d[\d\s().-]{7,}\d)(?![\w@])")
MAX_CLUES = 64



def _text_contains_credentials(text: str) -> bool:
    """Check whether text contains authentication secret patterns.
    Used to prevent document-derived images from pages containing credentials
    from being transmitted to Gemini."""
    if not text:
        return False
    from services.higgins.llm_boundary import _CREDENTIAL_PATTERNS
    for pattern in _CREDENTIAL_PATTERNS:
        if pattern.search(text):
            return True
    return False



def text_input_digest(kind: str, value: str) -> str:
    clean, _ = _redact(value)
    return repo.digest(f"{kind}\0{clean}")


def sniff(data: bytes, declared: str) -> str:
    head = data[:16]
    if head.startswith(b"%PDF"):
        return "application/pdf"
    if head.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if head.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if head.startswith(b"MZ"):
        return "application/vnd.microsoft.portable-executable"
    if head.startswith(b"\x7fELF"):
        return "application/x-elf"
    if head.startswith(b"PK\x03\x04"):
        try:
            with zipfile.ZipFile(io.BytesIO(data)) as archive:
                names = archive.namelist()
                if any(n.startswith("word/") for n in names):
                    return "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
                return "application/zip"
        except zipfile.BadZipFile:
            return "application/octet-stream"
    if head.startswith(b"Rar!") or head.startswith(b"\x1f\x8b") or head.startswith(b"7z\xbc\xaf"):
        return "application/x-archive"
    try:
        data[:4096].decode("utf-8")
        return "text/plain" if declared.startswith("text/") or not declared else declared
    except UnicodeDecodeError:
        return "application/octet-stream"


def _redact(text: str) -> tuple[str, list[Transformation]]:
    clean = redact_investigation_secrets(text)
    if clean == text:
        return text, []
    return clean, [Transformation(kind="secret_redaction", description="Authentication secrets (passwords/codes/tokens) were replaced with [redacted] before storage; surrounding context retained.")]


async def _case_budget(owner: str, case_id: str, adding: int) -> None:
    total = 0
    async for row in repo.db.investigation_evidence.find({"owner_id": owner, "case_id": case_id, "byte_length": {"$ne": None}}, {"_id": 0, "byte_length": 1}):
        total += row["byte_length"]
    if total + adding > MAX_CASE_BYTES:
        raise http(413, "budget_exhausted", f"This investigation's active payload budget ({MAX_CASE_BYTES // (1024 * 1024)} MiB) would be exceeded. Remove an item or start a new check.")


async def ingest_text(owner: str, case: dict, client_item_id: str, text: str, *, kind: str = "text", origin: str = "user_submission",
                      parent_id: Optional[str] = None, label: str = "", transformations: Optional[list[Transformation]] = None,
                      coverage: Optional[Coverage] = None, meta: Optional[dict] = None, simulation=None, observed_at: Optional[datetime] = None,
                      publication_root_id: Optional[str] = None, ingestion_attempt_id: Optional[str] = None,
                      publication_owner: Optional[dict] = None, publish: bool = True) -> EvidenceItem:
    clean, redactions = _redact(text)
    item = EvidenceItem(id=str(uuid.uuid4()), case_id=case["case_id"], client_item_id=client_item_id, origin=origin, kind=kind, parent_id=parent_id,
                        collected_at=now_utc(), observed_at=observed_at, expires_at=repo.utc(case["expires_at"]), media_type="text/plain",
                        byte_length=len(clean.encode("utf-8")), simulation=simulation,
                        coverage=coverage or Coverage(status="not_started", unit="characters", total=len(clean), examined=0),
                        transformations=[*(transformations or []), *redactions], label=label or ("link" if kind == "url" else "text"))
    root_id = publication_root_id or item.id
    attempt_id = ingestion_attempt_id or root_id
    await repo.insert_evidence(owner, item, {**(meta or {}), "inputDigest": text_input_digest(kind, clean), "urls": URL_RE.findall(clean) if kind == "text" else []},
                               publication_root_id=root_id, ingestion_attempt_id=attempt_id, publication_owner=publication_owner)
    await repo.store_bytes(owner, case["case_id"], item.id, clean.encode("utf-8"), item.expires_at, publish_root=False)
    if kind == "text" and ((origin == "user_submission" and not meta) or (meta or {}).get("registerClues")):
        await register_clues(owner, case, item, clean, publication_root_id=root_id, ingestion_attempt_id=attempt_id, publication_owner=publication_owner)
    if publish and not await repo.publish_evidence_root(owner, case["case_id"], root_id, attempt_id, publication_owner=publication_owner):
        await repo.discard_incomplete_ingestion(owner, case["case_id"], root_id, attempt_id=attempt_id, publication_owner=publication_owner)
        raise http(409, "conflict", "Evidence publication was superseded before it committed. Retry the submission.")
    return item


async def register_clues(owner: str, case: dict, parent: EvidenceItem, text: str, *, publication_root_id: Optional[str] = None,
                         ingestion_attempt_id: Optional[str] = None, publication_owner: Optional[dict] = None) -> list[EvidenceItem]:
    """Every link and callback number becomes an addressable child clue with its exact offset (R07).
    Full inventory first, then registration in document order (phones are never starved by many URLs); when the per-item
    budget is reached the omitted count and their offsets are recorded on the parent instead of vanishing silently (S10)."""
    found: list[tuple[str, str, int, int]] = []
    seen: set[str] = set()
    for kind, pattern in (("url", URL_RE), ("phone", PHONE_RE)):
        for match in pattern.finditer(text):
            value = match.group(0).rstrip(".,;")
            if value in seen or (kind == "phone" and sum(c.isdigit() for c in value) < 8):
                continue
            seen.add(value)
            found.append((kind, value, match.start(), match.end()))
    found.sort(key=lambda f: f[2])  # document order: a decisive late phone number is registered before an early batch of links
    phones = [f for f in found if f[0] == "phone"]
    urls = [f for f in found if f[0] == "url"]
    # Interleave so both kinds keep a share of the budget; phones (callback numbers) take priority when the budget is tight.
    budget = min(MAX_CLUES, len(found))
    phone_share = min(len(phones), max(budget // 2, budget - len(urls)))
    selected = sorted(phones[:phone_share] + urls[:budget - phone_share], key=lambda f: f[2])
    omitted = [f for f in found if f not in selected]
    clues: list[EvidenceItem] = []
    for kind, value, start, end in selected:
        clue = EvidenceItem(id=str(uuid.uuid4()), case_id=case["case_id"], client_item_id=f"{parent.client_item_id}.clue{len(clues)}", origin="apollo_inference",
                            kind="url" if kind == "url" else "text", parent_id=parent.id, collected_at=now_utc(), expires_at=parent.expires_at, media_type="text/plain",
                            byte_length=len(value.encode("utf-8")), coverage=Coverage(status="not_started", unit="items", total=1, examined=0),
                            transformations=[Transformation(kind="chunk", description=f"{kind} clue found at characters {start}–{end} of the parent item", source_start=start, source_end=end)],
                            label=(("link clue: " + re.sub(r"^https?://([^/]+).*$", r"\1", value)) if kind == "url" else "phone clue")[:80])
        await repo.insert_evidence(owner, clue, {"value": value, "parentOffset": [start, end]},
                                   publication_root_id=publication_root_id or parent.id,
                                   ingestion_attempt_id=ingestion_attempt_id or publication_root_id or parent.id,
                                   publication_owner=publication_owner)
        await repo.store_bytes(owner, case["case_id"], clue.id, value.encode("utf-8"), clue.expires_at, publish_root=False)
        clues.append(clue)
    updates: dict = {}
    if clues:
        updates["$addToSet"] = {"related_evidence_ids": {"$each": [c.id for c in clues]}}
    if omitted:
        parent_row = await repo.db.investigation_evidence.find_one(
            {"owner_id": owner, "case_id": case["case_id"], "evidence_id": parent.id}, {"_id": 0, "meta_ciphertext": 1}
        )
        parent_meta = repo.dec_json(parent_row["meta_ciphertext"]) if parent_row and parent_row.get("meta_ciphertext") else {}
        parent_meta["clueContinuation"] = [{"kind": f[0], "value": f[1], "start": f[2], "end": f[3]} for f in omitted]
        updates["$set"] = {"meta_ciphertext": repo.enc_json(parent_meta),
                           "clue_inventory": {"found": len(found), "registered": len(clues), "remaining": len(omitted),
                                              "nextCursor": 0, "pageSize": MAX_CLUES,
                                              "note": f"{len(omitted)} further {'clue is' if len(omitted) == 1 else 'clues are'} addressable with continue_clues; none were silently discarded."}}
    if updates:
        await repo.update_evidence(owner, case["case_id"], parent.id, updates, attempt_id=ingestion_attempt_id)
    return clues


async def ingest_url(owner: str, case: dict, client_item_id: str, url: str, *, parent_id: Optional[str] = None, label: str = "") -> EvidenceItem:
    url = url.strip()
    if not re.match(r"(?i)^https?://", url):
        url = "https://" + url
    host = re.sub(r"^https?://([^/]+).*$", r"\1", url, flags=re.I)
    return await ingest_text(owner, case, client_item_id, url, kind="url", parent_id=parent_id, label=label or host[:80],
                             coverage=Coverage(status="not_started", unit="items", total=1, examined=0))


async def ingest_observation(owner: str, case: dict, client_item_id: str, result: dict, *, parent_id: Optional[str] = None) -> EvidenceItem:
    import json
    structured = {key: result.get(key) for key in ("requestId", "caseId", "caseRevision", "capabilityId", "status", "unavailableReason", "observedAt", "values", "simulation") if key in result}
    text = json.dumps(structured, ensure_ascii=False, sort_keys=True)
    observed = datetime.fromisoformat(result["observedAt"].replace("Z", "+00:00")) if result.get("observedAt") else None
    return await ingest_text(owner, case, client_item_id, text, kind="observation", origin="device_observation", parent_id=parent_id,
                             label=f"observation: {result['capabilityId']}"[:80], simulation=result.get("simulation"), observed_at=observed,
                             coverage=Coverage(status="examined" if result["status"] == "observed" else "unavailable", unit="items", total=1,
                                               examined=1 if result["status"] == "observed" else 0, reason=None if result["status"] == "observed" else result["status"]),
                             meta={"deviceResult": result})


async def _purge_original_if_secret(owner: str, case: dict, item: EvidenceItem, text: str, attempt_id: str) -> None:
    """Originals are never retained in recoverable form when they carry an authentication secret (R03)."""
    if redact_investigation_secrets(text) != text:
        await repo.db.investigation_content_chunks.delete_many({"owner_id": owner, "case_id": case["case_id"], "evidence_id": item.id})
        await repo.update_evidence(owner, case["case_id"], item.id, {"$set": {"availability": "purged"}, "$push": {"transformations": Transformation(
            kind="secret_redaction", description="The original file contained an authentication secret; only the redacted extracted text is retained. Signature, size and structure were recorded first.").wire()}}, attempt_id=attempt_id)


MAX_SCANNED_PAGES = 12
SCAN_DPI = 110


def _render_pdf_pages(data: bytes, page_numbers: list[int]) -> list[tuple[int, bytes]]:
    """Rasterises the given 1-based pages to PNG (bounded). Rendering failures yield no image; the page stays an explicit omitted range."""
    try:
        import pypdfium2 as pdfium
        pdf = pdfium.PdfDocument(io.BytesIO(data))
    except Exception:  # noqa: BLE001
        return []
    out: list[tuple[int, bytes]] = []
    for number in page_numbers:
        try:
            page = pdf[number - 1]
            bitmap = page.render(scale=SCAN_DPI / 72)
            image = bitmap.to_pil()
            if image.width * image.height > MAX_IMAGE_PIXELS:
                image.thumbnail((2000, 2000))
            buf = io.BytesIO()
            image.save(buf, format="PNG", optimize=True)
            out.append((number, buf.getvalue()))
        except Exception:  # noqa: BLE001
            continue
    return out


def _pdf_pages(data: bytes, start_page: int = 1, page_count: int = MAX_PAGES) -> tuple[list[str], list[str], list[int], int, list[int], list[int]]:
    from pypdf import PdfReader
    reader = PdfReader(io.BytesIO(data))
    if reader.is_encrypted:
        raise ValueError("encrypted")
    pages, links, unreadable, annotation_errors, visual_pages = [], [], [], [], []
    total_pages = len(reader.pages)
    start_index = max(0, start_page - 1); end_index = min(total_pages, start_index + max(1, min(page_count, MAX_PAGES)))
    for index in range(start_index, end_index):
        page = reader.pages[index]
        try:
            text = page.extract_text() or ""
        except Exception:  # noqa: BLE001 — malformed page becomes an explicit gap
            text, unreadable = "", [*unreadable, index + 1]
        if not text.strip():
            unreadable.append(index + 1)
        try:
            resources = page.get("/Resources") or {}
            xobjects = resources.get("/XObject") or {}
            if any((obj.get_object().get("/Subtype") == "/Image") for obj in xobjects.values()):
                visual_pages.append(index + 1)
        except Exception:  # noqa: BLE001 — visual inventory failure is a page-level gap
            annotation_errors.append(index + 1)
        pages.append(text)
        for annotation in page.get("/Annots") or []:
            try:
                obj = annotation.get_object()
                uri = obj.get("/A", {}).get("/URI")
                if uri:
                    links.append(f"page {index + 1}: {uri}")
            except Exception:  # noqa: BLE001
                annotation_errors.append(index + 1)
    return pages, links, sorted(set(unreadable)), total_pages, sorted(set(annotation_errors)), sorted(set(visual_pages))


def _docx_text(data: bytes) -> tuple[list[str], list[str], list[tuple[str, str, bytes]], int]:
    import docx
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        expanded = sum(entry.file_size for entry in archive.infolist())
        if expanded > MAX_EXPANDED:
            raise ValueError("expanded")
    document = docx.Document(io.BytesIO(data))
    paragraphs = [p.text for p in document.paragraphs]
    for table in document.tables:  # tables are part of the document, not an omission
        for row in table.rows:
            paragraphs.append(" | ".join(cell.text for cell in row.cells))
    for section in document.sections:
        paragraphs.extend(p.text for p in section.header.paragraphs if p.text.strip())
        paragraphs.extend(p.text for p in section.footer.paragraphs if p.text.strip())
    links = [rel.target_ref for rel in document.part.rels.values() if "hyperlink" in rel.reltype and rel.is_external]
    images = []
    for rel in document.part.rels.values():
        if "image" not in rel.reltype:
            continue
        blob = rel.target_part.blob
        if len(blob) + sum(len(item[2]) for item in images) > MAX_EXPANDED:
            raise ValueError("expanded")
        images.append((str(rel.target_ref), str(rel.target_part.content_type), blob))
    drawing_count = len(document.element.xpath(".//w:drawing"))
    return paragraphs, links, images, max(0, drawing_count - len(images))


async def ingest_file(owner: str, case: dict, meta_in: dict, data: bytes, *, evidence_root_id: Optional[str] = None,
                      ingestion_attempt_id: Optional[str] = None, publication_owner: Optional[dict] = None,
                      content_digest: Optional[str] = None) -> EvidenceItem:
    if len(data) > MAX_FILE_BYTES:
        raise http(413, "budget_exhausted", f"Files above {MAX_FILE_BYTES // (1024 * 1024)} MiB are not accepted. The item stays listed as not received.")
    await _case_budget(owner, case["case_id"], len(data))
    detected = sniff(data, meta_in["mediaType"])
    transformations = []
    if detected != meta_in["mediaType"]:
        transformations.append(Transformation(kind="normalise", description=f"Declared type {meta_in['mediaType']} but bytes match {detected}; the detected type is used."))
    kind = SUPPORTED.get(detected, meta_in["kind"] if meta_in["kind"] != "document" else "attachment")
    if kind == "text":
        kind = "document"  # a TXT original is a document container; only its redacted derivative is model input
    expires = repo.utc(case["expires_at"])
    attempt_id = ingestion_attempt_id or uuid.uuid4().hex
    root_id = evidence_root_id or str(uuid.uuid4())
    item = EvidenceItem(id=root_id, case_id=case["case_id"], client_item_id=meta_in["clientItemId"], origin="user_submission", kind=kind,
                        parent_id=meta_in.get("parentId"), collected_at=now_utc(), expires_at=expires, media_type=detected, byte_length=len(data),
                        coverage=Coverage(status="not_started", unit="bytes", total=len(data), examined=0), transformations=transformations,
                        label=f"{kind}: {re.sub(r'[^A-Za-z0-9._ -]', '_', meta_in['filename'])[:60]}")

    # Submitting an image to an investigation authorises its analysis. Credential protection happens on the
    # device before upload (detected credentials are redacted, or the image is not sent); the bytes received
    # here are stored unchanged as the original evidence. Record what the device reported doing, if anything.
    consent_record = None
    if kind == "image" and meta_in.get("sanitizationDecision"):
        consent_record = {
            "decision": meta_in.get("sanitizationDecision"),
            "transformations": meta_in.get("sanitizationTransformations", []),
            "redactedRegions": meta_in.get("redactedRegions", 0),
            "recordedAt": now_utc().isoformat(),
        }
    await repo.insert_evidence(owner, item, {"filename": meta_in["filename"], "declaredMediaType": meta_in["mediaType"], "detectedMediaType": detected,
                                             "contentDigest": content_digest, **({"consentRecord": consent_record} if consent_record else {})},
                               publication_root_id=item.id, ingestion_attempt_id=attempt_id, publication_owner=publication_owner)
    await repo.store_bytes(owner, case["case_id"], item.id, data, expires, publish_root=False)
    await _derive(owner, case, item, data, detected, attempt_id, publication_owner)
    device_text = (meta_in.get("deviceExtractedText") or "").strip() if kind == "image" else ""
    if device_text:
        # Wright Triage's extraction of the screenshot/image: the text the phone read from it, as derived evidence.
        await ingest_text(owner, case, f"{item.client_item_id}.device-text", device_text, parent_id=item.id,
                          label="text read from the image on the phone", meta={"deviceExtracted": True, "registerClues": True},
                          transformations=[Transformation(kind="decode", description="Text the phone's on-device text recognition read from this image (credentials removed on the device).")],
                          publication_root_id=item.id, ingestion_attempt_id=attempt_id, publication_owner=publication_owner, publish=False)
    if not await repo.publish_evidence_root(owner, case["case_id"], item.id, attempt_id, publication_owner=publication_owner):
        await repo.discard_incomplete_ingestion(owner, case["case_id"], item.id, attempt_id=attempt_id, publication_owner=publication_owner)
        raise http(409, "conflict", "Evidence publication was superseded before it committed. Retry the upload.")
    return item


# ── Package 4: On-device privacy screening replaces Gemini preflight ──
# Raw images are never sent to Gemini for screening. All privacy screening
# happens on the device (ImagePrivacyGate) before network transmission.
# The backend validates client-supplied sanitization assertions.
# Derived document images undergo pre-transmission credential text-layer checks.


async def _derive(owner: str, case: dict, item: EvidenceItem, data: bytes, detected: str, attempt_id: str, publication_owner: Optional[dict] = None) -> None:
    """Parser extraction is recorded as its own derived evidence with page/offset identities. Parsing is not examination."""
    coverage_update: dict = {}
    try:
        if detected == "application/pdf" or detected.endswith("wordprocessingml.document"):
            if detected == "application/pdf":
                pages, links, unreadable, total_pages, annotation_errors, visual_pages = _pdf_pages(data)
                embedded_images, unresolved_drawings = [], 0
            else:
                paragraphs, links, embedded_images, unresolved_drawings = _docx_text(data)
                pages, unreadable, total_pages, annotation_errors, visual_pages = ["\n".join(paragraphs)], [], 1, [], []
            offsets, text, cursor = [], "", 0
            for number, page in enumerate(pages, start=1):
                block = f"\n\n[page {number}]\n{page}"
                offsets.append({"page": number, "start": cursor, "end": cursor + len(block), "readable": number not in unreadable})
                text += block
                cursor += len(block)
            if len(text) > MAX_EXPANDED:
                raise ValueError("expanded")
            link_text = "\n".join(links)
            derived = await ingest_text(owner, case, f"{item.client_item_id}.text", text + ("\n\n[links]\n" + link_text if link_text else ""), parent_id=item.id,
                                        label=f"extracted text ({len(pages)} pages)", meta={"pages": offsets, "links": links, "registerClues": True,
                                                                                         **({"itemIndex": 0} if embedded_images else {})},
                                        transformations=[Transformation(kind="decode", description=f"Parser text layer of {len(pages)} page(s) with page markers; {len(links)} link target(s) collected. Scanned/unreadable pages: {unreadable or 'none'}.")],
                                        publication_root_id=item.id, ingestion_attempt_id=attempt_id, publication_owner=publication_owner, publish=False)
            # Scanned/image-only pages: rasterise each (within budget) as a derived image so Gemini can read it visually. A rendered page
            # is addressable evidence with its own coverage; only pages beyond the render budget remain explicit omitted ranges.
            rendered_ids, rendered_pages = [], []
            credential_withheld_pages = []  # Pages withheld due to credential detection
            to_render = sorted(set(unreadable + visual_pages))[:MAX_SCANNED_PAGES] if detected == "application/pdf" else []
            if to_render:
                for number, png in _render_pdf_pages(data, to_render):
                    # Check source page text for credential patterns before storing.
                    page_index = number - 1
                    source_text = pages[page_index] if page_index < len(pages) else ""
                    has_text_layer = bool(source_text.strip())

                    if has_text_layer and _text_contains_credentials(source_text):
                        # Text layer contains credentials — withhold rendered image
                        credential_withheld_pages.append(number)
                        continue

                    # Determine limitation based on text layer availability
                    if not has_text_layer:
                        # No text layer — visual-only page. Cannot detect credentials server-side.
                        privacy_limitation = ("Scanned/image-only page: no text layer available for "
                                              "server-side credential detection. Visual-only authentication "
                                              "secrets cannot be identified without on-device screening.")
                    else:
                        privacy_limitation = ("Text layer credential check passed. Visual-only secrets "
                                              "not present in the text layer are a documented limitation.")

                    page_item = EvidenceItem(id=str(uuid.uuid4()), case_id=case["case_id"], client_item_id=f"{item.client_item_id}.page{number}", origin=item.origin, kind="image",
                                             parent_id=item.id, collected_at=now_utc(), expires_at=item.expires_at, media_type="image/png", byte_length=len(png),
                                             coverage=Coverage(status="not_started", unit="items", total=1, examined=0, reason="rendered page available to Higgins vision; not yet examined"),
                                             transformations=[Transformation(kind="decode", description=f"Page {number} rasterised at {SCAN_DPI} DPI."),
                                                              Transformation(kind="privacy_note", description=privacy_limitation)],
                                             label=f"visual page {number} (rendered image)")
                    await repo.insert_evidence(owner, page_item, {"page": number, "derivedFrom": item.id,
                                                                   "consentRecord": {"purpose": "investigation", "decision": "document_rendered_page",
                                                                                     "transformations": [f"Page {number} rasterised at {SCAN_DPI} DPI"],
                                                                                     "limitations": [privacy_limitation],
                                                                                     "consentRecordedAt": now_utc().isoformat(), "trustBoundary": "document_derived"}},
                                               publication_root_id=item.id, ingestion_attempt_id=attempt_id, publication_owner=publication_owner)
                    await repo.store_bytes(owner, case["case_id"], page_item.id, png, item.expires_at, publish_root=False)
                    rendered_ids.append(page_item.id)
                    rendered_pages.append(number)
            # Build omitted list — now safe to reference credential_withheld_pages
            omitted = [{"start": p - 1, "end": p, "reason": "rendered page withheld: source text contains authentication secret patterns; redacted text evidence preserved"}
                       for p in credential_withheld_pages]
            omitted.extend({"start": p - 1, "end": p, "reason": "no extractable text layer (scanned or image-only page); rendering it also failed" if p in to_render
                       else f"scanned page beyond this turn's {MAX_SCANNED_PAGES}-page visual-rendering budget; not yet examined"}
                      for p in unreadable if p not in rendered_pages and p not in credential_withheld_pages)
            omitted.extend({"start": p - 1, "end": p, "reason": "page contains material visual content beyond the bounded visual-rendering budget"}
                           for p in visual_pages if p not in rendered_pages and p not in unreadable)
            if total_pages > len(pages):
                omitted.append({"start": len(pages), "end": total_pages, "reason": f"beyond the {MAX_PAGES}-page processing budget; bounded continuation available"})
            omitted.extend({"start": page - 1, "end": page, "reason": "hyperlink annotation component could not be extracted"} for page in annotation_errors)
            coverage_update = {"status": "partial" if omitted else "not_started", "unit": "pages", "total": total_pages, "examined": 0, "omittedRanges": omitted,
                               "materialGap": bool(omitted), "permanentGap": False,
                               "reason": "parser extraction complete; model examination pending" + (f"; {len(rendered_pages)} scanned page(s) rendered for visual reading" if rendered_pages else "")}
            for image_index, (image_name, image_type, image_data) in enumerate(embedded_images):
                # Pre-transmission credential check on parent document text.
                parent_text = "\n".join(pages) if pages else ""
                if _text_contains_credentials(parent_text):
                    omitted.append({"start": image_index + 1, "end": image_index + 2,
                                    "reason": "embedded image withheld: parent document text contains authentication secret patterns; redacted text evidence preserved"})
                    continue
                if image_type in ("image/png", "image/jpeg"):
                    # Embedded images have no independent text layer — visual-only credential
                    # detection is not possible server-side. This is an honest limitation.
                    visual_limitation = ("Embedded image: no independent text layer for server-side credential "
                                         "detection. Visual-only authentication secrets cannot be identified "
                                         "without on-device screening. Parent document text was checked.")
                    image_item = EvidenceItem(id=str(uuid.uuid4()), case_id=case["case_id"], client_item_id=f"{item.client_item_id}.image{image_index}", origin=item.origin, kind="image",
                                              parent_id=item.id, collected_at=now_utc(), expires_at=item.expires_at, media_type=image_type, byte_length=len(image_data),
                                              coverage=Coverage(status="not_started", unit="items", total=1, examined=0,
                                                                reason="embedded document image extracted; parent text credential-checked"),
                                              transformations=[Transformation(kind="decode", description="Embedded image extracted from document."),
                                                               Transformation(kind="privacy_note", description=visual_limitation)],
                                              label=f"embedded image: {image_name}"[:80])
                    consent_meta = {
                        "derivedFrom": item.id, "embeddedName": image_name, "itemIndex": image_index + 1,
                        "consentRecord": {
                            "purpose": "investigation",
                            "decision": "document_embedded_image",
                            "transformations": ["Extracted from parent document; parent text credential-checked"],
                            "limitations": [visual_limitation],
                            "consentRecordedAt": now_utc().isoformat(),
                            "trustBoundary": "document_derived",
                        },
                    }
                    await repo.insert_evidence(owner, image_item, consent_meta, publication_root_id=item.id, ingestion_attempt_id=attempt_id, publication_owner=publication_owner)
                    await repo.store_bytes(owner, case["case_id"], image_item.id, image_data, item.expires_at, publish_root=False)
                    rendered_ids.append(image_item.id)
                else:
                    omitted.append({"start": image_index + 1, "end": image_index + 2, "reason": f"embedded image of unsupported type ({image_type}) withheld"})
                    await repo.db.investigation_content_chunks.delete_many({"owner_id": owner, "case_id": case["case_id"], "evidence_id": item.id})
            omitted.extend({"start": 1 + len(embedded_images) + index, "end": 2 + len(embedded_images) + index,
                            "reason": "embedded drawing object could not be decoded as text or image"} for index in range(unresolved_drawings))
            document_items = len(embedded_images) + unresolved_drawings
            coverage_update.update({"unit": "items" if document_items else coverage_update.get("unit", "pages"),
                                    "total": 1 + document_items if document_items else coverage_update.get("total"),
                                    "status": "partial" if omitted else "not_started", "omittedRanges": omitted, "materialGap": bool(omitted)})
            await repo.update_evidence(owner, case["case_id"], item.id, {"$set": {"coverage": coverage_update, "related_evidence_ids": [derived.id, *rendered_ids],
                                                                                   **({"availability": "purged"} if embedded_images and any(gap["reason"].startswith("embedded image withheld") for gap in omitted) else {})}}, attempt_id=attempt_id)
            await _purge_original_if_secret(owner, case, item, text, attempt_id)
        elif detected in ("image/png", "image/jpeg"):
            from PIL import Image
            with Image.open(io.BytesIO(data)) as image:
                if image.width * image.height > MAX_IMAGE_PIXELS:
                    await repo.update_evidence(owner, case["case_id"], item.id, {"$set": {"availability": "unavailable"}}, attempt_id=attempt_id)
                    raise ValueError("pixels")
            await repo.update_evidence(owner, case["case_id"], item.id, {"$set": {"coverage.reason": "original image available to Higgins vision; not yet examined"}}, attempt_id=attempt_id)
        elif detected == "text/plain":
            derived = await ingest_text(owner, case, f"{item.client_item_id}.text", data.decode("utf-8", errors="replace"), parent_id=item.id, label="file text", meta={"registerClues": True},
                                        publication_root_id=item.id, ingestion_attempt_id=attempt_id, publication_owner=publication_owner, publish=False)
            await repo.update_evidence(owner, case["case_id"], item.id, {"$set": {"related_evidence_ids": [derived.id], "coverage": {"status": "not_started", "unit": "characters", "total": len(data.decode("utf-8", errors="replace")), "examined": 0}}}, attempt_id=attempt_id)
            await _purge_original_if_secret(owner, case, item, data.decode("utf-8", errors="replace"), attempt_id)
        else:
            reason = {"application/zip": "archive contents are not expanded; list only", "application/x-archive": "compressed archive is not expanded",
                      "application/vnd.microsoft.portable-executable": "Windows executable: signature inspected, never executed",
                      "application/x-elf": "executable binary: signature inspected, never executed"}.get(detected, "unsupported format: signature and size only")
            await repo.update_evidence(owner, case["case_id"], item.id, {"$set": {"coverage": {"status": "unavailable", "unit": "bytes", "total": len(data), "examined": 16,
                                                                                    "examinedRanges": [{"start": 0, "end": 16}], "omittedRanges": [{"start": 16, "end": len(data), "reason": reason}],
                                                                                    "reason": reason, "materialGap": True, "permanentGap": True}}}, attempt_id=attempt_id)
    except ValueError as exc:
        reason = {"encrypted": "document is encrypted; contents cannot be read", "expanded": "extracted content exceeds the expansion budget", "pixels": "image exceeds the 40-megapixel decode budget"}.get(str(exc), "malformed content")
        await repo.update_evidence(owner, case["case_id"], item.id, {"$set": {"coverage": {"status": "unavailable", "unit": "bytes", "total": len(data), "examined": 0,
                                                                                "omittedRanges": [{"start": 0, "end": len(data), "reason": reason}], "reason": reason, "materialGap": True, "permanentGap": True}}}, attempt_id=attempt_id)
    except Exception:  # noqa: BLE001 — parser failure is an explicit gap, never a clean result
        await repo.update_evidence(owner, case["case_id"], item.id, {"$set": {"coverage.status": "unavailable", "coverage.reason": "parser failed; content not examined", "coverage.materialGap": True, "coverage.permanentGap": True}}, attempt_id=attempt_id)


def _subtract_page_range(ranges: list[dict], start: int, end: int) -> list[dict]:
    remaining: list[dict] = []
    for entry in ranges:
        left, right = int(entry.get("start", 0)), int(entry.get("end", 0))
        if right <= start or left >= end:
            remaining.append(entry); continue
        if left < start:
            remaining.append({**entry, "end": start})
        if right > end:
            remaining.append({**entry, "start": end})
    return remaining


async def continue_document(owner: str, case: dict, evidence_id: str, start_page: int, page_count: int = MAX_PAGES) -> dict:
    """Publishes one bounded PDF component slice (text, links and scanned-page visuals) as an atomic manifest."""
    row = await repo.get_evidence(owner, case["case_id"], evidence_id)
    if row.get("media_type") != "application/pdf" or row.get("parent_id"):
        raise http(400, "invalid_request", "Document continuation requires an original PDF evidence item.")
    data = await repo.load_bytes(owner, case["case_id"], evidence_id)
    pages, links, unreadable, total, annotation_errors, visual_pages = _pdf_pages(data, start_page, page_count)
    start = max(1, start_page); end = min(total, start + max(1, min(page_count, MAX_PAGES)) - 1)
    if start > total:
        raise http(400, "invalid_request", f"startPage exceeds the document's {total} pages.")
    client_item_id = f"{row['client_item_id']}.pages.{start}-{end}"
    existing = await repo.db.investigation_evidence.find_one(
        {"owner_id": owner, "case_id": case["case_id"], "client_item_id": client_item_id}, {"_id": 0}
    )
    if existing:
        try:
            return await _repair_continuation_from_manifest(owner, case, evidence_id, existing["evidence_id"], replayed=True)
        except Exception:  # unpublished interrupted slice: abandon only its exact attempt, then rebuild
            await repo.discard_incomplete_ingestion(owner, case["case_id"], existing["publication_root_id"], attempt_id=existing.get("ingestion_attempt_id"))
    text, offsets, cursor = "", [], 0
    for page_number, page_text in enumerate(pages, start=start):
        block = f"\n\n[page {page_number}]\n{page_text or '[No extractable text layer on this page.]'}"
        offsets.append({"page": page_number, "start": cursor, "end": cursor + len(block), "readable": page_number not in unreadable})
        text += block; cursor += len(block)
    if links:
        text += "\n\n[hyperlink targets]\n" + "\n".join(links)
    attempt_id = uuid.uuid4().hex
    derived = await ingest_text(owner, case, client_item_id, text, parent_id=evidence_id, label=f"continued PDF extraction (pages {start}-{end})",
                                meta={"pages": offsets, "links": links, "registerClues": True}, ingestion_attempt_id=attempt_id, publish=False,
                                transformations=[Transformation(kind="decode", description=f"Bounded component extraction for PDF pages {start}-{end}; {len(links)} hyperlink target(s); unreadable pages: {unreadable or 'none'}. ")])
    rendered_ids, rendered_pages = [], []
    for page_number, png in _render_pdf_pages(data, sorted(set(unreadable + visual_pages))[:MAX_SCANNED_PAGES]):
        visual = EvidenceItem(id=str(uuid.uuid4()), case_id=case["case_id"], client_item_id=f"{client_item_id}.visual.{page_number}", origin=row["origin"], kind="image",
                              parent_id=evidence_id, collected_at=now_utc(), expires_at=repo.utc(row["expires_at"]), media_type="image/png", byte_length=len(png),
                              coverage=Coverage(status="not_started", unit="items", total=1, examined=0, reason="continued scanned-page visual available; not yet examined"),
                              transformations=[Transformation(kind="decode", description=f"Continuation page {page_number} rendered at {SCAN_DPI} DPI for visual reading.")],
                              label=f"continued scanned page {page_number}")
        await repo.insert_evidence(owner, visual, {"page": page_number, "derivedFrom": evidence_id}, publication_root_id=derived.id, ingestion_attempt_id=attempt_id)
        await repo.store_bytes(owner, case["case_id"], visual.id, png, visual.expires_at, publish_root=False)
        rendered_ids.append(visual.id); rendered_pages.append(page_number)
    derived_row = await repo.db.investigation_evidence.find_one(
        {"owner_id": owner, "case_id": case["case_id"], "evidence_id": derived.id, "ingestion_attempt_id": attempt_id}, {"_id": 0}
    )
    derived_meta = repo.dec_json(derived_row["meta_ciphertext"]) if derived_row and derived_row.get("meta_ciphertext") else {}
    derived_meta["continuation"] = {"parentEvidenceId": evidence_id, "startPage": start, "endPage": end, "totalPages": total,
                                    "links": links, "unreadablePages": unreadable, "visualPages": visual_pages, "annotationGapPages": annotation_errors,
                                    "renderedPages": rendered_pages}
    await repo.update_evidence(owner, case["case_id"], derived.id, {"$set": {"meta_ciphertext": repo.enc_json(derived_meta)}}, attempt_id=attempt_id)
    if not await repo.publish_evidence_root(owner, case["case_id"], derived.id, attempt_id):
        await repo.discard_incomplete_ingestion(owner, case["case_id"], derived.id, attempt_id=attempt_id)
        raise http(409, "conflict", "The document slice lost publication ownership; retry the continuation.")
    return await _repair_continuation_from_manifest(owner, case, evidence_id, derived.id, replayed=False)


async def continue_clues(owner: str, case: dict, evidence_id: str, cursor: int = 0) -> dict:
    """Publishes the next deterministic clue page retained in the parent's encrypted continuation inventory."""
    parent = await repo.get_evidence(owner, case["case_id"], evidence_id)
    meta = await repo.evidence_meta(parent)
    queued = meta.get("clueContinuation") or []
    cursor = max(0, int(cursor))
    if cursor > len(queued):
        raise http(400, "invalid_request", f"cursor exceeds the {len(queued)} deferred clues.")
    page = queued[cursor:cursor + MAX_CLUES]
    registered = []
    replayed = bool(page)
    for offset, clue in enumerate(page, start=cursor):
        client_item_id = f"{parent['client_item_id']}.clue.cont.{offset}"
        existing = await repo.db.investigation_evidence.find_one(
            {"owner_id": owner, "case_id": case["case_id"], "client_item_id": client_item_id}, {"_id": 0, "evidence_id": 1}
        )
        if existing:
            item = await repo.get_evidence(owner, case["case_id"], existing["evidence_id"])
            item_id, kind = item["evidence_id"], item["kind"]
        elif clue["kind"] == "url":
            replayed = False
            item = await ingest_url(owner, case, client_item_id, clue["value"], parent_id=evidence_id, label="continued link clue")
            item_id, kind = item.id, item.kind
        else:
            replayed = False
            item = await ingest_text(owner, case, client_item_id, clue["value"], parent_id=evidence_id, origin="apollo_inference", label="continued phone clue")
            item_id, kind = item.id, item.kind
        registered.append({"evidenceId": item_id, "kind": kind, "offset": [clue["start"], clue["end"]]})
    next_cursor = cursor + len(page)
    remaining = max(0, len(queued) - next_cursor)
    if registered:
        found = int((parent.get("clue_inventory") or {}).get("found", len(registered) + remaining))
        await repo.update_evidence(owner, case["case_id"], evidence_id, {"$addToSet": {"related_evidence_ids": {"$each": [item["evidenceId"] for item in registered]}},
            "$set": {"clue_inventory.registered": found - remaining,
                     "clue_inventory.remaining": remaining, "clue_inventory.nextCursor": next_cursor if remaining else None}})
    return {"parentEvidenceId": evidence_id, "registered": registered, "nextCursor": next_cursor if remaining else None,
            "remaining": remaining, "totalDeferred": len(queued), "replayed": replayed}


async def _repair_continuation_from_manifest(owner: str, case: dict, parent_id: str, slice_root_id: str, *, replayed: bool) -> dict:
    """Reconstruct delivery and parent coverage solely from the committed slice manifest.

    This is the recovery boundary for a crash after slice publication but before the parent projection or model
    checkpoint was updated. Uncommitted/wrong-attempt children never enter the result because ``get_evidence``
    verifies every manifest member against the winning publication attempt.
    """
    root = await repo.get_evidence(owner, case["case_id"], slice_root_id)
    manifest = root.get("publication_manifest") or [slice_root_id]
    members = []
    for member_id in manifest:
        try:
            members.append(await repo.get_evidence(owner, case["case_id"], member_id))
        except Exception:  # an incomplete manifest is not deliverable; caller rebuilds the slice
            raise http(409, "conflict", "The committed document slice manifest is incomplete; retry the continuation.")
    meta = await repo.evidence_meta(root)
    continuation = meta.get("continuation") or {}
    start = int(continuation.get("startPage") or 1)
    end = int(continuation.get("endPage") or start)
    total = int(continuation.get("totalPages") or end)
    links = [str(link) for link in continuation.get("links", meta.get("links", []))]
    unreadable = [int(page) for page in continuation.get("unreadablePages", [])]
    visual_pages = [int(page) for page in continuation.get("visualPages", [])]
    annotation_errors = [int(page) for page in continuation.get("annotationGapPages", [])]
    rendered_pages = {int(page) for page in continuation.get("renderedPages", [])}
    visual_ids = []
    for member in members:
        if member.get("kind") == "image":
            visual_ids.append(member["evidence_id"])
            visual_meta = await repo.evidence_meta(member)
            if visual_meta.get("page"):
                rendered_pages.add(int(visual_meta["page"]))
    parent = await repo.get_evidence(owner, case["case_id"], parent_id)
    omitted = list(parent.get("coverage", {}).get("omittedRanges", []))
    available_pages = {page for page in range(start, end + 1) if (page not in unreadable and page not in visual_pages) or page in rendered_pages} - set(annotation_errors)
    for page in sorted(available_pages):
        omitted = _subtract_page_range(omitted, page - 1, page)
    additions = [
        *({"start": page - 1, "end": page, "reason": "no text layer and continuation visual rendering failed"} for page in unreadable if page not in rendered_pages),
        *({"start": page - 1, "end": page, "reason": "material visual content was not rendered in this bounded continuation"} for page in visual_pages if page not in rendered_pages and page not in unreadable),
        *({"start": page - 1, "end": page, "reason": "hyperlink annotation component could not be extracted"} for page in annotation_errors),
    ]
    for gap in additions:
        if gap not in omitted:
            omitted.append(gap)
    await repo.update_evidence(owner, case["case_id"], parent_id, {
        "$addToSet": {"related_evidence_ids": {"$each": [member["evidence_id"] for member in members]},
                      "extraction_ranges": {"start": start - 1, "end": end}},
        "$set": {"coverage.omittedRanges": omitted, "coverage.materialGap": bool(omitted), "coverage.permanentGap": False,
                 "coverage.status": "partial" if omitted else "not_started",
                 "coverage.reason": "bounded parser extraction available; semantic reading progress remains separate"},
    })
    return {"evidenceId": slice_root_id, "visualEvidenceIds": visual_ids, "startPage": start, "endPage": end, "totalPages": total,
            "links": links, "unreadablePages": unreadable, "visualPages": visual_pages, "annotationGapPages": annotation_errors, "replayed": replayed,
            "delivery": "committed_manifest"}


def _union(ranges: list[dict], start: int, end: int) -> list[dict]:
    merged, added = [], False
    for r in sorted([*ranges, {"start": start, "end": end}], key=lambda x: x["start"]):
        if merged and r["start"] <= merged[-1]["end"]:
            merged[-1]["end"] = max(merged[-1]["end"], r["end"])
        else:
            merged.append(dict(r))
    return merged if added or True else merged


async def mark_examined(owner: str, case_id: str, evidence_id: str, start: int, end: int, total: Optional[int]) -> None:
    row = await repo.get_evidence(owner, case_id, evidence_id)
    coverage = row["coverage"]
    ranges = _union(coverage.get("examinedRanges", []), start, end)
    examined = sum(r["end"] - r["start"] for r in ranges)
    total = total if total is not None else coverage.get("total")
    fully_read = total is not None and examined >= total
    # A gap recorded at INGESTION time (truncation, incomplete transcription, parser failure, ...) is a fact about
    # what was retained, not about what was read. Reading everything that WAS retained can never resolve it here —
    # that only happens once the missing portion is actually processed (a future continuation turn), never by
    # re-reading. `permanentGap` is set ONLY at ingestion and never rewritten below, so — unlike `materialGap`, which
    # this function itself recomputes on every call as "not yet fully read" — it cannot be mistaken for resolved
    # just because this same (already limited) retained content was eventually read in full.
    permanent_gap = bool(coverage.get("permanentGap"))
    complete = fully_read and not permanent_gap
    await repo.update_evidence(owner, case_id, evidence_id, {"$set": {"coverage.examinedRanges": ranges, "coverage.examined": min(examined, total or examined),
                                                                      "coverage.status": "examined" if complete else "partial",
                                                                      "coverage.materialGap": permanent_gap or (not fully_read and bool(total))}})
    # Only a DERIVED full-text child (document extraction) or a rendered scanned-page image propagates coverage to its
    # parent. A registered clue (origin apollo_inference, parentOffset) is a relationship, not inherited completion:
    # reading one clue never examines the document.
    if not row.get("parent_id") or row.get("origin") == "apollo_inference":
        return
    parent = await repo.get_evidence(owner, case_id, row["parent_id"])
    meta = await repo.evidence_meta(row)
    if parent["coverage"].get("unit") == "items" and isinstance(meta.get("itemIndex"), int):
        if not complete:
            return
        parent_ranges = _union(parent["coverage"].get("examinedRanges", []), meta["itemIndex"], meta["itemIndex"] + 1)
        parent_examined = sum(item["end"] - item["start"] for item in parent_ranges)
        parent_total = parent["coverage"].get("total")
        parent_gap = bool(parent["coverage"].get("omittedRanges"))
        parent_complete = parent_total is not None and parent_examined >= parent_total and not parent_gap
        await repo.update_evidence(owner, case_id, row["parent_id"], {"$set": {"coverage.examinedRanges": parent_ranges,
            "coverage.examined": min(parent_examined, parent_total or parent_examined), "coverage.status": "examined" if parent_complete else "partial",
            "coverage.materialGap": parent_gap or not parent_complete}})
        return
    if parent["coverage"].get("unit") != "pages":
        # Single-child parent (no page-level structure of its own): mirror this child's own outcome directly.
        await repo.update_evidence(owner, case_id, row["parent_id"], {"$set": {"coverage.status": "examined" if complete else "partial"}})
        return
    # Multi-page parent (a scanned/mixed PDF): its own pages are covered by TWO kinds of children — the extracted-text
    # child (page ranges in CHARACTER units, readable pages only) and each rendered scanned-page image (exactly one
    # page each). Neither can singlehandedly complete the parent; their page coverage is combined here incrementally.
    covered_pages: set[int] = set()
    if meta.get("pages"):  # the extracted-text child: a page counts only once fully covered AND it actually had a text layer
        covered_pages = {p["page"] for p in meta["pages"] if p.get("readable", True) and any(r["start"] <= p["start"] and r["end"] >= p["end"] for r in ranges)}
    elif meta.get("page") and complete:  # a single rendered scanned-page image child represents exactly that one page
        covered_pages = {meta["page"]}
    if not covered_pages:
        return
    parent_ranges = list(parent["coverage"].get("examinedRanges", []))
    for page in covered_pages:
        parent_ranges = _union(parent_ranges, page - 1, page)
    parent_examined = sum(r["end"] - r["start"] for r in parent_ranges)
    parent_total = parent["coverage"].get("total")
    parent_gap = bool(parent["coverage"].get("omittedRanges"))  # pages beyond a processing budget remain a gap until a continuation turn resolves them
    parent_complete = parent_total is not None and parent_examined >= parent_total and not parent_gap
    await repo.update_evidence(owner, case_id, row["parent_id"], {"$set": {
        "coverage.examinedRanges": parent_ranges, "coverage.examined": min(parent_examined, parent_total or parent_examined),
        "coverage.status": "examined" if parent_complete else "partial", "coverage.materialGap": parent_gap or not parent_complete}})


def _as_json(text: str) -> object:
    """Parsed JSON when the item IS a JSON envelope, otherwise the text itself."""
    stripped = text.strip()
    if stripped.startswith("{"):
        try:
            return json.loads(stripped)
        except ValueError:
            return text
    return text


def has_intelligence(payload: object) -> bool:
    """True when a specialist lookup actually returned something.

    Apollo's triage records a result envelope even when no provider was consulted
    ("providers_consulted": [], "total_lookups": 0). An empty envelope carries no intelligence, so it
    is not evidence and is never sent to Gemini.
    """
    if not isinstance(payload, dict):
        return bool(payload)
    summary = payload.get("_summary")
    if isinstance(summary, dict):
        if summary.get("providers_consulted") or summary.get("total_lookups"):
            return True
    # Any section other than the bookkeeping summary that holds real content.
    return any(key != "_summary" and value not in (None, "", [], {}) for key, value in payload.items())


# Workflow metadata recorded when a check starts. It describes HOW the check was initiated, not what
# was observed, so it is kept locally but never sent as evidence.
_WORKFLOW_METADATA = re.compile(r"^(user-initiated|automatic|auto)\b.*\b(check|investigation)\b", re.IGNORECASE)


def is_workflow_metadata(text: str) -> bool:
    return bool(_WORKFLOW_METADATA.match(text.strip()))


# Maximum words of written evidence Apollo will send in one investigation, across every document and
# item combined. Over this, Apollo sends NOTHING: it never quietly shortens, samples or drops evidence.
EVIDENCE_WORD_LIMIT = 10_000


async def model_parts(owner: str, case: dict, rows: list[dict]) -> tuple[list[Part], list[tuple[str, int, int, int]], int]:
    """The case evidence as request parts, each labelled with its id and kind.

    The request sent through the AI gateway is: the person's question, this evidence, and the response schema.
    Therefore:
    - Evidence is sent COMPLETE. Text is never truncated, shortened or summarised.
    - Each item appears ONCE. An image is sent as its bytes with a single identifying line; it is
      never also described in a second, textual representation.
    - Derived items retain their own IDs and parent relationships, even if their text also appears
      in the original. They are never silently omitted by substring matching.
    - Workflow metadata ("user-initiated check via ...") describes how the check started, not what was
      observed, so it is not sent.
    - Empty specialist-intelligence envelopes (no provider consulted, no lookups) carry nothing and
      are not sent.
    - The label carries only the identifier and kind, so findings can cite real evidenceIds. It is
      not instruction or interpretation.
    - Unavailable items are named, with the recorded reason, so the absence is visible and their ids
      stay referable — Apollo never silently drops evidence it holds but cannot supply.

    Returns the parts, the pending examination marks (evidence_id, start, end, total) applied only
    after the model call succeeds, and the total word count of the written evidence (labels excluded, images
    contribute no words) so the caller can enforce EVIDENCE_WORD_LIMIT before any call is made.

    Privacy: text parts are credential-stripped by the provider boundary before the call; images were
    screened and redacted on the device (or refused) before upload. Images carrying visual-only
    credential content remain a documented limitation.
    """
    available = [row for row in rows if row["availability"] == "available"]
    texts: dict[str, str] = {}
    for row in available:
        if row["kind"] in ("text", "url", "observation", "source_snapshot"):
            texts[row["evidence_id"]] = (await repo.read_bytes(owner, case["case_id"], row["evidence_id"])).decode("utf-8", errors="strict")

    parts: list[Part] = []
    marks: list[tuple[str, int, int, int]] = []
    words = 0
    for row in rows:
        label = f"[evidence {row['evidence_id']} · kind={row['kind']}"
        if row.get("label"):
            label += f" · {row['label']}"
        if row.get("parent_id"):
            label += f" · derived-from={row['parent_id']}"
        if row["availability"] != "available":
            reason = (row.get("coverage") or {}).get("reason") or row["availability"]
            parts.append(Part(text=f"{label} · unavailable: {reason}]"))
            continue
        label += "]"
        if row["kind"] in ("text", "url", "observation", "source_snapshot"):
            text = texts[row["evidence_id"]]
            if is_workflow_metadata(text) or not has_intelligence(_as_json(text)):
                continue
            parts.append(Part(text=f"{label}\n{text}"))
            words += len(text.split())
            # The whole retained content of this item is in the part above, so sending it is the
            # examination. Character-counted items record the span; item-counted items (a URL, an
            # observation, a specialist-intelligence record — always total=1) record the one item.
            # Without this, an item-counted evidence row stayed `not_started` for ever and the
            # validator rejected EVERY answer that said the investigation was complete.
            if row["coverage"].get("unit") == "characters":
                marks.append((row["evidence_id"], 0, len(text), len(text)))
            elif row["coverage"].get("unit") == "items":
                total = row["coverage"].get("total") or 1
                marks.append((row["evidence_id"], 0, total, total))
        elif row["kind"] == "image":
            data = await repo.read_bytes(owner, case["case_id"], row["evidence_id"])
            parts.append(Part(text=label))
            parts.append(Part.from_bytes(data=data, mime_type=row["media_type"]))
            marks.append((row["evidence_id"], 0, len(data), len(data)))
    return parts, marks, words
