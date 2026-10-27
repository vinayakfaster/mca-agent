"""
Run with:  python -m unittest test_phase0 test_study -v

Real: pypdf reading an actual PDF, the file store, the tool registry, the agent loop.
Stand-ins: ChromaDB (a small in-memory fake that is deliberately STRICT, e.g. it errors if you ask for
more results than exist) and the language model. Needs no internet, Ollama or GPU.
"""
import os
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock

os.environ["DATA_DIR"] = tempfile.mkdtemp(prefix="agent_study_test_")

# ---------------------------------------------------------------- fake chromadb
_PERSIST = {}


class FakeCollection:
    def __init__(self):
        self.rows = {}

    @staticmethod
    def _match(meta, where):
        return all(meta.get(k) == v for k, v in (where or {}).items())

    def count(self):
        return len(self.rows)

    def get(self, where=None, include=None):
        ids = [i for i, (_, m) in self.rows.items() if self._match(m, where)]
        return {"ids": ids, "metadatas": [self.rows[i][1] for i in ids]}

    def add(self, ids, documents, metadatas):
        assert len(ids) <= 128, "batch too big"
        for i, d, m in zip(ids, documents, metadatas):
            self.rows[i] = (d, m)

    def delete(self, ids=None, where=None):
        for i in [i for i, (_, m) in list(self.rows.items()) if (ids and i in ids) or (where and self._match(m, where))]:
            del self.rows[i]

    def query(self, query_texts, n_results, where=None):
        pool = [(i, d, m) for i, (d, m) in self.rows.items() if self._match(m, where)]
        if n_results > len(pool):
            raise RuntimeError("Number of requested results is larger than the number of elements")
        words = set(query_texts[0].lower().split())
        pool.sort(key=lambda r: -len(words & set(r[1].lower().split())))
        pool = pool[:n_results]
        return {"documents": [[d for _, d, _ in pool]], "metadatas": [[m for _, _, m in pool]],
                "distances": [[0.1 * k for k in range(len(pool))]]}


class FakeClient:
    def __init__(self, path):
        self.cols = _PERSIST.setdefault(path, {})

    def get_or_create_collection(self, name, embedding_function=None):
        assert 3 <= len(name) <= 63 and name.replace("_", "").isalnum(), name
        return self.cols.setdefault(name, FakeCollection())


chroma = types.ModuleType("chromadb")
chroma.PersistentClient = FakeClient
chroma_utils = types.ModuleType("chromadb.utils")
chroma_ef = types.ModuleType("chromadb.utils.embedding_functions")
chroma_ef.SentenceTransformerEmbeddingFunction = lambda model_name: object()
chroma_utils.embedding_functions = chroma_ef
sys.modules.update({"chromadb": chroma, "chromadb.utils": chroma_utils,
                    "chromadb.utils.embedding_functions": chroma_ef})

try:
    import conversation_store  # noqa: F401
except ImportError:
    stub = types.ModuleType("conversation_store")
    stub.save_conversation = lambda u, c, m: None
    stub.load_conversation = lambda u, c: []
    stub.list_conversations = lambda u: []
    sys.modules["conversation_store"] = stub

import agent
import file_store
import tools_registry as tr
from study_companion import pdf_processor, study_tools, vector_store

# ---------------------------------------------------------------- a real PDF
TOPICS = [
    "Photosynthesis converts light energy into chemical energy stored in glucose",
    "Chlorophyll in the chloroplasts absorbs mostly red and blue light",
    "The light reactions happen in the thylakoid membranes and produce ATP and NADPH",
    "The Calvin cycle uses ATP and NADPH to fix carbon dioxide into sugar",
    "Mitochondria perform cellular respiration and release energy from glucose",
    "Cellular respiration has three stages glycolysis the Krebs cycle and the electron transport chain",
]


def make_pdf(pages):
    n = len(pages)
    font_id = 3 + 2 * n
    kids = " ".join(f"{3 + 2 * i} 0 R" for i in range(n))
    objs = [b"<< /Type /Catalog /Pages 2 0 R >>", f"<< /Type /Pages /Kids [{kids}] /Count {n} >>".encode()]
    for i, lines in enumerate(pages):
        content = "BT /F1 11 Tf 40 760 Td 14 TL " + " ".join(f"({l}) Tj T*" for l in lines) + " ET"
        objs.append(f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents {4 + 2 * i} 0 R "
                    f"/Resources << /Font << /F1 {font_id} 0 R >> >> >>".encode())
        objs.append(f"<< /Length {len(content)} >>\nstream\n{content}\nendstream".encode())
    objs.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")
    out, offs = b"%PDF-1.4\n", []
    for i, o in enumerate(objs, 1):
        offs.append(len(out))
        out += f"{i} 0 obj\n".encode() + o + b"\nendobj\n"
    xref = len(out)
    out += f"xref\n0 {len(objs) + 1}\n".encode() + b"0000000000 65535 f \n"
    out += b"".join(f"{o:010d} 00000 n \n".encode() for o in offs)
    out += f"trailer\n<< /Size {len(objs) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF".encode()
    return out


BIOLOGY_PDF = make_pdf([TOPICS * 3, TOPICS * 3])      # 2 pages, ~2700 characters of text


def fresh_store():
    _PERSIST.clear()
    study_tools._store = None


def ctx_for(uid, module="study"):
    return {"user_id": uid, "conversation_id": "chat_x", "module": module, "user_dir": file_store.user_dir(uid)}


def upload(uid, name, data=BIOLOGY_PDF):
    return file_store.save_bytes(uid, name, data)


# ---------------------------------------------------------------- tests
class PdfProcessing(unittest.TestCase):
    def test_reads_a_real_pdf_and_chunks_it(self):
        p = Path(tempfile.mkdtemp()) / "bio.pdf"
        p.write_bytes(BIOLOGY_PDF)
        text = pdf_processor.extract_text_from_pdf(str(p))
        self.assertIn("Photosynthesis converts light energy", text)
        self.assertNotIn("   ", text)
        doc = pdf_processor.process_pdf(str(p), doc_id="abc", display_name="Biology.pdf")
        self.assertEqual(doc["document_id"], "abc")
        self.assertEqual(doc["filename"], "Biology.pdf")
        self.assertGreaterEqual(doc["total_chunks"], 3)
        self.assertEqual(doc["chunks"][0]["chunk_id"], "abc_chunk_0")
        self.assertIsNone(pdf_processor.process_pdf("/no/such/file.pdf"))

    def test_bad_pdfs_give_friendly_errors(self):
        p = Path(tempfile.mkdtemp()) / "bad.pdf"
        p.write_bytes(b"this is not a pdf at all")
        with self.assertRaises(ValueError) as cm:
            pdf_processor.extract_text_from_pdf(str(p))
        self.assertIn("could not be opened", str(cm.exception))
        p.write_bytes(BIOLOGY_PDF)
        with mock.patch.object(pdf_processor, "MAX_PDF_PAGES", 1):
            with self.assertRaises(ValueError) as cm:
                pdf_processor.extract_text_from_pdf(str(p))
        self.assertIn("limit", str(cm.exception))


class Store(unittest.TestCase):
    def setUp(self):
        fresh_store()
        self.vs = vector_store.VectorStore("./test_chroma")

    def doc(self, doc_id, n, name="a.pdf"):
        return {"document_id": doc_id, "filename": name, "total_chunks": n,
                "chunks": [{"chunk_id": f"{doc_id}_chunk_{i}", "document_id": doc_id, "chunk_index": i,
                            "text": f"chunk {i} about topic {doc_id}"} for i in range(n)]}

    def test_users_are_isolated(self):
        self.vs.add_document("alice", self.doc("d1", 3))
        self.assertEqual(len(self.vs.search("alice", "topic", 3)), 3)
        self.assertEqual(self.vs.search("bob", "topic", 3), [])
        self.assertEqual(self.vs.list_documents("bob"), [])

    def test_reload_replaces_stale_chunks(self):
        self.vs.add_document("u", self.doc("d1", 5))
        self.vs.add_document("u", self.doc("d1", 2))
        self.assertEqual(self.vs.list_documents("u")[0]["chunks"], 2)

    def test_big_documents_are_batched(self):
        self.vs.add_document("u", self.doc("big", 300))
        self.assertEqual(self.vs.list_documents("u")[0]["chunks"], 300)

    def test_n_results_larger_than_available_is_safe(self):
        self.vs.add_document("u", self.doc("d1", 2, "a.pdf"))
        self.vs.add_document("u", self.doc("d2", 4, "b.pdf"))
        self.assertEqual(len(self.vs.search("u", "topic", 8)), 6)
        self.assertEqual(len(self.vs.search("u", "topic", 8, filename="a.pdf")), 2)
        self.assertEqual(self.vs.search("u", "topic", 8, filename="missing.pdf"), [])

    def test_delete(self):
        self.vs.add_document("u", self.doc("d1", 2))
        self.vs.delete_document("u", "d1")
        self.assertEqual(self.vs.list_documents("u"), [])


class Tools(unittest.TestCase):
    def setUp(self):
        fresh_store()

    def call(self, name, args, uid="alice"):
        return tr.call_tool(name, args, ctx=ctx_for(uid))

    def test_registered_only_for_the_study_module(self):
        names = lambda m: [t["function"]["name"] for t in tr.get_tools(m, "hello")]
        self.assertEqual(names(None), ["get_weather"])
        for t in ("load_pdf", "search_documents", "generate_flashcards", "create_quiz", "list_documents"):
            self.assertIn(t, names("study"))
            self.assertNotIn(t, names("data"))
        self.assertLessEqual(len(names("study")), tr.MAX_TOOLS_PER_REQUEST)

    def test_load_then_search(self):
        upload("alice", "Biology Notes.pdf")
        self.assertIn("Loaded 'Biology Notes.pdf'", self.call("load_pdf", {"file": "biology notes"}))   # sloppy name works
        out = self.call("search_documents", {"query": "What does chlorophyll absorb light"})
        self.assertIn("Answer ONLY from these excerpts", out)
        self.assertIn("Chlorophyll", out)
        self.assertIn("Biology Notes.pdf", out)
        self.assertNotIn("...", out)                       # no more 300-character cut-off

    def test_path_tricks_and_other_users_files_are_refused(self):
        upload("alice", "private.pdf")
        for ref in ["../../etc/passwd", "C:\\Windows\\win.ini", "/etc/hosts", "private.pdf.exe"]:
            self.assertIn("could not find", self.call("load_pdf", {"file": ref}, uid="alice"), ref)
        self.assertIn("could not find", self.call("load_pdf", {"file": "private.pdf"}, uid="bob"))
        self.assertIn("could not find", self.call("load_pdf", {"file": upload("alice", "x.pdf")["id"]}, uid="bob"))

    def test_sample_folder_works_but_only_by_name(self):
        d = Path(tempfile.mkdtemp())
        (d / "sample.pdf").write_bytes(BIOLOGY_PDF)
        with mock.patch.object(study_tools, "DOCS_DIR", d):
            self.assertIn("Loaded 'sample.pdf'", self.call("load_pdf", {"file": "sample.pdf"}))
            self.assertIn("Loaded 'sample.pdf'", self.call("load_pdf", {"file": "../../anything/sample.pdf"}))
            self.assertIn("sample document", self.call("list_documents", {}))

    def test_unreadable_and_empty_pdfs(self):
        upload("alice", "broken.pdf", b"not a pdf")
        self.assertIn("could not be opened", self.call("load_pdf", {"file": "broken.pdf"}))
        upload("alice", "blank.pdf", make_pdf([[" "]]))
        self.assertIn("no readable text", self.call("load_pdf", {"file": "blank.pdf"}))

    def test_search_with_nothing_loaded_and_per_user(self):
        self.assertIn("No document is loaded", self.call("search_documents", {"query": "anything"}))
        upload("alice", "bio.pdf")
        self.call("load_pdf", {"file": "bio.pdf"})
        self.assertIn("No document is loaded", self.call("search_documents", {"query": "chlorophyll"}, uid="bob"))

    def test_list_documents(self):
        upload("alice", "a.pdf")
        upload("alice", "b.pdf")
        self.call("load_pdf", {"file": "a.pdf"})
        out = self.call("list_documents", {})
        self.assertRegex(out, r"- a\.pdf \(loaded, \d+ chunks\)")
        self.assertIn("- b.pdf (uploaded, not loaded yet)", out)

    def test_missing_dependencies_give_a_clear_message(self):
        upload("alice", "bio.pdf")
        with mock.patch.object(study_tools, "get_vector_store", side_effect=ImportError("no chromadb")):
            self.assertIn("pip install chromadb", self.call("load_pdf", {"file": "bio.pdf"}))
            self.assertIn("pip install chromadb", self.call("search_documents", {"query": "x"}))

    def test_flashcards(self):
        upload("alice", "bio.pdf")
        self.call("load_pdf", {"file": "bio.pdf"})
        reply = {"cards": [{"question": "What absorbs light?", "answer": "Chlorophyll"},
                           {"question": "", "answer": "dropped"}, {"question": "Where is the Calvin cycle?", "answer": "Stroma"}]}
        with mock.patch.object(study_tools.llm_client, "chat_once", return_value=reply) as m:
            out = self.call("generate_flashcards", {"topic": "photosynthesis", "num_cards": "3"})
        self.assertIn("1. Q: What absorbs light?", out)
        self.assertIn("A: Chlorophyll", out)
        self.assertNotIn("dropped", out)
        self.assertIn("Using ONLY the excerpts", m.call_args[0][0])
        self.assertIn("Photosynthesis", m.call_args[0][0])      # real retrieved text went into the prompt

    def test_quiz_validation(self):
        upload("alice", "bio.pdf")
        self.call("load_pdf", {"file": "bio.pdf"})
        reply = {"questions": [
            {"question": "Which pigment absorbs light?", "options": ["Chlorophyll", "Keratin", "Insulin", "Lipase"], "correct": "a", "explanation": "It is the green pigment."},
            {"question": "Broken: only 3 options", "options": ["a", "b", "c"], "correct": "A", "explanation": ""},
            {"question": "Broken: bad letter", "options": ["a", "b", "c", "d"], "correct": "Z", "explanation": ""}]}
        with mock.patch.object(study_tools.llm_client, "chat_once", return_value=reply):
            out = self.call("create_quiz", {"topic": "pigments", "difficulty": "nonsense"})
        self.assertIn("Quiz: pigments (medium, 1 questions)", out)
        self.assertIn("A) Chlorophyll", out)
        self.assertIn("1. A - It is the green pigment.", out)
        self.assertNotIn("Broken", out)
        with mock.patch.object(study_tools.llm_client, "chat_once", return_value={"questions": []}):
            self.assertIn("could not make a quiz", self.call("create_quiz", {"topic": "pigments"}))

    def test_llm_failure_becomes_an_error_string(self):
        import requests
        upload("alice", "bio.pdf")
        self.call("load_pdf", {"file": "bio.pdf"})
        with mock.patch.object(study_tools.llm_client, "chat_once", side_effect=requests.ConnectionError("down")):
            self.assertTrue(self.call("generate_flashcards", {"topic": "photosynthesis"}).startswith("Error running"))


class FakeResp:
    def __init__(self, d): self.d = d
    def raise_for_status(self): pass
    def json(self): return self.d


class AgentWithStudy(unittest.TestCase):
    def setUp(self):
        fresh_store()

    def run_agent(self, replies, text, module="study", uid="alice"):
        sent, it = [], iter(replies)

        def post(u, json=None, timeout=None):
            sent.append(json)
            return FakeResp({"message": next(it)})
        msgs = [{"role": "system", "content": agent.SYSTEM_PROMPT}]
        with mock.patch("agent.requests.post", post):
            out = agent.run_agent(msgs, text, module=module, ctx=ctx_for(uid, module))
        return out, msgs, sent

    @staticmethod
    def call(name, args):
        return {"role": "assistant", "content": "", "tool_calls": [{"function": {"name": name, "arguments": args}}]}

    def test_search_flow_uses_the_study_hint_and_tools(self):
        upload("alice", "bio.pdf")
        study_tools.load_pdf("bio.pdf", ctx_for("alice"))
        out, msgs, sent = self.run_agent(
            [self.call("search_documents", {"query": "chlorophyll light"}), {"role": "assistant", "content": "It absorbs red and blue light (bio.pdf)."}],
            "what absorbs light in bio.pdf?")
        self.assertIn("red and blue", out)
        tool_msg = [m for m in msgs if m["role"] == "tool"][0]
        self.assertEqual(tool_msg["tool_name"], "search_documents")
        self.assertIn("Chlorophyll", tool_msg["content"])
        self.assertIn("search_documents", [t["function"]["name"] for t in sent[0]["tools"]])
        self.assertTrue(any("STUDY mode" in str(m.get("content")) for m in sent[0]["messages"]))
        self.assertFalse(any("STUDY mode" in str(m.get("content")) for m in msgs))     # hint is never saved

    def test_study_tools_hidden_without_the_study_module(self):
        _, _, sent = self.run_agent([{"role": "assistant", "content": "hi"}], "what absorbs light", module=None)
        self.assertEqual([t["function"]["name"] for t in sent[0]["tools"]], ["get_weather"])
        self.assertFalse(any("STUDY mode" in str(m.get("content")) for m in sent[0]["messages"]))

    def test_flashcards_are_returned_as_is_without_a_second_model_call(self):
        upload("alice", "bio.pdf")
        study_tools.load_pdf("bio.pdf", ctx_for("alice"))
        cards = {"cards": [{"question": "Q one?", "answer": "A one"}]}
        with mock.patch.object(study_tools.llm_client, "chat_once", return_value=cards):
            out, msgs, sent = self.run_agent([self.call("generate_flashcards", {"topic": "photosynthesis"})],
                                             "make flashcards on photosynthesis")
        self.assertEqual(len(sent), 1)                       # only ONE call to the chat model
        self.assertIn("1. Q: Q one?", out)
        self.assertEqual(msgs[-1], {"role": "assistant", "content": out})   # history stays valid

    def test_direct_tool_errors_go_back_to_the_model_instead(self):
        out, msgs, sent = self.run_agent(
            [self.call("generate_flashcards", {"topic": "x"}), {"role": "assistant", "content": "Please upload a PDF first."}],
            "make flashcards")
        # nothing is loaded -> the friendly 'no document' text is returned directly (it is not an 'Error ...')
        self.assertIn("No document is loaded", out)
        self.assertEqual(len(sent), 1)


if __name__ == "__main__":
    unittest.main()
