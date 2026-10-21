import json
import os
import re

BASE_DIR = "conversations"  # sab users ka data isi ke andar rahega


def sanitize_id(raw_id: str) -> str:
    """
    User_id ya conversation_id mein sirf safe characters allow karo.
    Yeh zaroori hai kyunki yeh string folder/file naam banegi -
    agar isme '/', '..' jaisi cheezein aa gayin, toh koi file system ke
    galat jagah likh/padh sakta hai (security issue - "path traversal").
    Google login se email aayega (jaise amit@gmail.com) - usme '@' aur '.'
    hote hain, isliye woh allow rakhe hain, sirf slashes/dots-dots hataye hain.
    """
    # sirf letters, numbers, @, ., _, - allow karo; baaki sab '_' se replace
    cleaned = re.sub(r"[^a-zA-Z0-9@._-]", "_", raw_id)
    return cleaned or "unknown_user"


def ensure_user_dir(user_id: str):
    user_id = sanitize_id(user_id)
    path = os.path.join(BASE_DIR, user_id)
    os.makedirs(path, exist_ok=True)
    return path


def save_conversation(user_id: str, conversation_id: str, messages: list):
    user_id = sanitize_id(user_id)
    conversation_id = sanitize_id(conversation_id)

    user_dir = ensure_user_dir(user_id)
    path = os.path.join(user_dir, f"{conversation_id}.json")

    with open(path, "w", encoding="utf-8") as f:
        json.dump(messages, f, ensure_ascii=False, indent=2)


def load_conversation(user_id: str, conversation_id: str) -> list:
    user_id = sanitize_id(user_id)
    conversation_id = sanitize_id(conversation_id)

    path = os.path.join(BASE_DIR, user_id, f"{conversation_id}.json")
    if not os.path.exists(path):
        return []
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def list_conversations(user_id: str) -> list:
    """
    Ek user ki saari conversation-ids return karta hai (file names bina .json ke).
    Future mein UI mein "aapki purani chats" dikhane ke kaam aayega.
    """
    user_id = sanitize_id(user_id)
    user_dir = os.path.join(BASE_DIR, user_id)
    if not os.path.exists(user_dir):
        return []
    return [f[:-5] for f in os.listdir(user_dir) if f.endswith(".json")]