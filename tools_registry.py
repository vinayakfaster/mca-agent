"""
tools_registry.py - one place that knows every tool the agent can call.

Add a tool with the @register decorator (see agent.py for examples). Each tool belongs
to a module: "general" tools are offered on every request, a module's tools
("study", "data", "code", "pay") only when the frontend says that module is active.
That keeps the model's tool list short, which matters a lot for an 8B model.
"""
import json
import logging
import os
from dataclasses import dataclass
from typing import Any, Callable, Optional

import file_store

log = logging.getLogger("agent.tools")

MODULES = ("general", "study", "data", "code", "pay")
MAX_TOOLS_PER_REQUEST = int(os.getenv("MAX_TOOLS_PER_REQUEST", "8"))
MAX_RESULT_CHARS = int(os.getenv("MAX_TOOL_RESULT_CHARS", "4000"))


@dataclass
class Tool:
    name: str
    description: str
    properties: dict
    required: list
    func: Callable[..., Any]
    module: str = "general"
    needs_ctx: bool = False                       # True -> func receives ctx=... as a keyword
    when: Optional[Callable[[str], bool]] = None  # keyword gate on the user's message; None = always

    def schema(self) -> dict:
        return {"type": "function", "function": {
            "name": self.name,
            "description": self.description,
            "parameters": {"type": "object", "properties": self.properties,
                           "required": list(self.required)},
        }}


REGISTRY: dict = {}


def register(name: str, description: str, properties: dict, required=(),
             module: str = "general", needs_ctx: bool = False,
             when: Optional[Callable[[str], bool]] = None):
    """Decorator: register a function as an agent tool."""
    if module not in MODULES:
        raise ValueError(f"Unknown module '{module}'. Use one of {MODULES}.")

    def deco(fn):
        if name in REGISTRY:
            log.warning("Tool '%s' registered twice - replacing the old one", name)
        REGISTRY[name] = Tool(name, description, properties, list(required), fn, module, needs_ctx, when)
        return fn
    return deco


def get_tools(module: Optional[str] = None, user_message: str = "") -> list:
    """Tool schemas to show the model for this request."""
    active = module if module in MODULES else None
    allowed = {"general"} | ({active} if active else set())
    chosen = [t for t in REGISTRY.values()
              if t.module in allowed and (t.when is None or t.when(user_message))]
    if len(chosen) > MAX_TOOLS_PER_REQUEST:
        log.warning("%d tools offered (limit %d) - trimming; consider gating some with when=",
                    len(chosen), MAX_TOOLS_PER_REQUEST)
        chosen = chosen[:MAX_TOOLS_PER_REQUEST]
    return [t.schema() for t in chosen]


def make_ctx(user_id: str, conversation_id: Optional[str] = None, module: Optional[str] = None) -> dict:
    """Per-request context handed to tools that set needs_ctx=True."""
    return {"user_id": user_id, "conversation_id": conversation_id, "module": module,
            "user_dir": file_store.user_dir(user_id)}


def call_tool(name: str, args: Any, ctx: Optional[dict] = None, overrides: Optional[dict] = None) -> str:
    """
    Run a tool and ALWAYS return a string. Never raises: problems come back as
    'Error: ...' text so the model can read them and recover.
    `overrides` is a {name: callable} dict kept for older code that binds tools at runtime.
    """
    tool = REGISTRY.get(name)
    override = (overrides or {}).get(name)
    if tool is None and override is None:
        return f"Error: unknown tool '{name}'. Available tools: {', '.join(sorted(REGISTRY)) or 'none'}."

    if isinstance(args, str):                       # some models send arguments as a JSON string
        try:
            args = json.loads(args)
        except ValueError:
            return "Error: tool arguments were not valid JSON."
    if args is None:
        args = {}
    if not isinstance(args, dict):
        return "Error: tool arguments must be an object."

    if tool is not None:
        missing = [r for r in tool.required if args.get(r) in (None, "")]
        if missing:
            return f"Error: missing required argument(s): {', '.join(missing)}."
        args = {k: v for k, v in args.items() if k in tool.properties}   # drop invented arguments

    try:
        if override is not None:
            result = override(**args)
        elif tool.needs_ctx:
            if ctx is None:
                return f"Error: tool '{name}' needs request context and none was provided."
            result = tool.func(ctx=ctx, **args)
        else:
            result = tool.func(**args)
    except Exception as e:                           # noqa: BLE001 - tools must never crash the agent
        log.exception("Tool %s failed", name)
        return f"Error running {name}: {type(e).__name__}: {str(e)[:300]}"

    text = result if isinstance(result, str) else json.dumps(result, default=str, ensure_ascii=False)
    if len(text) > MAX_RESULT_CHARS:
        text = text[:MAX_RESULT_CHARS] + f"\n... [truncated, {len(text) - MAX_RESULT_CHARS} more characters]"
    return text
