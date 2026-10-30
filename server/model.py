"""The local models, served by llama.cpp: the 2B writes, the 0.8B reads photos."""
import json
import os
import urllib.request

LLM = os.environ.get("EMBER_LLM", "http://127.0.0.1:8080")
VISION = os.environ.get("EMBER_VISION", LLM)  # a smaller model reads photos better and faster than the text model


def call(messages, server=None, **options):
    request = {"messages": messages, "temperature": 0, "chat_template_kwargs": {"enable_thinking": False}, **options}
    req = urllib.request.Request(f"{server or LLM}/v1/chat/completions", json.dumps(request).encode(), {"Content-Type": "application/json"})
    return urllib.request.urlopen(req, timeout=300)


def ask(messages, schema=None, server=None, limit=None):
    """The answer, read as JSON when it follows a schema. Raises ValueError if it runs past `limit` tokens."""
    options = {"max_tokens": limit} if limit else {}
    if schema:
        options["response_format"] = {"type": "json_schema", "json_schema": {"schema": schema}}
    with call(messages, server, **options) as r:
        choice = json.load(r)["choices"][0]
    if choice["finish_reason"] == "length":
        raise ValueError("answer cut off")
    answer = choice["message"]["content"]
    return json.loads(answer) if schema else answer.strip()


def stream(messages, **options):
    """The answer, piece by piece as it's written."""
    with call(messages, stream=True, **options) as r:
        for line in r:
            if line.startswith(b"data: {"):
                for choice in json.loads(line[6:]).get("choices", []):
                    yield choice["delta"].get("content") or ""
