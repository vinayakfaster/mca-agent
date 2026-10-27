# study_companion/vector_store.py
import chromadb
from chromadb.utils import embedding_functions

MAX_BATCH = 100


class VectorStore:
    def __init__(self, persist_directory="./chroma_db"):
        self.client = chromadb.PersistentClient(path=persist_directory)
        self.embedding_fn = embedding_functions.SentenceTransformerEmbeddingFunction(
            model_name="all-MiniLM-L6-v2"
        )
        self.collection = self.client.get_or_create_collection(
            name="study_documents", embedding_function=self.embedding_fn
        )

    @staticmethod
    def _where(user_id, extra=None):
        w = {"user_id": user_id}
        if extra:
            w.update(extra)
        return w

    def add_document(self, user_id, document_data):
        if not document_data or not document_data.get("chunks"):
            return False
        chunks = document_data["chunks"]

        # 1) remove stale chunks for this user+document
        old = self.collection.get(where=self._where(user_id, {"document_id": document_data["document_id"]}))
        if old["ids"]:
            for i in range(0, len(old["ids"]), MAX_BATCH):
                self.collection.delete(ids=old["ids"][i:i + MAX_BATCH])

        # 2) add new chunks in batches
        metas = [{"user_id": user_id,
                  "document_id": c["document_id"],
                  "chunk_index": c["chunk_index"],
                  "filename": document_data["filename"]} for c in chunks]
        ids = [c["chunk_id"] for c in chunks]
        texts = [c["text"] for c in chunks]
        for i in range(0, len(ids), MAX_BATCH):
            self.collection.add(ids=ids[i:i + MAX_BATCH],
                                documents=texts[i:i + MAX_BATCH],
                                metadatas=metas[i:i + MAX_BATCH])
        return True

    def search(self, user_id, query, n_results=5, filename=None):
        extra = {"filename": filename} if filename else None
        pool = self.collection.get(where=self._where(user_id, extra))
        if not pool["ids"]:
            return []
        # clamp n_results — never ask for more than exist
        n = min(n_results, len(pool["ids"]))
        results = self.collection.query(query_texts=[query], n_results=n,
                                        where=self._where(user_id, extra))
        out = []
        if results and results["documents"]:
            for i in range(len(results["documents"][0])):
                out.append({"text": results["documents"][0][i],
                            "metadata": results["metadatas"][0][i],
                            "distance": results["distances"][0][i] if "distances" in results else None})
        return out

    def list_documents(self, user_id):
        data = self.collection.get(where=self._where(user_id))
        docs = {}
        for meta in data["metadatas"]:
            did = meta["document_id"]
            d = docs.setdefault(did, {"document_id": did, "filename": meta["filename"], "chunks": 0})
            d["chunks"] += 1
        return sorted(docs.values(), key=lambda d: d["filename"])

    def delete_document(self, user_id, document_id):
        data = self.collection.get(where=self._where(user_id, {"document_id": document_id}))
        if not data["ids"]:
            return False
        self.collection.delete(ids=data["ids"])
        return True
