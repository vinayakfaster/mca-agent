import json
import os
from study_companion.pdf_processor import process_pdf
from study_companion.vector_store import VectorStore

# Global vector store instance (singleton)
_vector_store = None

def get_vector_store():
    global _vector_store
    if _vector_store is None:
        _vector_store = VectorStore()
    return _vector_store

def load_pdf(pdf_path):
    # Auto-detect: agar file study_companion/documents/ mein hai toh wahan bhi check karo
    if not os.path.exists(pdf_path):
        # Try in study_companion/documents/
        alt_path = os.path.join("study_companion", "documents", os.path.basename(pdf_path))
        if os.path.exists(alt_path):
            pdf_path = alt_path
        else:
            return f"File '{pdf_path}' nahi mili."
    
    try:
        doc_data = process_pdf(pdf_path)
        if not doc_data:
            return "PDF process nahi ho paayi."
        
        store = get_vector_store()
        store.add_document(doc_data)
        
        return f"✅ PDF '{doc_data['filename']}' load ho gayi! {doc_data['total_chunks']} chunks index hue."
    except Exception as e:
        return f"Error loading PDF: {e}"

def search_documents(query, n_results=5, document_filter=None):
    """
    Tool: Documents mein search karo
    """
    store = get_vector_store()
    results = store.search(query, n_results, document_filter)
    
    if not results:
        return f"'{query}' ke liye koi relevant chunk nahi mila."
    
    # Results ko readable format mein do
    output = []
    for i, result in enumerate(results, 1):
        output.append(f"[Result {i}]")
        output.append(f"From: {result['metadata'].get('filename', 'Unknown')}")
        output.append(f"Text: {result['text'][:300]}...")
        output.append("---")
    
    return "\n".join(output)

def generate_flashcards(topic, num_cards=5):
    """
    Tool: Topic ke hisaab se flashcards generate karo
    (Vector search use karke relevant content dhoondho, phir LLM se flashcards banwao)
    """
    # Pehle relevant content search karo
    store = get_vector_store()
    results = store.search(topic, n_results=10)
    
    if not results:
        return f"'{topic}' ke liye koi content nahi mila. Flashcards nahi bana sakte."
    
    # Relevant text chunks ko combine karo
    context = "\n\n".join([r["text"] for r in results[:5]])
    
    # LLM se flashcards generate karao
    flashcard_prompt = f"""
    Based on the following text about "{topic}", create {num_cards} flashcards.
    
    Text:
    {context}
    
    Format each flashcard as:
    Q: [Question]
    A: [Answer]
    
    Make them concise and focused on key concepts.
    """
    
    import requests
    payload = {
        "model": "qwen3:8b",
        "messages": [{"role": "user", "content": flashcard_prompt}],
        "stream": False,
        "think": False,
        "options": {"temperature": 0.3}
    }
    response = requests.post("http://localhost:11434/api/chat", json=payload)
    flashcards = response.json()["message"]["content"]
    
    return flashcards

def create_quiz(topic, num_questions=5, difficulty="medium"):
    """
    Tool: Topic ke hisaab se quiz generate karo
    """
    # Similar to flashcards but with multiple choice
    store = get_vector_store()
    results = store.search(topic, n_results=10)
    
    if not results:
        return f"'{topic}' ke liye koi content nahi mila."
    
    context = "\n\n".join([r["text"] for r in results[:5]])
    
    quiz_prompt = f"""
    Based on the following text about "{topic}", create a quiz with {num_questions} multiple-choice questions.
    
    Text:
    {context}
    
    Format each question as:
    Q: [Question]
    A) [Option A]
    B) [Option B]
    C) [Option C]
    D) [Option D]
    Correct: [Letter of correct answer]
    Explanation: [Brief explanation]
    
    Difficulty: {difficulty}
    """
    
    import requests
    payload = {
        "model": "qwen3:8b",
        "messages": [{"role": "user", "content": quiz_prompt}],
        "stream": False,
        "think": False,
        "options": {"temperature": 0.3}
    }
    response = requests.post("http://localhost:11434/api/chat", json=payload)
    quiz = response.json()["message"]["content"]
    
    return quiz

# Tool definitions for agent
study_tools = [
    {
        "type": "function",
        "function": {
            "name": "load_pdf",
            "description": "Load a PDF file and index it for searching. Use this first before searching.",
            "parameters": {
                "type": "object",
                "properties": {
                    "pdf_path": {"type": "string", "description": "Full path to the PDF file"}
                },
                "required": ["pdf_path"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "search_documents",
            "description": "Search through loaded PDFs for relevant content. Use when user asks about document content.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Search query"},
                    "n_results": {"type": "integer", "description": "Number of results to return (default 5)"},
                    "document_filter": {"type": "string", "description": "Specific document ID to search in (optional)"}
                },
                "required": ["query"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "generate_flashcards",
            "description": "Generate flashcards from document content on a specific topic.",
            "parameters": {
                "type": "object",
                "properties": {
                    "topic": {"type": "string", "description": "Topic to create flashcards for"},
                    "num_cards": {"type": "integer", "description": "Number of flashcards (default 5)"}
                },
                "required": ["topic"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "create_quiz",
            "description": "Generate a multiple-choice quiz on a specific topic.",
            "parameters": {
                "type": "object",
                "properties": {
                    "topic": {"type": "string", "description": "Topic to create quiz for"},
                    "num_questions": {"type": "integer", "description": "Number of questions (default 5)"},
                    "difficulty": {"type": "string", "description": "easy/medium/hard (default medium)"}
                },
                "required": ["topic"]
            }
        }
    }
]

study_functions = {
    "load_pdf": load_pdf,
    "search_documents": search_documents,
    "generate_flashcards": generate_flashcards,
    "create_quiz": create_quiz
}