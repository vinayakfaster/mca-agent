# study_companion/study_tools.py
"""
Study Companion tools for the agent. Importing this module registers them (module="study"):

    load_pdf             read a PDF the user uploaded and store it for searching
    search_documents     find the passages that answer a question
    list_documents       show which PDFs exist and which are loaded
    generate_flashcards  finished flashcards            (direct: returned as-is)
    create_quiz          finished multiple-choice quiz  (direct: returned as-is)

Every tool returns plain text and works per user (ctx["user_id"]), so one user never sees
another user's PDFs. Files are found by NAME only, never by a path.
"""
import hashlib
import logging
import os
import re
from pathlib import Path

import file_store
from tools_registry import register
from study_companion import llm_client, pdf_processor

log = logging.getLogger("agent.study")

DOCS_DIR = Path(__file__).resolve().parent / "documents"          # optional shared sample PDFs
CHROMA_DIR = os.getenv("CHROMA_DIR", "./chroma_db")

DEP_MSG = ("The study tools need extra packages. On the server run: "
           "pip install chromadb sentence-transformers pypdf")
NO_DOC_MSG = "No document is loaded yet. Upload a PDF in the Study tab and load it first, then try again."

_store = None


def get_vector_store():
    """Create the vector store on first use (so the backend still starts if chromadb is missing)."""
    global _store
    if _store is None:
        from study_companion.vector_store import VectorStore
        _store = VectorStore(CHROMA_DIR)
    return _store


# ------------------------------------------------------------------ finding files (by name only)

def _norm(text):
    return re.sub(r"\.pdf$", "", (text or "").strip().lower()).strip()


def _match_name(ref, names):
    """Exact match first (ignoring case and a trailing .pdf), then a unique 'contains' match."""
    r = _norm(ref)
    if not r:
        return None
    for n in names:
        if n.lower() == (ref or "").strip().lower() or _norm(n) == r:
            return n
    hits = [n for n in names if len(r) >= 3 and r in _norm(n)]
    return hits[0] if len(hits) == 1 else None


def _candidates(ctx):
    """This user's uploaded PDFs, then the shared sample PDFs. Newest upload wins on equal names."""
    uid = ctx["user_id"]
    found = {}
    for meta in file_store.list_files(uid):
        if meta.get("ext") != ".pdf":
            continue
        try:
            path, _ = file_store.get_file(uid, meta["id"])
        except FileNotFoundError:
            continue
        found.setdefault(meta["name"].lower(), {"name": meta["name"], "path": path, "kind": "upload",
                                                "id": meta["id"], "doc_id": meta["id"]})
    if DOCS_DIR.is_dir():
        who = hashlib.sha1(uid.encode()).hexdigest()[:8]      # keeps chunk ids unique per user
        for p in sorted(DOCS_DIR.glob("*.pdf")):
            stem = re.sub(r"[^A-Za-z0-9]+", "_", p.stem)
            found.setdefault(p.name.lower(), {"name": p.name, "path": p, "kind": "sample",
                                              "id": None, "doc_id": f"sample{who}_{stem}"})
    return list(found.values())


def _find(ctx, ref):
    ref = (ref or "").strip()
    cands = _candidates(ctx)
    uploads = [c for c in cands if c["kind"] == "upload"]
    samples = [c for c in cands if c["kind"] == "sample"]
    for c in uploads:                                           # exact file id
        if c["id"] == ref:
            return c
    name = _match_name(ref, [c["name"] for c in uploads])
    if name is None:                                            # samples: file name only, any folder part is dropped
        base = ref.replace("\\", "/").split("/")[-1]
        name = _match_name(base, [c["name"] for c in samples])
        pool = samples
    else:
        pool = uploads
    return next((c for c in pool if c["name"] == name), None) if name else None


def _clamp(value, default, lo, hi):
    try:
        return max(lo, min(hi, int(float(value))))
    except (TypeError, ValueError):
        return default


def _excerpts(results):
    parts = []
    for i, r in enumerate(results, 1):
        m = r.get("metadata") or {}
        part = int(m.get("chunk_index", 0)) + 1
        parts.append(f"[{i}] {m.get('filename', 'document')} (part {part})\n{r['text'].strip()}")
    return "\n\n".join(parts)


# ------------------------------------------------------------------ tools

@register(
    name="load_pdf",
    description=("Read a PDF the user uploaded and store it so it can be searched. Use this first when the "
                 "user names a PDF. Pass the file name, e.g. 'Biology Notes.pdf'."),
    properties={"file": {"type": "string", "description": "File name of the uploaded PDF"}},
    required=["file"], module="study", needs_ctx=True,
)
def load_pdf(file, ctx):
    try:
        store = get_vector_store()
    except ImportError:
        return DEP_MSG
    c = _find(ctx, file)
    if not c:
        names = [x["name"] for x in _candidates(ctx)]
        hint = (" Available PDFs: " + ", ".join(names) + ".") if names else \
               " No PDFs are uploaded yet. Upload one in the Study tab first."
        return f"I could not find a PDF called '{file}'." + hint
    try:
        doc = pdf_processor.process_pdf(str(c["path"]), doc_id=c["doc_id"], display_name=c["name"])
    except ValueError as e:
        return str(e).replace(Path(c["path"]).name, c["name"])
    if not doc or not doc["chunks"]:
        return f"'{c['name']}' has no readable text. It may be a scanned image, which this tool cannot read."
    store.add_document(ctx["user_id"], doc)
    return (f"Loaded '{c['name']}' ({doc['total_chunks']} chunks). "
            "You can now ask questions about it, or ask for flashcards or a quiz.")


@register(
    name="search_documents",
    description=("Find the passages of the user's loaded PDFs that answer a question. Use this for every "
                 "question about a PDF's content."),
    properties={"query": {"type": "string", "description": "What to look for, in a few words"},
                "file": {"type": "string", "description": "Optional: only search this PDF (file name)"}},
    required=["query"], module="study", needs_ctx=True,
)
def search_documents(query, ctx, file=None):
    try:
        store = get_vector_store()
    except ImportError:
        return DEP_MSG
    uid = ctx["user_id"]
    filename = None
    if file:
        filename = _match_name(file, [d["filename"] for d in store.list_documents(uid)])
        if filename is None:
            return f"'{file}' is not loaded yet. Load it first with load_pdf."
    results = store.search(uid, query, 5, filename=filename)
    if not results:
        return NO_DOC_MSG if not store.list_documents(uid) else "I found no relevant text in the loaded documents."
    return ("Answer ONLY from these excerpts and name the file in your answer. "
            "If they do not contain the answer, say so.\n\n" + _excerpts(results))


@register(
    name="list_documents",
    description="List the user's PDFs and whether each one is loaded for searching.",
    properties={}, required=[], module="study", needs_ctx=True,
)
def list_documents(ctx):
    loaded = {}
    try:
        for d in get_vector_store().list_documents(ctx["user_id"]):
            loaded[d["filename"]] = d["chunks"]
    except ImportError:
        pass
    lines, seen = [], set()
    for c in _candidates(ctx):
        seen.add(c["name"])
        label = "sample document, " if c["kind"] == "sample" else ""
        if c["name"] in loaded:
            lines.append(f"- {c['name']} ({label}loaded, {loaded[c['name']]} chunks)")
        elif c["kind"] == "sample":
            lines.append(f"- {c['name']} (sample document, not loaded yet)")
        else:
            lines.append(f"- {c['name']} (uploaded, not loaded yet)")
    for name, n in loaded.items():                              # loaded earlier, upload since deleted
        if name not in seen:
            lines.append(f"- {name} (loaded, {n} chunks)")
    return "Your PDFs:\n" + "\n".join(lines) if lines else "No PDFs yet. Upload one in the Study tab."


FLASHCARD_SCHEMA = {
    "type": "object",
    "properties": {"cards": {"type": "array", "items": {
        "type": "object",
        "properties": {"question": {"type": "string"}, "answer": {"type": "string"}},
        "required": ["question", "answer"]}}},
    "required": ["cards"],
}

QUIZ_SCHEMA = {
    "type": "object",
    "properties": {"questions": {"type": "array", "items": {
        "type": "object",
        "properties": {"question": {"type": "string"},
                       "options": {"type": "array", "items": {"type": "string"}},
                       "correct": {"type": "string"},
                       "explanation": {"type": "string"}},
        "required": ["question", "options", "correct", "explanation"]}}},
    "required": ["questions"],
}


@register(
    name="generate_flashcards",
    description="Make study flashcards (question and answer) about a topic from the user's loaded PDFs.",
    properties={"topic": {"type": "string", "description": "Topic to make flashcards about"},
                "num_cards": {"type": "integer", "description": "How many cards (default 8, max 15)"}},
    required=["topic"], module="study", needs_ctx=True, direct=True,
)
def generate_flashcards(topic, ctx, num_cards=8):
    n = _clamp(num_cards, 8, 1, 15)
    try:
        results = get_vector_store().search(ctx["user_id"], topic, 8)
    except ImportError:
        return DEP_MSG
    if not results:
        return NO_DOC_MSG
    prompt = (f"Using ONLY the excerpts below, write {n} flashcards about \"{topic}\". "
              "Each card has a short question and a short answer. Do not add facts that are not in the excerpts. "
              "Reply with JSON only.\n\nExcerpts:\n" + _excerpts(results))
    data = llm_client.chat_once(prompt, FLASHCARD_SCHEMA)
    raw = data.get("cards") if isinstance(data, dict) else None
    cards = [(str(c.get("question", "")).strip(), str(c.get("answer", "")).strip())
             for c in (raw or []) if isinstance(c, dict)]
    cards = [(q, a) for q, a in cards if q and a][:n]
    if not cards:
        return "I could not make flashcards from the document for that topic. Try a different topic."
    body = "\n".join(f"{i}. Q: {q}\n   A: {a}" for i, (q, a) in enumerate(cards, 1))
    return f"Flashcards: {topic} ({len(cards)} cards)\n\n{body}"


@register(
    name="create_quiz",
    description="Make a multiple-choice quiz about a topic from the user's loaded PDFs.",
    properties={"topic": {"type": "string", "description": "Topic of the quiz"},
                "num_questions": {"type": "integer", "description": "How many questions (default 5, max 10)"},
                "difficulty": {"type": "string", "description": "easy, medium or hard"}},
    required=["topic"], module="study", needs_ctx=True, direct=True,
)
def create_quiz(topic, ctx, num_questions=5, difficulty="medium"):
    n = _clamp(num_questions, 5, 1, 10)
    difficulty = str(difficulty or "").strip().lower()
    if difficulty not in ("easy", "medium", "hard"):
        difficulty = "medium"
    try:
        results = get_vector_store().search(ctx["user_id"], topic, 8)
    except ImportError:
        return DEP_MSG
    if not results:
        return NO_DOC_MSG
    prompt = (f"Using ONLY the excerpts below, write {n} {difficulty} multiple-choice questions about \"{topic}\". "
              "Each question has exactly 4 options, the letter of the correct option (A, B, C or D) in "
              "\"correct\", and a one-sentence explanation. Do not add facts that are not in the excerpts. "
              "Reply with JSON only.\n\nExcerpts:\n" + _excerpts(results))
    data = llm_client.chat_once(prompt, QUIZ_SCHEMA)
    raw = data.get("questions") if isinstance(data, dict) else None
    good = []
    for q in (raw or []):
        if not isinstance(q, dict):
            continue
        question = str(q.get("question", "")).strip()
        options = q.get("options")
        letter = str(q.get("correct", "")).strip().upper()[:1]
        if not question or not isinstance(options, list) or len(options) != 4 or letter not in "ABCD" or not letter:
            continue
        options = [re.sub(r"^[A-Da-d][\).:]\s+", "", str(o).strip()) for o in options]
        if not all(options):
            continue
        good.append((question, options, letter, str(q.get("explanation", "")).strip()))
    good = good[:n]
    if not good:
        return "I could not make a quiz from the document for that topic. Try a different topic."
    out = [f"Quiz: {topic} ({difficulty}, {len(good)} questions)", ""]
    for i, (question, options, _, _) in enumerate(good, 1):
        out.append(f"{i}. {question}")
        out += [f"{'ABCD'[k]}) {o}" for k, o in enumerate(options)]
        out.append("")
    out.append("Answer key:")
    for i, (_, _, letter, expl) in enumerate(good, 1):
        out.append(f"{i}. {letter} - {expl}" if expl else f"{i}. {letter}")
    return "\n".join(out)
