import chromadb
from chromadb.utils import embedding_functions
import os

class VectorStore:
    def __init__(self, persist_directory="./chroma_db"):
        """ChromaDB initialize karo"""
        self.persist_directory = persist_directory
        self.client = chromadb.PersistentClient(path=persist_directory)
        
        # Local embedding model (free, no API key)
        self.embedding_fn = embedding_functions.SentenceTransformerEmbeddingFunction(
            model_name="all-MiniLM-L6-v2"  # Small, fast, decent quality
        )
        
        # Collection name — saare documents ek hi collection mein
        self.collection_name = "study_documents"
        self.collection = self.client.get_or_create_collection(
            name=self.collection_name,
            embedding_function=self.embedding_fn
        )
    
    def add_document(self, document_data):
        """Document ke saare chunks ko vector store mein add karo"""
        if not document_data or "chunks" not in document_data:
            return False
        
        chunks = document_data["chunks"]
        if not chunks:
            return False
        
        # ChromaDB ko data do
        ids = [chunk["chunk_id"] for chunk in chunks]
        texts = [chunk["text"] for chunk in chunks]
        metadatas = [
            {
                "document_id": chunk["document_id"],
                "chunk_index": chunk["chunk_index"],
                "filename": document_data["filename"]
            }
            for chunk in chunks
        ]
        
        # Pehle purane chunks hatao (agar document pehle se exist karta hai)
        existing_doc_ids = [chunk["chunk_id"] for chunk in chunks]
        if existing_doc_ids:
            self.collection.delete(ids=existing_doc_ids)
        
        # Naye chunks add karo
        self.collection.add(
            ids=ids,
            documents=texts,
            metadatas=metadatas
        )
        return True
    
    def search(self, query, n_results=5, filter_document=None):
        """
        Query ke hisaab se similar chunks search karo.
        filter_document = agar specific document mein search karna hai
        """
        where_filter = None
        if filter_document:
            where_filter = {"document_id": filter_document}
        
        results = self.collection.query(
            query_texts=[query],
            n_results=n_results,
            where=where_filter
        )
        
        # Results ko readable format mein convert karo
        formatted_results = []
        if results and results["documents"]:
            for i in range(len(results["documents"][0])):
                formatted_results.append({
                    "text": results["documents"][0][i],
                    "metadata": results["metadatas"][0][i],
                    "distance": results["distances"][0][i] if "distances" in results else None
                })
        
        return formatted_results
    
    def list_documents(self):
        """Saare documents ki list do"""
        # Collection mein saare unique document_ids nikaalo
        all_data = self.collection.get()
        if not all_data or "metadatas" not in all_data:
            return []
        
        docs = set()
        for meta in all_data["metadatas"]:
            if "document_id" in meta:
                docs.add(meta["document_id"])
        
        return sorted(list(docs))
    
    def delete_document(self, document_id):
        """Ek document ko delete karo (saare chunks)"""
        all_data = self.collection.get()
        if not all_data or "metadatas" not in all_data:
            return False
        
        ids_to_delete = []
        for i, meta in enumerate(all_data["metadatas"]):
            if meta.get("document_id") == document_id:
                ids_to_delete.append(all_data["ids"][i])
        
        if ids_to_delete:
            self.collection.delete(ids=ids_to_delete)
            return True
        return False