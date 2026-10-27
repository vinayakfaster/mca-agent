"""
EVAL HARNESS - agent ki tool-calling accuracy ko automatically test karta hai.

Yeh file step4_agent_loop.py ko CHHEDTI NAHI - sirf usse IMPORT karke,
alag-alag test-prompts bhej ke check karti hai ki sahi tool call hua ya nahi.

Chalane ka tareeka (project root se):
    python eval_harness.py

Isse do cheezein milengi:
1. Terminal mein turant pass/fail dikhega, har test ke saath
2. Ek 'eval_report.md' file banegi - yeh mentor ko dikhane layak hai

CHANGE (Phase 0): tools ab tools_registry mein registered hain, isliye spies
registry se bante hain. Test cases aur report ka format bilkul pehle jaisa hai.
"""

import time
from datetime import datetime

from step4_agent_loop import run_agent, tool_functions, SYSTEM_PROMPT
from tools_registry import REGISTRY

# Is TEST ke dauraan kaunse tools kitni baar call hue.
call_log = []

# Fake user/conversation: search tool ko sirf call hona hai, uska real result matter nahi karta.
EVAL_USER = "eval_user"


def make_logging_wrapper(tool_name, original_func, ctx=None):
    """
    Ek chhota 'spy': asal function ko call karta hai (jaisa normal chalta),
    lekin pehle apna naam call_log mein likh deta hai.
    """
    def wrapper(**kwargs):
        call_log.append(tool_name)
        if ctx is not None:
            return original_func(ctx=ctx, **kwargs)
        return original_func(**kwargs)
    return wrapper


def install_spies():
    # Har registered tool ko wrap karo. tool_functions mein daalne se agent
    # registry ki jagah yahi spy call karta hai.
    ctx = {"user_id": EVAL_USER, "conversation_id": "eval_conversation_never_matches"}
    for name, tool in REGISTRY.items():
        tool_functions[name] = make_logging_wrapper(name, tool.func, ctx if tool.needs_ctx else None)


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


def run_single_test(case, index=0):
    """Ek test-case chalata hai, fresh conversation ke saath, aur result return karta hai."""
    global call_log
    call_log = []

    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    # Har test ki apni conversation id: agent ke facts alag-alag rehte hain, purane test ka data leak nahi hota.
    ctx = {"user_id": EVAL_USER, "conversation_id": f"eval_{int(time.time())}_{index}"}

    start = time.time()
    try:
        answer = run_agent(messages, case["prompt"], ctx=ctx)
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
    for i, case in enumerate(TEST_CASES):
        print(f"Test: {case['name']}")
        result = run_single_test(case, i)
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
