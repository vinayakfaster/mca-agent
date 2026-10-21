import os
from pypdf import PdfReader
import hashlib

def extract_text_from_pdf(pdf_path):
    """PDF se saara text nikaal lo"""
    reader = PdfReader(pdf_path)
    text = ""
    for page in reader.pages:
        text += page.extract_text() + "\n"
    return text

def chunk_text(text, chunk_size=500, overlap=50):
    """
    Bade text ko chhote chunks mein baanto.
    chunk_size = 500 characters per chunk
    overlap = 50 characters overlap (context continuity ke liye)
    """
    chunks = []
    for i in range(0, len(text), chunk_size - overlap):
        chunk = text[i:i + chunk_size]
        if len(chunk) < 100:  # Bahut chhota chunk ignore karo
            continue
        chunks.append(chunk)
    return chunks

def get_document_id(pdf_path):
    """Har document ka unique ID — filename + file size se"""
    stat = os.stat(pdf_path)
    return f"{os.path.basename(pdf_path)}_{stat.st_size}_{stat.st_mtime}"

def process_pdf(pdf_path):
    """Ek PDF ko process karo — text nikaalo, chunks banao"""
    if not os.path.exists(pdf_path):
        return None
    
    doc_id = get_document_id(pdf_path)
    text = extract_text_from_pdf(pdf_path)
    chunks = chunk_text(text)
    
    # Har chunk ko metadata do (kaunsa document, chunk number)
    chunk_data = []
    for i, chunk in enumerate(chunks):
        chunk_data.append({
            "chunk_id": f"{doc_id}_chunk_{i}",
            "document_id": doc_id,
            "chunk_index": i,
            "text": chunk
        })
    
    return {
        "document_id": doc_id,
        "filename": os.path.basename(pdf_path),
        "total_chunks": len(chunks),
        "chunks": chunk_data
    }