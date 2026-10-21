"""
EVAL HARNESS - agent ki tool-calling accuracy ko automatically test karta hai.

Yeh file step4_agent_loop.py ko CHHEDTI NAHI - sirf usse IMPORT karke,
alag-alag test-prompts bhej ke check karti hai ki sahi tool call hua ya nahi.

Chalane ka tareeka:
    python eval_harness.py

Isse do cheezein milengi:
1. Terminal mein turant pass/fail dikhega, har test ke saath
2. Ek 'eval_report.md' file banegi - yeh mentor ko dikhane layak hai 
"""

import time
from datetime import datetime

from step4_agent_loop import (
    run_agent,
    tool_functions,
    session_facts,
    search_old_conversations,
    SYSTEM_PROMPT,
)

# NAYA: yeh list record karti hai is TEST ke dauraan kaunse tools kitni baar
# call hue. Real tool_functions ko "wrap" kar denge taaki asal kaam bhi ho
# (real API call jaaye) AUR humein pata bhi chale ki call hui.
call_log = []


def make_logging_wrapper(tool_name, original_func):
    """
    Ek chhota 'spy' banata hai jo asal function ko call karta hai (jaisa
    normal chalta), lekin call hone se pehle apna naam call_log mein
    likh deta hai. Isse humein pata chal jaata hai model ne kya-kya use kiya.
    """
    def wrapper(*args, **kwargs):
        call_log.append(tool_name)
        return original_func(*args, **kwargs)
    return wrapper


def install_spies():
    # get_weather aur calculate ko wrap karo (yeh already tool_functions mein hain)
    for name in list(tool_functions.keys()):
        tool_functions[name] = make_logging_wrapper(name, tool_functions[name])

    # search_old_conversations abhi tool_functions mein nahi hai (real script
    # mein yeh __main__ mein bind hoti hai) - eval ke liye khud bind kar dete hain,
    # ek fake user/conversation ke saath (kyunki humein sirf yeh dekhna hai ki
    # model TOOL CALL karta hai ya nahi, uska real result matter nahi karta).
    def eval_search(query):
        return search_old_conversations("eval_user", "eval_conversation_never_matches", query)

    tool_functions["search_old_conversations"] = make_logging_wrapper(
        "search_old_conversations", eval_search
    )


# ==========================================================================
# TEST CASES - yahan naye test add kar sakte ho jaise-jaise naye tools banao
# ==========================================================================
TEST_CASES = [
    {
        "name": "Single city weather",
        "prompt": "what's the weather in Delhi",
        "expected_tools": ["get_weather"],
    },
    {
        "name": "Simple calculation",
        "prompt": "what is 25 + 17",
        "expected_tools": ["calculate"],
    },
    {
        "name": "Casual greeting - no tool should fire",
        "prompt": "hi, how are you doing today",
        "expected_tools": [],
    },
    {
        "name": "Multi-city weather - tool should fire twice",
        "prompt": "weather in Mumbai and Pune",
        "expected_tools": ["get_weather", "get_weather"],
    },
    {
        "name": "Unknown city - tool fires, error handled gracefully",
        "prompt": "what's the weather in Zzznotarealplace",
        "expected_tools": ["get_weather"],
    },
    {
        "name": "Weather question should NOT trigger calculate",
        "prompt": "temperature in Jaipur right now",
        "expected_tools": ["get_weather"],
    },
]


def run_single_test(case):
    """Ek test-case chalata hai, fresh conversation ke saath, aur result return karta hai."""
    global call_log
    call_log = []
    session_facts["queried_cities"].clear()  # purane test ka data is test mein leak na ho

    messages = [{"role": "system", "content": SYSTEM_PROMPT}]

    start = time.time()
    try:
        answer = run_agent(messages, case["prompt"])
        error = None
    except Exception as e:
        answer = None
        error = str(e)
    elapsed = round(time.time() - start, 2)

    actual_tools = sorted(call_log)
    expected_tools = sorted(case["expected_tools"])
    passed = (actual_tools == expected_tools) and (error is None)

    return {
        "name": case["name"],
        "prompt": case["prompt"],
        "expected_tools": case["expected_tools"],
        "actual_tools": call_log,
        "passed": passed,
        "answer": answer,
        "error": error,
        "elapsed_seconds": elapsed,
    }


def main():
    install_spies()

    print("=== EVAL HARNESS - agent ke tool-calling ko test kar raha hoon ===\n")

    results = []
    for case in TEST_CASES:
        print(f"Test: {case['name']}")
        result = run_single_test(case)
        results.append(result)

        status = "PASS" if result["passed"] else "FAIL"
        print(f"  -> {status}  (expected: {result['expected_tools']}, got: {result['actual_tools']}, {result['elapsed_seconds']}s)")
        if result["error"]:
            print(f"     ERROR: {result['error']}")
        print()

    passed_count = sum(1 for r in results if r["passed"])
    total = len(results)
    pass_rate = round((passed_count / total) * 100, 1)

    print(f"=== RESULT: {passed_count}/{total} tests passed ({pass_rate}%) ===")

    write_report(results, passed_count, total, pass_rate)
    print("\nReport saved to eval_report.md - yeh mentor ko dikhao.")


def write_report(results, passed_count, total, pass_rate):
    lines = []
    lines.append("# Agent evaluation report\n")
    lines.append(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}\n")
    lines.append(f"**Overall: {passed_count}/{total} tests passed ({pass_rate}%)**\n")
    lines.append("| Test | Expected tools | Actual tools | Time | Result |")
    lines.append("|---|---|---|---|---|")

    for r in results:
        status = "PASS" if r["passed"] else "FAIL"
        expected = ", ".join(r["expected_tools"]) or "(none)"
        actual = ", ".join(r["actual_tools"]) or "(none)"
        lines.append(f"| {r['name']} | {expected} | {actual} | {r['elapsed_seconds']}s | {status} |")

    lines.append("\n## Details\n")
    for r in results:
        lines.append(f"### {r['name']}")
        lines.append(f"- Prompt: `{r['prompt']}`")
        lines.append(f"- Expected tool calls: {r['expected_tools']}")
        lines.append(f"- Actual tool calls: {r['actual_tools']}")
        lines.append(f"- Result: **{'PASS' if r['passed'] else 'FAIL'}**")
        if r["error"]:
            lines.append(f"- Error: {r['error']}")
        elif r["answer"]:
            preview = r["answer"][:200].replace("\n", " ")
            lines.append(f"- Agent's answer (preview): {preview}...")
        lines.append("")

    with open("eval_report.md", "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


if __name__ == "__main__":
    main()