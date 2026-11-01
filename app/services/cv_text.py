"""Plain text out of an uploaded CV (PDF or Word). Local only; no LLM and no network."""
import io
import re
import zipfile

from . import offer_docs
from .common import ValidationError

MAX_PAGES = 20
MAX_STORED_CHARS = 60000
MIN_TEXT_CHARS = 50
_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\ufffe\uffff]")


def _fail(msg: str):
    raise ValidationError({"file": msg})


def _pdf_text(blob: bytes) -> str:
    from pypdf import PdfReader
    try:
        reader = PdfReader(io.BytesIO(blob))
        if reader.is_encrypted:
            _fail("this PDF is password protected")
        if len(reader.pages) > MAX_PAGES:
            _fail(f"the PDF has more than {MAX_PAGES} pages")
        return "\n".join(p.extract_text() or "" for p in reader.pages)
    except ValidationError:
        raise
    except Exception:
        _fail("this PDF could not be read")


def _docx_text(blob: bytes) -> str:
    try:
        with zipfile.ZipFile(io.BytesIO(blob)) as z:
            if sum(i.file_size for i in z.infolist()) > offer_docs.MAX_UNZIPPED_BYTES:
                _fail("the Word file is too large when unpacked")
            if "word/document.xml" not in z.namelist():
                _fail("this is not a Word (.docx) document")
            doc = offer_docs.open_docx(blob)
            lines = []
            for p in offer_docs._docx_paragraphs(doc):
                t = p.text.strip()
                if t and (not lines or lines[-1] != t):  # merged table cells repeat the same paragraph
                    lines.append(t)
            return "\n".join(lines)
    except ValidationError:
        raise
    except (zipfile.BadZipFile, ValueError):
        _fail("this is not a valid Word (.docx) document")


def extract(blob: bytes) -> tuple[str, str]:
    """Return (kind, text) for a CV file. Raises ValidationError({'file': ...}) when it cannot be used."""
    if not blob:
        _fail("empty upload")
    try:
        kind = offer_docs.detect_kind(blob)
    except ValueError:
        _fail("upload a Word (.docx) or PDF file")
    text = _pdf_text(blob) if kind == "pdf" else _docx_text(blob)
    text = _CONTROL.sub(" ", text.replace("\r", "\n"))
    text = re.sub(r"[\t\u00a0]+", " ", text)
    text = re.sub(r"\n\s*\n+", "\n\n", text).strip()
    if len(text) < MIN_TEXT_CHARS:
        _fail("no readable text found (is it a scan?); enter the details by hand")
    return kind, text[:MAX_STORED_CHARS]
