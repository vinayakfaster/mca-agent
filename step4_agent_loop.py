import ast
import json
import logging
import operator
import os
import re
from datetime import datetime

import requests

from conversation_store import save_conversation, load_conversation, list_conversations
from tools_registry import register, get_tools, call_tool, make_ctx, REGISTRY

log = logging.getLogger("agent")

url = os.getenv("OLLAMA_URL", "http://localhost:11434/api/chat")
MODEL = os.getenv("OLLAMA_MODEL", "qwen3:8b")
OLLAMA_TIMEOUT = float(os.getenv("OLLAMA_TIMEOUT", "300"))   # local models can be slow
HTTP_TIMEOUT = 15                                            # weather lookups


# ---------------------------------------------------------------------------
# "Should this tool be offered for this message?" checks (keyword gates).
# Defined first because the @register lines below use them.
# ---------------------------------------------------------------------------

def user_wants_calculation(user_message):
    """
    True if the user asked for maths/comparison: either a keyword ("add", "calculate", "jod"...)
    or a "number operator number" pattern such as "25 + 17" (no keyword needed).
    """
    calculation_keywords = [
        "add", "sum", "total", "combined", "plus", "minus", "subtract",
        "multiply", "divide", "calculate", "compare", "difference",
        "average", "percent", "jod", "ghata", "guna", "compare"
    ]
    message_lower = user_message.lower()
    has_keyword = any(keyword in message_lower for keyword in calculation_keywords)
    has_math_symbol = bool(re.search(r"\d+\s*[\+\-\*/]\s*\d+", user_message))
    return has_keyword or has_math_symbol


def user_wants_old_search(user_message):
    """True if the user is asking about a PAST/older chat (not the current one)."""
    old_chat_keywords = [
        "pichli baar", "pichhli baar", "purani", "purana", "purane",
        "pehle", "previously", "last time", "last session", "last chat",
        "old chat", "old conversation", "past conversation", "before this"
    ]
    message_lower = user_message.lower()
    return any(keyword in message_lower for keyword in old_chat_keywords)


# ---------------------------------------------------------------------------
# TOOLS  (to add one: write the function, put @register above it - that is all)
# ---------------------------------------------------------------------------

@register(
    name="get_weather",
    description="Get the current real-time weather for a given city. Returns the temperature and humidity.",
    properties={"city": {"type": "string", "description": "The name of the city"}},
    required=["city"],
)
def get_weather(city):
    try:
        geo_response = requests.get("https://geocoding-api.open-meteo.com/v1/search",
                                    params={"name": city, "count": 1}, timeout=HTTP_TIMEOUT)
        geo_response.raise_for_status()
        geo_data = geo_response.json()

        if "results" not in geo_data or len(geo_data["results"]) == 0:
            return f"'{city}' naam ka shehar nahi mila."

        lat = geo_data["results"][0]["latitude"]
        lon = geo_data["results"][0]["longitude"]

        weather_response = requests.get("https://api.open-meteo.com/v1/forecast", params={
            "latitude": lat,
            "longitude": lon,
            "current": "temperature_2m,relative_humidity_2m,weather_code"
        }, timeout=HTTP_TIMEOUT)
        weather_response.raise_for_status()
        weather_data = weather_response.json()

        temp = weather_data["current"]["temperature_2m"]
        humidity = weather_data["current"]["relative_humidity_2m"]
        return f"The temperature in {city} is exactly {temp} degrees Celsius, humidity {humidity}%."
    except requests.RequestException:
        return f"Could not fetch the weather for '{city}' right now (weather service unreachable)."


# Safe maths: parse the expression into a tree and allow only numbers and + - * / // % **.
# This replaces eval(), which could be frozen by input like 9**9**9**9.
_BIN_OPS = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul,
            ast.Div: operator.truediv, ast.FloorDiv: operator.floordiv, ast.Mod: operator.mod,
            ast.Pow: operator.pow}
_UNARY_OPS = {ast.UAdd: operator.pos, ast.USub: operator.neg}


def _eval_node(node):
    if isinstance(node, ast.Expression):
        return _eval_node(node.body)
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)) and not isinstance(node.value, bool):
        return node.value
    if isinstance(node, ast.UnaryOp) and type(node.op) in _UNARY_OPS:
        return _UNARY_OPS[type(node.op)](_eval_node(node.operand))
    if isinstance(node, ast.BinOp) and type(node.op) in _BIN_OPS:
        left, right = _eval_node(node.left), _eval_node(node.right)
        if isinstance(node.op, ast.Pow) and abs(right) > 100:
            raise ValueError("exponent too large (max 100)")
        result = _BIN_OPS[type(node.op)](left, right)
        if isinstance(result, int) and result.bit_length() > 4096:
            raise ValueError("result too large")
        return result
    raise ValueError("only plain numbers and + - * / // % ** ( ) are allowed")


@register(
    name="calculate",
    description=("Evaluate a basic math expression using ONLY plain numbers, e.g. '25 + 4'. "
                 "Never put a function call or city name inside this - only numbers you already have."),
    properties={"expression": {"type": "string", "description": "A math expression using only numbers, e.g. '25.1 + 28.3'"}},
    required=["expression"],
    when=user_wants_calculation,
)
def calculate(expression):
    try:
        if len(expression) > 200:
            return "Invalid expression - too long."
        result = _eval_node(ast.parse(expression.strip(), mode="eval"))
        if isinstance(result, float):
            result = round(result, 10)
        return f"Result: {result}"
    except ZeroDivisionError:
        return "Error calculating: division by zero."
    except (ValueError, SyntaxError, OverflowError, RecursionError) as e:
        return f"Invalid expression - {e}. Use only plain numbers and + - * / ( )."


@register(
    name="search_old_conversations",
    description=(
        "Search the user's PREVIOUS chat sessions (not this current conversation) "
        "for information discussed earlier. Use this ONLY when the user refers to "
        "something from a past/older session, e.g. 'pichli baar maine kya poocha tha', "
        "'what did I ask before', 'my last conversation about X'. "
        "Do NOT use this for anything already visible in the current conversation."
    ),
    properties={"query": {"type": "string", "description": "Keyword(s) to search for, e.g. 'weather', 'Delhi'"}},
    required=["query"],
    needs_ctx=True,                    # gets ctx["user_id"] and ctx["conversation_id"] automatically
    when=user_wants_old_search,
)
def search_old_conversations(query, ctx):
    """Search every other saved chat of this user for `query` (the current chat is skipped)."""
    user_id, current_conversation_id = ctx["user_id"], ctx.get("conversation_id")
    query_lower = query.lower()
    matches = []

    for conv_id in list_conversations(user_id):
        if conv_id == current_conversation_id:
            continue
        for msg in load_conversation(user_id, conv_id):
            role = msg.get("role")
            content = msg.get("content") or ""
            if role in ("user", "assistant") and query_lower in content.lower():
                matches.append(f"[{conv_id}] {role}: {content[:200]}")

    if not matches:
        return f"'{query}' ke baare mein koi purani conversation nahi mili."
    return "\n".join(matches[:5])      # top 5 only, so the context window does not fill up


# Older code could bind tools at runtime with  tool_functions["name"] = callable.
# That still works (it overrides the registry), but you should not need it any more.
tool_functions = {}


# ---------------------------------------------------------------------------
# Context-window management (unchanged logic)
# ---------------------------------------------------------------------------

MAX_MESSAGES = 16   # thoda badhaya - summarization kam frequent ho, drift kam ho
KEEP_RECENT = 8     # yeh aakhri N messages hamesha as-is rakho, summarize mat karo

SUMMARY_TAG = "[Condensed history of THIS SAME current chat, for context]"


def summarize_old_messages(old_messages, previous_summary=None):
    """
    Turns old messages into one short summary. If a previous summary exists it is passed in
    explicitly and the model is told to keep all its facts - this stops the
    "summary of a summary of a summary" drift bug.
    """
    text_parts = []

    if previous_summary:
        text_parts.append(f"EARLIER SUMMARY (must keep all these facts): {previous_summary}")

    for m in old_messages:
        role = m.get("role")
        content = m.get("content") or ""
        if not content:
            continue  # assistant messages that only hold tool_calls have empty content
        if role == "tool":
            text_parts.append(f"[tool result]: {content}")
        else:
            text_parts.append(f"{role}: {content}")

    conversation_text = "\n".join(text_parts)

    summary_prompt = (
        "You are updating a running summary of an ongoing conversation. "
        "Below is the EARLIER SUMMARY (if present) followed by NEW messages. "
        "Write an UPDATED summary in 3-5 short sentences that includes "
        "EVERY fact from the earlier summary PLUS the new information. "
        "Do NOT drop any city name, number, or fact that was already mentioned. "
        "Be careful to attach each number/fact to the CORRECT city or topic - "
        "do not mix up which number belongs to which city.\n\n"
        f"{conversation_text}"
    )

    payload = {
        "model": MODEL,
        "messages": [{"role": "user", "content": summary_prompt}],
        "stream": False,
        "think": False,
        "options": {"temperature": 0.2}
    }
    response = requests.post(url, json=payload, timeout=OLLAMA_TIMEOUT)
    response.raise_for_status()
    return response.json()["message"]["content"]


def manage_context_window(messages):
    """
    If the message list gets long, replace the older part with one short summary message.
    The system prompt (index 0) is never touched. If index 1 is already one of our summary
    messages, its text is passed on as previous_summary so no facts are lost.
    """
    if len(messages) <= MAX_MESSAGES:
        return messages

    system_msg = messages[0]

    previous_summary = None
    start_index = 1

    if len(messages) > 1:
        second_msg = messages[1]
        if second_msg.get("role") == "system" and SUMMARY_TAG in (second_msg.get("content") or ""):
            previous_summary = second_msg["content"].replace(f"{SUMMARY_TAG}: ", "")
            start_index = 2

    old_messages = messages[start_index:-KEEP_RECENT]
    recent_messages = messages[-KEEP_RECENT:]

    log.info("Context is long (%d messages) - summarizing the oldest %d", len(messages), len(old_messages))
    summary_text = summarize_old_messages(old_messages, previous_summary)

    summary_message = {"role": "system", "content": f"{SUMMARY_TAG}: {summary_text}"}
    return [system_msg, summary_message] + recent_messages


# ---------------------------------------------------------------------------
# Per-conversation fact tracker.
# FIX: this used to be ONE global set, so on a server with several users, cities one user
# asked about leaked into everybody else's prompts. Now it is keyed by conversation.
# ---------------------------------------------------------------------------

_cities_by_conversation = {}

SYSTEM_PROMPT = (
    "You are a careful agent that uses tools step by step. "
    "Rules: "
    "1. Call only ONE tool at a time, one step at a time. "
    "2. Never nest a tool call inside another tool's arguments (e.g. never write get_weather(...) inside calculate). "
    "3. If a task needs data from multiple tools, first call the tools separately to get plain numbers, "
    "then in a LATER step call calculate using only those plain numbers you already received. "
    "4. Never invent, guess, or assume any number that wasn't explicitly given to you in a tool result. "
    "5. If the user asks about something from a PAST/OLDER SESSION (a different, previous chat, not this one), "
    "use the search_old_conversations tool. "
    "6. Any message labeled '[Condensed history of THIS SAME current chat, for context]' is part of THIS SAME CURRENT "
    "conversation - it has just been condensed to save space. Read it directly to answer questions about what was "
    "discussed earlier in THIS chat. Do NOT call search_old_conversations for information that is "
    "already visible to you in this summary or in the messages above. "
    "7. If the user asks for multiple items (e.g. weather for several cities), you must keep calling "
    "the tool for EACH remaining item, one at a time, until ALL of them are done. "
    "Do NOT write a text message like 'I will now check X' instead of calling the tool - "
    "that is treated as your FINAL answer and stops you from continuing. "
    "Only write your final text answer after every requested item has been fetched via a tool call."
)

# Extra guidance used ONLY while the Study tab is active. It is sent to the model with each
# request but never saved into the conversation history.
STUDY_HINT = (
    "STUDY mode: the user is working with their uploaded PDFs. "
    "Use load_pdf when they name a file, search_documents to answer questions about it, "
    "generate_flashcards and create_quiz when asked. Answer ONLY from the excerpts a tool returns, "
    "mention the file name, and if nothing relevant was found say so. "
    "Flashcards and quizzes come back finished, so do not rewrite them."
)


def run_agent(messages, user_message, max_turns=8, module=None, ctx=None):
    """
    module: which frontend tab is active ("study", "data", "code", "pay") or None.
            "general" tools are always offered; a module's tools only when it is active.
    ctx:    make_ctx(user_id, conversation_id, module) - needed by tools that read the
            user's files or past chats. Optional, so older callers keep working.
    """
    available_tools = get_tools(module, user_message)

    messages.append({"role": "user", "content": user_message})

    # messages[:] = ... replaces the list's CONTENT, so the caller's variable sees the update.
    try:
        messages[:] = manage_context_window(messages)
    except requests.RequestException:
        log.exception("Summarizing failed; continuing with the full history")

    facts_key = (ctx or {}).get("conversation_id") or "default"
    cities = _cities_by_conversation.setdefault(facts_key, set())

    for turn in range(max_turns):
        log.info("--- TURN %d ---", turn + 1)

        # Extra system messages are added for this one API call only and are NOT saved in `messages`.
        extra = []
        if module == "study":
            extra.append({"role": "system", "content": STUDY_HINT})
        if cities:
            extra.append({
                "role": "system",
                "content": "[Reliable fact - do not doubt this]: Cities whose weather has been checked so far in this chat: "
                           + ", ".join(sorted(cities)) + "."
            })
        payload_messages = messages + extra

        payload = {
            "model": MODEL,
            "messages": payload_messages,
            "tools": available_tools,
            "stream": False,
            "think": False,
            "options": {
                "temperature": 0.3,
                "repeat_penalty": 1.2
            }
        }
        # Ollama errors (down, too slow, model missing) are NOT caught here on purpose:
        # backend/main.py turns them into clear 503 / 504 / 502 messages.
        response = requests.post(url, json=payload, timeout=OLLAMA_TIMEOUT)
        response.raise_for_status()
        assistant_message = response.json()["message"]

        messages.append(assistant_message)

        if "tool_calls" in assistant_message and assistant_message["tool_calls"]:
            already_called = set()
            direct_result = None   # set when a "direct" tool (flashcards, quiz) produced the finished answer

            for call in assistant_message["tool_calls"]:
                tool_name = call["function"]["name"]
                tool_args = call["function"].get("arguments", {})

                call_signature = (tool_name, json.dumps(tool_args, sort_keys=True, default=str))
                if call_signature in already_called:
                    log.info("Skipped duplicate call: %s(%s)", tool_name, tool_args)
                    continue
                already_called.add(call_signature)

                log.info("Model asked for: %s(%s)", tool_name, tool_args)
                result = call_tool(tool_name, tool_args, ctx=ctx, overrides=tool_functions)
                log.info("Tool result: %s", result[:200])

                # A "direct" tool already wrote the text for the user: return it as-is (one model call
                # fewer, and the small model cannot shorten or garble it). Errors still go back to the model.
                tool = REGISTRY.get(tool_name)
                if (tool is not None and tool.direct and not result.startswith("Error")
                        and len(assistant_message["tool_calls"]) == 1):
                    direct_result = result

                # Deterministic tracker (no LLM): remember cities whose weather really came back.
                if tool_name == "get_weather" and result.startswith("The temperature in") and isinstance(tool_args, dict):
                    city_name = str(tool_args.get("city", "")).strip().title()
                    if city_name:
                        cities.add(city_name)

                messages.append({"role": "tool", "tool_name": tool_name, "content": result})

            if direct_result is not None:
                messages.append({"role": "assistant", "content": direct_result})   # keeps the saved history valid
                return direct_result

            continue

        else:
            final_text = assistant_message.get("content") or ""

            stripped = final_text.strip()
            if stripped.startswith("{") and '"name"' in stripped and '"parameters"' in stripped:
                log.warning("Model wrote a tool call as text instead of calling it: %s", stripped[:200])
                return (
                    "Mujhe iska poora jawaab nahi mil paaya - model confuse ho gaya. "
                    "Kripya sawaal ko aur simple/step-by-step tareeke se poochho."
                )

            # If the model only wrote "I will now do X" (no tool call) and turns remain, nudge it on.
            narration_phrases = ["i will now", "let me check", "let me now", "i'll now", "next i will", "now i will"]
            looks_like_narration = any(phrase in stripped.lower() for phrase in narration_phrases)

            if looks_like_narration and turn < max_turns - 1:
                log.info("Model only described its plan - sending a nudge")
                messages.append({
                    "role": "user",
                    "content": "Please continue - call the tool for the next remaining item now, don't just describe your plan."
                })
                continue

            return final_text

    return "Turn limit khatam ho gayi, kaam poora nahi hua."


# ---------------------------------------------------------------------------
# Command-line mode (for testing without the website)
# ---------------------------------------------------------------------------

def get_current_user_id():
    """
    NOW: asks for a username (placeholder).
    LATER: with Google OAuth login this returns the logged-in user's id; everything else
    keeps working because save/load already take user_id as a parameter.
    """
    user_id = input("Apna username/email daalo (login se pehle): ").strip()
    return user_id or "guest"


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    print("=== AI Agent (type 'exit' to quit) ===")

    USER_ID = get_current_user_id()
    CONVERSATION_ID = "chat_" + datetime.now().strftime("%Y%m%d_%H%M%S")

    past_chats = list_conversations(USER_ID)
    print(f"[INFO] {USER_ID} ki {len(past_chats)} purani chat(s) mili (unhe touch nahi kiya).")
    print(f"[INFO] Yeh naya session hai: {CONVERSATION_ID}")

    ctx = make_ctx(USER_ID, CONVERSATION_ID)
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]

    while True:
        user_input = input("\nWrite Faaa: ")

        if user_input.lower() in ["exit", "quit"]:
            save_conversation(USER_ID, CONVERSATION_ID, messages)
            print("[INFO] Conversation save ho gayi. Bye!")
            break

        final_answer = run_agent(messages, user_input, ctx=ctx)
        save_conversation(USER_ID, CONVERSATION_ID, messages)

        print("\n=== FINAL ANSWER ===")
        print(final_answer)
