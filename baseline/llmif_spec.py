"""LLMIF Section 3.2: retrieve message descriptions from a PDF outline.

The specification is data. No PDF text, outline text, or downloaded Python is
executed. The original artifact's ``spec/libs/process_pdf.py`` supplies outline
and page-text utilities; this independent adapter uses pypdf lazily instead of
requiring that artifact's fitz/numpy imports or executing its code.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
from pathlib import Path
import re


@dataclass
class _Section:
    title: str
    page: int
    index: int
    path: tuple[str, ...]
    children: list = field(default_factory=list)

    @property
    def depth(self):
        return len(self.path)


def _canonical_path(path):
    # JSON-pointer escaping preserves hierarchy even when titles contain '/'.
    return "/".join(title.replace("~", "~0").replace("/", "~1") for title in path)


def _message_title(title):
    # Retain the actual section title; this additional selector only removes
    # its numeric outline prefix, e.g. '3.5.2.3.1 Identify Command'.
    return re.sub(r"^\s*\d+(?:\.\d+)*(?:\.)?(?:\s+|$)", "", title).strip()


def _selector(value):
    return re.sub(r"\s+", " ", str(value)).strip().casefold()


def _outline_sections(reader, page_count):
    try:
        outline = reader.outline
    except AttributeError:
        try:
            outline = reader.outlines
        except AttributeError as exc:
            raise ValueError("PDF reader exposes no document outline") from exc
    if not outline:
        raise ValueError("Specification PDF has no outline; outline-based retrieval cannot infer message sections")
    sections = []

    def walk(items, parent=None):
        previous = None
        for entry in items:
            if isinstance(entry, (list, tuple)):
                if previous is None:
                    raise ValueError("Malformed PDF outline: child sections have no parent heading")
                walk(entry, previous)
                continue
            title = getattr(entry, "title", None)
            if title is None and hasattr(entry, "get"):
                title = entry.get("/Title", entry.get("title"))
            if not isinstance(title, str) or not title.strip():
                raise ValueError("PDF outline contains an unnamed section; no section title was invented")
            title = title.strip()
            try:
                page = reader.get_destination_page_number(entry)
            except Exception as exc:
                raise ValueError(f"Cannot resolve outline destination for {title!r}") from exc
            if type(page) is not int or not 0 <= page < page_count:
                raise ValueError(f"Outline destination for {title!r} is outside this PDF")
            if parent is not None and page < parent.page:
                raise ValueError(f"Non-monotonic PDF outline: {title!r} starts before its parent")
            path = (*parent.path, title) if parent else (title,)
            section = _Section(title, page, len(sections), path)
            sections.append(section)
            if parent is not None:
                parent.children.append(section)
            previous = section

    walk(outline)
    return sections


def retrieve_spec_descriptions(pdf_path, *, section_pattern=r"commands\s+received",
                               header_pattern=None, message_names=None, reader=None, selection="children"):
    """Return auditable full-page description spans, without calling an LLM.

    ``section_pattern`` is a case-insensitive regex over outline titles. The
    immediate children of each matching section are message descriptions;
    nested payload/field headings stay inside their parent message span.
    ``message_names`` can select canonical hierarchical keys, original section
    titles, or titles with their leading numeric section prefix removed. A
    short title shared by several clusters retains all of those messages.

    Page numbers are 1-based physical PDF pages. The next peer/ancestor's first
    page is INCLUDED because the current description may end on that page.
    This deliberately allows page overlap and surrounding section text. PDF
    outlines do not establish character-level or layout-level boundaries.
    ``reader`` is an optional pypdf-compatible injection for hermetic tests.
    """
    path = Path(pdf_path).expanduser().resolve()
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    if not isinstance(section_pattern, str) or not section_pattern:
        raise ValueError("A nonempty section_pattern regex is required")
    command_match = re.compile(section_pattern, re.IGNORECASE)
    if header_pattern is not None and (not isinstance(header_pattern, str) or not header_pattern):
        raise ValueError("header_pattern must be a nonempty regex or None")
    header_match = re.compile(header_pattern, re.IGNORECASE) if header_pattern else None
    reader_was_injected = reader is not None
    if reader is None:
        try:
            from pypdf import PdfReader
        except ImportError as exc:
            raise ImportError("PDF specification retrieval requires optional dependency pypdf; core baseline imports do not") from exc
        reader = PdfReader(str(path))
    if getattr(reader, "is_encrypted", False):
        raise ValueError("Decrypt the specification PDF before outline-based retrieval")
    page_count = len(reader.pages)
    if not page_count:
        raise ValueError("Specification PDF has no pages")
    outline = _outline_sections(reader, page_count)
    command_sections = [section for section in outline if command_match.search(section.title)]
    if not command_sections:
        raise ValueError(f"No PDF outline sections match command pattern {section_pattern!r}")
    if selection not in {"children", "matching"}:
        raise ValueError("selection must be children or matching")
    messages = command_sections if selection == "matching" else [child for section in command_sections for child in section.children]
    if not messages:
        raise ValueError("Matching command sections have no immediate message subsections in the PDF outline")
    # Assign keys before filtering, so selecting a subset does not renumber
    # duplicate sibling bookmarks and change the message's identity.
    keys = {}
    occurrences = {}
    reserved = {_canonical_path(section.path) for section in messages}
    assigned = set()
    for section in messages:
        base = _canonical_path(section.path)
        occurrence = occurrences.get(base, 0) + 1
        occurrences[base] = occurrence
        key = base
        if occurrence > 1:
            key = f"{base} [outline-index={section.index}]"
            while key in reserved or key in assigned:
                key += "#"
        keys[section.index] = key
        assigned.add(key)
    requested = None
    if message_names is not None:
        requested = (message_names,) if isinstance(message_names, str) else tuple(message_names)
        if not requested or any(not isinstance(name, str) or not name.strip() for name in requested):
            raise ValueError("message_names must contain nonempty message selectors")
        matched_selectors = set()
        selected = []
        for section in messages:
            candidates = {_selector(keys[section.index]), _selector(section.title),
                          _selector(_message_title(section.title))}
            matched = {name for name in requested if _selector(name) in candidates}
            if matched:
                selected.append(section)
                matched_selectors.update(matched)
        missing = set(requested) - matched_selectors
        if missing:
            raise ValueError(f"Requested messages are absent from matching command sections: {sorted(missing)!r}")
        messages = selected
    header_sections = [section for section in outline if header_match and header_match.search(section.title)]
    if header_match and not header_sections:
        raise ValueError(f"No PDF outline sections match header pattern {header_pattern!r}")
    text_cache = {}
    extraction_warnings = []

    def page_text(index):
        if index not in text_cache:
            try:
                text = reader.pages[index].extract_text()
            except Exception as exc:
                raise ValueError(f"PDF text extraction failed on physical page {index + 1}") from exc
            if text is None:
                text = ""
            if not isinstance(text, str):
                raise ValueError(f"PDF reader returned non-text content on page {index + 1}")
            text_cache[index] = text
            if not text.strip():
                extraction_warnings.append({"page": index + 1, "issue": "no-extractable-page-text", "ocr_performed": False})
        return text_cache[index]

    def span(section):
        # Descendants describe fields of the current section, not its end.
        boundary = next((other for other in outline[section.index + 1:]
                         if other.depth <= section.depth), None)
        end = boundary.page if boundary else page_count - 1
        if end < section.page:
            raise ValueError(f"Non-monotonic PDF outline range for {section.title!r}; cannot infer a safe description span")
        indices = range(section.page, end + 1)
        description = [page_text(index) for index in indices]
        metadata = {
            "name": keys.get(section.index, _canonical_path(section.path)),
            "title": section.title, "message_name": _message_title(section.title),
            "outline_path": list(section.path), "outline_index": section.index,
            "start_page": section.page + 1, "end_page": end + 1,
            "page_numbering": "1-based-physical-pdf-pages",
            "range_basis": "outline-start-through-next-peer-or-ancestor-start-inclusive",
            "boundary_page_included": boundary is not None,
            "boundary_title": boundary.title if boundary else None,
            "within_page_boundaries_resolved": False,
            "full_page_text_may_include_adjacent_sections": True,
            "empty_text_pages": [index + 1 for index in indices if not text_cache[index].strip()],
        }
        return description, metadata

    output, sections = {}, []
    for section in messages:
        description, metadata = span(section)
        output[metadata["name"]] = description
        sections.append(metadata)
    if not any(text.strip() for description in output.values() for text in description):
        raise ValueError("Matched message pages contain no extractable text; OCR or a text-bearing specification is required")
    header = None
    header_metadata = []
    if header_match:
        header_pages = set()
        for section in header_sections:
            _, metadata = span(section)
            header_metadata.append(metadata)
            header_pages.update(range(metadata["start_page"] - 1, metadata["end_page"]))
        header = [page_text(index) for index in sorted(header_pages)]
    return {
        "schema_version": "llmif-spec-descriptions-v1",
        "source_pdf": str(path), "source_sha256": digest.hexdigest(),
        "messages": output, "sections": sections, "header": header,
        "provenance": {
            "method": "LLMIF Section 3.2 outline-regex retrieval",
            "selection": selection,
            "parser": "injected-pypdf-compatible-reader" if reader_was_injected else "pypdf",
            "section_pattern": section_pattern, "header_pattern": header_pattern,
            "message_selectors": list(requested) if requested is not None else None,
            "header_sections": header_metadata, "page_count": page_count,
            "truncation_checked": False, "ocr_performed": False,
            "uncertainty": [
                "Outline bookmarks establish page starts, not exact text boundaries; boundary pages are retained in both adjacent spans.",
                "PDF text extraction may omit images, unusual fonts, or change reading order; no completeness claim or OCR is made.",
            ],
            "warnings": extraction_warnings,
        },
    }
