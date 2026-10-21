import requests
import json
import re
from datetime import datetime
from conversation_store import save_conversation, load_conversation, list_conversations

url = "http://localhost:11434/api/chat"

tools = [
    {
        "type": "function",
        "function": {
            "name": "get_weather",
            "description": "Get the current real-time weather for a given city. Returns only the temperature.",
            "parameters": {
                "type": "object",
                "properties": {
                    "city": {"type": "string", "description": "The name of the city"}
                },
                "required": ["city"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "search_old_conversations",
            "description": (
                "Search the user's PREVIOUS chat sessions (not this current conversation) "
                "for information discussed earlier. Use this ONLY when the user refers to "
                "something from a past/older session, e.g. 'pichli baar maine kya poocha tha', "
                "'what did I ask before', 'my last conversation about X'. "
                "Do NOT use this for anything already visible in the current conversation."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Keyword(s) to search for, e.g. 'weather', 'Delhi'"}
                },
                "required": ["query"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "calculate",
            "description": "Evaluate a basic math expression using ONLY plain numbers, e.g. '25 + 4'. Never put a function call or city name inside this - only numbers you already have.",
            "parameters": {
                "type": "object",
                "properties": {
                    "expression": {"type": "string", "description": "A math expression using only numbers, e.g. '25.1 + 28.3'"}
                },
                "required": ["expression"]
            }
        }
    }
]

def get_weather(city):
    geo_url = "https://geocoding-api.open-meteo.com/v1/search"
    geo_response = requests.get(geo_url, params={"name": city, "count": 1})
    geo_data = geo_response.json()

    if "results" not in geo_data or len(geo_data["results"]) == 0:
        return f"'{city}' naam ka shehar nahi mila."

    lat = geo_data["results"][0]["latitude"]
    lon = geo_data["results"][0]["longitude"]

    weather_url = "https://api.open-meteo.com/v1/forecast"
    weather_response = requests.get(weather_url, params={
        "latitude": lat,
        "longitude": lon,
        "current": "temperature_2m,relative_humidity_2m,weather_code"
    })
    weather_data = weather_response.json()

    temp = weather_data["current"]["temperature_2m"]
    humidity = weather_data["current"]["relative_humidity_2m"]

    return f"The temperature in {city} is exactly {temp} degrees Celsius, humidity {humidity}%."

def calculate(expression):
    try:
        allowed_chars = set("0123456789+-*/(). ")
        if not all(c in allowed_chars for c in expression):
            return "Invalid expression - only plain numbers and + - * / ( ) allowed. Do not put function calls or text inside."
        result = eval(expression)
        return f"Result: {result}"
    except Exception as e:
        return f"Error calculating: {e}"

def search_old_conversations(user_id, current_conversation_id, query):
    """
    User ki SAARI purani conversation files (current session ko chhod ke) mein
    'query' keyword dhoondhta hai. Filing-cabinet analogy: har purani file (drawer)
    kholte hain, har user/assistant message check karte hain - kya query ka
    koi word usme mila? Agar mila, woh line result mein daal dete hain.
    """
    query_lower = query.lower()
    matches = []

    for conv_id in list_conversations(user_id):
        if conv_id == current_conversation_id:
            continue  # abhi ki chat khud ko search karne ki zaroorat nahi

        past_messages = load_conversation(user_id, conv_id)
        for msg in past_messages:
            role = msg.get("role")
            content = msg.get("content") or ""
            if role in ("user", "assistant") and query_lower in content.lower():
                # itna hi rakhte hain taaki context window mein zyada jagah na le
                snippet = content[:200]
                matches.append(f"[{conv_id}] {role}: {snippet}")

    if not matches:
        return f"'{query}' ke baare mein koi purani conversation nahi mili."

    # sirf top 5 matches wapas bhejo, warna context bhar jaayega
    return "\n".join(matches[:5])


MAX_MESSAGES = 16   # thoda badhaya - summarization kam frequent ho, drift kam ho
KEEP_RECENT = 8       # yeh aakhri N messages hamesha as-is rakho, summarize mat karo

SUMMARY_TAG = "[Condensed history of THIS SAME current chat, for context]"


def summarize_old_messages(old_messages, previous_summary=None):
    """
    Purane messages ko ek chhoti summary mein convert karta hai.
    NAYA: agar 'previous_summary' diya gaya hai (matlab yeh dusri/teesri baar
    summarize ho raha hai), toh use bhi text mein explicitly shaamil karte hain,
    aur model ko saaf-saaf bolte hain "iske saare facts zaroor rakhna" -
    isse "summary ki summary ki summary" mein info kho jaane ka bug (drift) rukta hai.
    """
    text_parts = []

    if previous_summary:
        text_parts.append(f"EARLIER SUMMARY (must keep all these facts): {previous_summary}")

    for m in old_messages:
        role = m.get("role")
        content = m.get("content") or ""
        if not content:
            continue  # tool_calls wale assistant messages ka content khaali hota hai, skip
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
        "model": "qwen3:8b",
        "messages": [{"role": "user", "content": summary_prompt}],
        "stream": False,
        "think": False,
        "options": {"temperature": 0.2}
    }
    response = requests.post(url, json=payload)
    return response.json()["message"]["content"]


def manage_context_window(messages):
    """
    Agar messages list bahut badi ho jaaye, purane hisse ko summarize karke
    ek chhoti summary-message se replace kar deta hai.
    System prompt (index 0) kabhi touch nahi hota.

    NAYA: agar index 1 pe pehle se hi ek summary-message maujood hai
    (matlab yeh pehli baar nahi, dusri/teesri baar summarize ho raha hai),
    toh us purani summary ko "previous_summary" ke roop mein alag nikaal lete
    hain aur summarizer ko explicitly dete hain - taaki woh naya summary
    banate waqt purane facts na bhool jaaye (drift bug ka fix).
    """
    if len(messages) <= MAX_MESSAGES:
        return messages  # abhi chhoti hai, kuch karne ki zaroorat nahi

    system_msg = messages[0]

    previous_summary = None
    start_index = 1

    # check karo: kya index 1 pehle se hi hamari summary-message hai?
    if len(messages) > 1:
        second_msg = messages[1]
        if second_msg.get("role") == "system" and SUMMARY_TAG in (second_msg.get("content") or ""):
            previous_summary = second_msg["content"].replace(f"{SUMMARY_TAG}: ", "")
            start_index = 2  # is purani summary ko dobara "old_messages" mein mat gino

    old_messages = messages[start_index:-KEEP_RECENT]     # yeh naye-purane summarize honge
    recent_messages = messages[-KEEP_RECENT:]              # yeh as-is rahenge

    print(f"\n[INFO] Context bada ho gaya ({len(messages)} messages) - purane {len(old_messages)} messages summarize kar raha hoon...")
    summary_text = summarize_old_messages(old_messages, previous_summary)
    print(f"[INFO] Summary bani: {summary_text}\n")

    summary_message = {
        "role": "system",
        "content": f"{SUMMARY_TAG}: {summary_text}"
    }

    return [system_msg, summary_message] + recent_messages


def user_wants_calculation(user_message):
    """
    Check karta hai ki user ne calculation/math/comparison explicitly maanga hai ya nahi.
    Do tareeke se check karta hai:
    1. Keywords ("add", "calculate", "jod", waghera)
    2. NAYA: Regex - agar message mein "number + operator + number" pattern hai
       (jaise "25 + 17"), toh woh bhi calculation hai, chahe koi keyword na ho.
       Yeh bug-fix hai: "what is 25 + 17" mein koi keyword nahi thi, isliye
       calculate tool available hi nahi hota tha - eval harness ne yeh pakda.
    """
    calculation_keywords = [
        "add", "sum", "total", "combined", "plus", "minus", "subtract",
        "multiply", "divide", "calculate", "compare", "difference",
        "average", "percent", "jod", "ghata", "guna", "compare"
    ]
    message_lower = user_message.lower()

    has_keyword = any(keyword in message_lower for keyword in calculation_keywords)

    # pattern: ek ya zyada digit, optional spaces, ek operator (+-*/), spaces, digit(s)
    has_math_symbol = bool(re.search(r"\d+\s*[\+\-\*/]\s*\d+", user_message))

    return has_keyword or has_math_symbol


def user_wants_old_search(user_message):
    """
    Check karta hai ki user PURANI/PICHLI conversation ke baare mein poochh raha hai ya nahi.
    Isse hum search_old_conversations tool ko sirf zaroorat pade tabhi model ko dikhate hain -
    baaki (normal) messages mein yeh tool bilkul available hi nahi hoga, isliye model
    galti se bhi use call nahi kar payega jab zaroorat na ho.
    """
    old_chat_keywords = [
        "pichli baar", "pichhli baar", "purani", "purana", "purane",
        "pehle", "previously", "last time", "last session", "last chat",
        "old chat", "old conversation", "past conversation", "before this"
    ]
    message_lower = user_message.lower()
    return any(keyword in message_lower for keyword in old_chat_keywords)

tool_functions = {
    "get_weather": get_weather,
    "calculate": calculate
    # "search_old_conversations" yahan nahi hai - kyunki usko user_id aur
    # current conversation_id chahiye, jo model ko pata nahi hote.
    # Isko __main__ mein runtime par is dict mein add karenge (neeche dekho).
}

# NAYA: yeh ek DETERMINISTIC (LLM-independent) tracker hai. Jab bhi get_weather
# successfully call hoti hai, uski city yahan add hoti hai - plain Python set mein,
# koi LLM guess-work nahi. Yeh summarization ke bug (facts drop/mix ho jaana) se
# bilkul immune hai kyunki isme AI ka koi role nahi, sirf code hai.
session_facts = {
    "queried_cities": set()
}

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
    "6. Any message labeled '[Earlier conversation summary]' is part of THIS SAME CURRENT conversation - "
    "it has just been condensed to save space. Read it directly to answer questions about what was "
    "discussed earlier in THIS chat. Do NOT call search_old_conversations for information that is "
    "already visible to you in this summary or in the messages above. "
    "7. If the user asks for multiple items (e.g. weather for several cities), you must keep calling "
    "the tool for EACH remaining item, one at a time, until ALL of them are done. "
    "Do NOT write a text message like 'I will now check X' instead of calling the tool - "
    "that is treated as your FINAL answer and stops you from continuing. "
    "Only write your final text answer after every requested item has been fetched via a tool call."
)

def run_agent(messages, user_message, max_turns=8):
    # check karo ki calculation aur/ya old-conversation-search chahiye ya nahi
    # (sirf is user_message ke keywords ke basis pe) - dono tools by-default
    # HATA diye jaate hain, sirf zaroorat lagne par wapas jode jaate hain.
    available_tools = [
        t for t in tools
        if t["function"]["name"] not in ("calculate", "search_old_conversations")
    ]

    if user_wants_calculation(user_message):
        calc_tool = next(t for t in tools if t["function"]["name"] == "calculate")
        available_tools.append(calc_tool)

    if user_wants_old_search(user_message):
        search_tool = next(t for t in tools if t["function"]["name"] == "search_old_conversations")
        available_tools.append(search_tool)

    # messages bahar se aa rahi hai (poori history ke saath), hum bas naya user turn append karte hain.
    messages.append({"role": "user", "content": user_message})

    # NAYA: context bahut bada ho gaya toh purana hissa summarize kar do.
    # messages[:] = ... IMPORTANT hai: yeh list ke ANDAR ka content replace karta hai,
    # list ka address (id) same rehta hai - isliye __main__ mein jo "messages"
    # variable hai woh bhi updated content dekhega (reference wahi rehta hai).
    messages[:] = manage_context_window(messages)

    for turn in range(max_turns):
        print(f"\n--- TURN {turn + 1} ---")

        # NAYA: har baar API ko call karne se pehle, tracked facts ko taaza
        # ek chhoti system-message mein daal dete hain. Yeh 'messages' list mein
        # PERMANENTLY save nahi hoti (isliye save_conversation() mein duplicate
        # nahi banegi) - sirf isi API call ke liye temporarily jodi jaati hai.
        payload_messages = messages
        if session_facts["queried_cities"]:
            cities_list = ", ".join(sorted(session_facts["queried_cities"]))
            facts_message = {
                "role": "system",
                "content": f"[Reliable fact - do not doubt this]: Cities whose weather has been checked so far in this chat: {cities_list}."
            }
            payload_messages = messages + [facts_message]

        payload = {
            "model": "qwen3:8b",
            "messages": payload_messages,
            "tools": available_tools,
            "stream": False,
            "think": False,
            "options": {
                "temperature": 0.3,
                "repeat_penalty": 1.2
            }
        }
        response = requests.post(url, json=payload)
        assistant_message = response.json()["message"]

        messages.append(assistant_message)

        if "tool_calls" in assistant_message and assistant_message["tool_calls"]:
            already_called = set()

            for call in assistant_message["tool_calls"]:
                tool_name = call["function"]["name"]
                tool_args = call["function"]["arguments"]

                call_signature = (tool_name, json.dumps(tool_args, sort_keys=True))
                if call_signature in already_called:
                    print(f"Duplicate call skip kiya: {tool_name}({tool_args})")
                    continue

                already_called.add(call_signature)

                print(f"Model ne maanga: {tool_name}({tool_args})")
                func = tool_functions[tool_name]
                result = func(**tool_args)
                print(f"Real result mila: {result}")

                # NAYA: agar get_weather successfully chali (error nahi aaya), toh
                # city ka naam humare deterministic tracker mein daal do - yeh
                # summarization se bilkul alag/safe hai, kyunki isme LLM shaamil nahi.
                if tool_name == "get_weather" and "naam ka shehar nahi mila" not in str(result):
                    city_name = tool_args.get("city", "").strip().title()
                    if city_name:
                        session_facts["queried_cities"].add(city_name)

                messages.append({
                    "role": "tool",
                    "content": str(result)
                })

            continue

        else:
            final_text = assistant_message["content"]

            stripped = final_text.strip()
            if stripped.startswith("{") and '"name"' in stripped and '"parameters"' in stripped:
                print("\n[CHETAVNI] Model ne tool call ko text mein likha, real tool call nahi kiya.")
                print(f"Raw text: {stripped}")
                return (
                    "Mujhe iska poora jawaab nahi mil paaya - model confuse ho gaya. "
                    "Kripya sawaal ko aur simple/step-by-step tareeke se poochho."
                )

            # NAYA: agar model ne sirf "main ab yeh karunga" type text likha (tool call
            # kiye bina), aur turn-limit abhi khatam nahi hui, use "final" mat maano -
            # ek chhota nudge bhej ke usse continue karne ko kaho.
            narration_phrases = ["i will now", "let me check", "let me now", "i'll now", "next i will", "now i will"]
            looks_like_narration = any(phrase in stripped.lower() for phrase in narration_phrases)

            if looks_like_narration and turn < max_turns - 1:
                print(f"\n[INFO] Model sirf bata raha hai 'aage karunga' - tool call nahi kiya. Nudge bhej raha hoon.")
                messages.append({
                    "role": "user",
                    "content": "Please continue - call the tool for the next remaining item now, don't just describe your plan."
                })
                continue

            print("\nModel ka FINAL jawaab:")
            return final_text

    return "Turn limit khatam ho gayi, kaam poora nahi hua."


def get_current_user_id():
    """
    ABHI: user se manually poochh rahe hain (placeholder).
    FUTURE: jab Google OAuth login integrate hoga, yeh function
    login se mile hue email/user-ID ko return karega -
    baaki poora code (save/load) bina kisi change ke chalta rahega,
    kyunki save/load hamesha se hi "user_id" ek parameter ki tarah lete hain.
    """
    user_id = input("Apna username/email daalo (login se pehle): ").strip()
    if not user_id:
        user_id = "guest"
    return user_id


if __name__ == "__main__":
    print("=== AI Agent (type 'exit' to quit) ===")

    USER_ID = get_current_user_id()

    # NAYA: har session pe automatic naya conversation-ID banega (timestamp based)
    # Format: chat_YYYYMMDD_HHMMSS -> jaise chat_20260826_143022
    CONVERSATION_ID = "chat_" + datetime.now().strftime("%Y%m%d_%H%M%S")

    past_chats = list_conversations(USER_ID)
    print(f"[INFO] {USER_ID} ki {len(past_chats)} purani chat(s) mili (unhe touch nahi kiya).")
    print(f"[INFO] Yeh naya session hai: {CONVERSATION_ID}")

    # NAYA: ab jab USER_ID aur CONVERSATION_ID pata chal gaye hain, search tool ko
    # inke saath "bind" kar dete hain - taaki model sirf "query" bheje,
    # baaki (kis user ki, kaunsi chat ko chhod ke search karna hai) yahin se pass ho jaaye.
    def bound_search(query):
        return search_old_conversations(USER_ID, CONVERSATION_ID, query)

    tool_functions["search_old_conversations"] = bound_search

    # naya session hai isliye messages hamesha fresh system-prompt se shuru honge
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]

    while True:
        user_input = input("\nWrite Faaa: ")

        if user_input.lower() in ["exit", "quit"]:
            save_conversation(USER_ID, CONVERSATION_ID, messages)
            print("[INFO] Conversation save ho gayi. Bye!")
            break

        final_answer = run_agent(messages, user_input)
        save_conversation(USER_ID, CONVERSATION_ID, messages)

        print("\n=== FINAL ANSWER ===")
        print(final_answer)