# study_companion/pdf_processor.py
import os
import re
from pypdf import PdfReader

MAX_PDF_PAGES = 300


def extract_text_from_pdf(pdf_path):
    if not os.path.exists(pdf_path):
        return None
    try:
        reader = PdfReader(pdf_path)
    except Exception:
        raise ValueError(f"'{os.path.basename(pdf_path)}' could not be opened as a PDF.")
    if len(reader.pages) > MAX_PDF_PAGES:
        raise ValueError(f"PDF has {len(reader.pages)} pages, over the {MAX_PDF_PAGES} page limit.")
    text = "\n".join((page.extract_text() or "") for page in reader.pages)
    # collapse whitespace runs to single spaces (test: assertNotIn "   ")
    return re.sub(r"[ \t]{2,}", " ", text)


def chunk_text(text, chunk_size=500, overlap=50):
    chunks = []
    for i in range(0, len(text), chunk_size - overlap):
        chunk = text[i:i + chunk_size]
        if len(chunk.strip()) >= 100:
            chunks.append(chunk)
    return chunks


def get_document_id(pdf_path):
    stat = os.stat(pdf_path)
    return f"{os.path.basename(pdf_path)}_{stat.st_size}_{stat.st_mtime}"


def process_pdf(pdf_path, doc_id=None, display_name=None):
    if not os.path.exists(pdf_path):
        return None
    doc_id = doc_id or get_document_id(pdf_path)
    display_name = display_name or os.path.basename(pdf_path)
    text = extract_text_from_pdf(pdf_path)
    chunks = chunk_text(text)
    return {
        "document_id": doc_id,
        "filename": display_name,
        "total_chunks": len(chunks),
        "chunks": [{"chunk_id": f"{doc_id}_chunk_{i}", "document_id": doc_id,
                    "chunk_index": i, "text": c} for i, c in enumerate(chunks)],
    }
