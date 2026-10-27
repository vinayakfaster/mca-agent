"""
Run with:  python -m unittest test_phase0 -v
No Ollama, internet or FastAPI needed: the model and weather API are mocked.
"""
import os
import sys
import tempfile
import unittest
from unittest import mock

os.environ["DATA_DIR"] = tempfile.mkdtemp(prefix="agent_test_")

try:
    import conversation_store  # noqa: F401  (your real one, if it is in this folder)
except ImportError:
    import types
    stub = types.ModuleType("conversation_store")
    _db = {}
    stub.save_conversation = lambda u, c, m: _db.__setitem__((u, c), list(m))
    stub.load_conversation = lambda u, c: _db.get((u, c), [])
    stub.list_conversations = lambda u: [c for (uu, c) in _db if uu == u]
    sys.modules["conversation_store"] = stub

import agent
import file_store
import tools_registry as tr


class FakeResp:
    def __init__(self, data): self._d = data
    def raise_for_status(self): pass
    def json(self): return self._d


def tool_call(name, args): return {"role": "assistant", "content": "", "tool_calls": [{"function": {"name": name, "arguments": args}}]}
def text(t): return {"role": "assistant", "content": t}


class Registry(unittest.TestCase):
    def names(self, module=None, msg=""):
        return [t["function"]["name"] for t in tr.get_tools(module, msg)]

    def test_gating(self):
        self.assertEqual(self.names(None, "hello"), ["get_weather"])
        self.assertIn("calculate", self.names(None, "what is 25 + 17"))
        self.assertIn("calculate", self.names(None, "please calculate this"))
        self.assertIn("search_old_conversations", self.names(None, "what did I ask last time"))

    def test_module_tools_only_when_active(self):
        @tr.register("zz_study_tool", "x", {"a": {"type": "string"}}, ["a"], module="study")
        def f(a): return "ok " + a
        try:
            self.assertNotIn("zz_study_tool", self.names(None))
            self.assertNotIn("zz_study_tool", self.names("data"))
            self.assertIn("zz_study_tool", self.names("study"))
            self.assertNotIn("zz_study_tool", self.names("bogus"))
        finally:
            tr.REGISTRY.pop("zz_study_tool")

    def test_call_tool_never_raises(self):
        self.assertTrue(tr.call_tool("nope", {}).startswith("Error: unknown tool"))
        self.assertIn("missing required", tr.call_tool("calculate", {}))
        self.assertIn("not valid JSON", tr.call_tool("calculate", "{bad"))
        self.assertEqual(tr.call_tool("calculate", '{"expression": "2+3"}'), "Result: 5")
        self.assertEqual(tr.call_tool("calculate", {"expression": "2+3", "invented": 1}), "Result: 5")
        self.assertIn("needs request context", tr.call_tool("search_old_conversations", {"query": "x"}))

    def test_exception_and_truncation(self):
        @tr.register("zz_boom", "x", {}, [])
        def boom(): raise RuntimeError("kaboom")
        @tr.register("zz_big", "x", {}, [])
        def big(): return "a" * 10000
        try:
            self.assertIn("RuntimeError: kaboom", tr.call_tool("zz_boom", {}))
            out = tr.call_tool("zz_big", {})
            self.assertLess(len(out), 4200)
            self.assertIn("truncated", out)
        finally:
            tr.REGISTRY.pop("zz_boom"); tr.REGISTRY.pop("zz_big")

    def test_override_still_works(self):
        self.assertEqual(tr.call_tool("search_old_conversations", {"query": "q"}, overrides={"search_old_conversations": lambda query: "bound:" + query}), "bound:q")


class Calculator(unittest.TestCase):
    def test_good(self):
        for expr, want in [("2+3*4", "14"), ("(1+2)*3", "9"), ("10/4", "2.5"), ("2**10", "1024"), ("-5 + 2", "-3"), ("7 % 4", "3")]:
            self.assertEqual(agent.calculate(expr), f"Result: {want}", expr)

    def test_bad(self):
        for expr in ["9**9**9**9", "__import__('os').system('x')", "abs(-1)", "1/0", "2 +", "'a'*5", "True+1", "9**101"]:
            self.assertTrue(agent.calculate(expr).startswith(("Invalid", "Error")), expr)


class Files(unittest.TestCase):
    def test_roundtrip(self):
        m = file_store.save_bytes("u_abc", "notes.PDF", b"%PDF-1")
        self.assertEqual(m["ext"], ".pdf")
        path, meta = file_store.get_file("u_abc", m["id"])
        self.assertEqual(path.read_bytes(), b"%PDF-1")
        self.assertEqual([f["id"] for f in file_store.list_files("u_abc")], [m["id"]])
        file_store.delete_file("u_abc", m["id"])
        self.assertEqual(file_store.list_files("u_abc"), [])
        with self.assertRaises(FileNotFoundError):
            file_store.get_file("u_abc", m["id"])

    def test_isolation_between_users(self):
        m = file_store.save_bytes("alice", "a.txt", b"secret")
        with self.assertRaises(FileNotFoundError):
            file_store.get_file("bob", m["id"])

    def test_rejects(self):
        with self.assertRaises(file_store.FileStoreError): file_store.save_bytes("u", "x.exe", b"1")
        with self.assertRaises(file_store.FileStoreError): file_store.save_bytes("u", "x.svg", b"<svg/>")
        with self.assertRaises(file_store.FileStoreError): file_store.save_bytes("u", "x", b"1")
        with self.assertRaises(file_store.FileStoreError): file_store.save_bytes("..", "a.txt", b"1")
        with mock.patch.object(file_store, "MAX_UPLOAD_BYTES", 10):
            with self.assertRaises(file_store.FileStoreError): file_store.save_bytes("u", "a.txt", b"x" * 11)

    def test_path_tricks(self):
        m = file_store.save_bytes("../../etc", "../../evil.txt", b"x")
        path, _ = file_store.get_file("../../etc", m["id"])
        self.assertIn(str(file_store.DATA_DIR), str(path.resolve()))
        self.assertEqual(m["name"], "evil.txt")
        for bad in ["../x", "ZZZ", "", "a" * 16 + "/../b"]:
            with self.assertRaises(FileNotFoundError): file_store.get_file("u", bad)


class AgentLoop(unittest.TestCase):
    def run_with(self, replies, user_message="weather in delhi", ctx=None, module=None, weather_fail=False):
        sent = []
        it = iter(replies)
        def fake_post(u, json=None, timeout=None):
            sent.append(json)
            return FakeResp({"message": next(it)})
        def fake_get(u, params=None, timeout=None):
            if weather_fail:
                import requests; raise requests.ConnectionError("down")
            if "geocoding" in u:
                return FakeResp({"results": [{"latitude": 1, "longitude": 2}]})
            return FakeResp({"current": {"temperature_2m": 31.5, "relative_humidity_2m": 40}})
        msgs = [{"role": "system", "content": agent.SYSTEM_PROMPT}]
        with mock.patch("agent.requests.post", fake_post), mock.patch("agent.requests.get", fake_get):
            out = agent.run_agent(msgs, user_message, ctx=ctx, module=module)
        return out, msgs, sent

    def test_tool_then_answer(self):
        out, msgs, sent = self.run_with([tool_call("get_weather", {"city": "delhi"}), text("It is 31.5 C")])
        self.assertEqual(out, "It is 31.5 C")
        tool_msgs = [m for m in msgs if m["role"] == "tool"]
        self.assertEqual(len(tool_msgs), 1)
        self.assertEqual(tool_msgs[0]["tool_name"], "get_weather")
        self.assertIn("31.5", tool_msgs[0]["content"])
        self.assertEqual([t["function"]["name"] for t in sent[0]["tools"]], ["get_weather"])

    def test_unknown_tool_does_not_crash(self):
        out, msgs, _ = self.run_with([tool_call("hack_the_planet", {}), text("Sorry")])
        self.assertEqual(out, "Sorry")
        self.assertIn("unknown tool", [m for m in msgs if m["role"] == "tool"][0]["content"])

    def test_weather_outage_is_survivable(self):
        out, msgs, _ = self.run_with([tool_call("get_weather", {"city": "x"}), text("Service down")], weather_fail=True)
        self.assertEqual(out, "Service down")
        self.assertIn("Could not fetch", [m for m in msgs if m["role"] == "tool"][0]["content"])

    def test_ollama_errors_propagate_to_the_server_layer(self):
        import requests
        msgs = [{"role": "system", "content": "s"}]
        with mock.patch("agent.requests.post", side_effect=requests.ConnectionError("refused")):
            with self.assertRaises(requests.ConnectionError):
                agent.run_agent(msgs, "hi")
        with mock.patch("agent.requests.post", side_effect=requests.Timeout("slow")):
            with self.assertRaises(requests.Timeout):
                agent.run_agent(msgs, "hi")

    def test_facts_do_not_leak_between_conversations(self):
        ctx_a = {"user_id": "a", "conversation_id": "conv_a"}
        ctx_b = {"user_id": "b", "conversation_id": "conv_b"}
        self.run_with([tool_call("get_weather", {"city": "delhi"}), text("ok")], ctx=ctx_a)
        _, _, sent = self.run_with([text("hi")], user_message="hello", ctx=ctx_b)
        self.assertNotIn("Delhi", str(sent[0]["messages"]))
        _, _, sent = self.run_with([text("hi")], user_message="hello again", ctx=ctx_a)
        self.assertIn("Delhi", str(sent[0]["messages"]))

    def test_search_old_conversations_uses_ctx(self):
        import conversation_store as cs
        cs.save_conversation("sam", "old1", [{"role": "user", "content": "weather in Pune?"}])
        cs.save_conversation("sam", "cur", [{"role": "user", "content": "weather in Pune again"}])
        ctx = {"user_id": "sam", "conversation_id": "cur"}
        out, msgs, sent = self.run_with([tool_call("search_old_conversations", {"query": "pune"}), text("found")],
                                        user_message="what did I ask last time about pune", ctx=ctx)
        res = [m for m in msgs if m["role"] == "tool"][0]["content"]
        self.assertIn("[old1]", res)
        self.assertNotIn("[cur]", res)
        self.assertIn("search_old_conversations", [t["function"]["name"] for t in sent[0]["tools"]])

    def test_narration_nudge_and_turn_limit(self):
        out, msgs, _ = self.run_with([text("I will now check Delhi"), tool_call("get_weather", {"city": "delhi"}), text("done")])
        self.assertEqual(out, "done")
        out, _, _ = self.run_with([tool_call("get_weather", {"city": "a"})] * 8)
        self.assertIn("Turn limit", out)


if __name__ == "__main__":
    unittest.main()
