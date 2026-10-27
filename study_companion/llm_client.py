# study_companion/llm_client.py
"""Ask the local Ollama model one question and get JSON back (used for flashcards and quizzes)."""
import json
import os
import re

import requests


def _base_url():
    return os.getenv("OLLAMA_BASE_URL", "http://localhost:11434").rstrip("/")


def _model():
    return os.getenv("OLLAMA_MODEL", "qwen3:8b")


def _parse_json(text):
    text = (text or "").strip()
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text).strip()   # remove ``` fences if the model added them
    try:
        return json.loads(text)
    except ValueError:
        start, end = text.find("{"), text.rfind("}")
        if start != -1 and end > start:
            try:
                return json.loads(text[start:end + 1])
            except ValueError:
                pass
    raise ValueError("The model did not return valid JSON. Please try again.")


def chat_once(prompt, schema=None, temperature=0.2):
    """
    One single-turn call to Ollama. If `schema` (a JSON schema dict) is given, Ollama is forced to
    answer in that shape. Returns the parsed JSON (a dict). Network and HTTP errors are NOT caught
    here on purpose: call_tool() turns them into an 'Error running ...' message for the model.
    """
    payload = {
        "model": _model(),
        "messages": [{"role": "user", "content": prompt}],
        "stream": False,
        "think": False,
        "options": {"temperature": temperature},
    }
    if schema:
        payload["format"] = schema
    r = requests.post(f"{_base_url()}/api/chat", json=payload,
                      timeout=float(os.getenv("OLLAMA_TIMEOUT", "300")))
    r.raise_for_status()
    content = (r.json().get("message") or {}).get("content") or ""
    return _parse_json(content)
