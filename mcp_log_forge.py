#!/usr/bin/env python3
"""Log-Forge: a local, read-only Model Context Protocol (MCP) telemetry server.

Transport : MCP stdio (newline-delimited JSON-RPC 2.0 on stdin/stdout).
Tools     : read_live_telemetry, list_active_logs.
Dependencies: Python standard library only. No network modules are imported;
              verify_log_forge.py enforces this with an AST check.

Run:
    LOG_FORGE_ROOTS=/var/log/myapp:/srv/app/logs python mcp_log_forge.py

Environment:
    LOG_FORGE_ROOTS   os.pathsep-separated allow-list of directories the agent
                      may read. Default: the current working directory.
    LOG_FORGE_REDACT  "0" disables best-effort secret redaction (default: on).

Design notes:
  * stdout carries protocol messages only; diagnostics go to stderr.
  * Reads touch only the end of the file (bounded by MAX_READ_BYTES), so cost
    is proportional to the returned window, not to the file size. This is
    bounded and small, not literally zero.
  * Every file read happens in a worker thread so the event loop never blocks.
"""

import asyncio
import json
import os
import re
import stat
import sys
from datetime import datetime, timezone

SERVER_NAME = "log-forge"
SERVER_VERSION = "1.0.0"
SUPPORTED_PROTOCOLS = ("2025-06-18", "2025-03-26", "2024-11-05")

MAX_LINES = 100                 # hard cap on lines returned per call
MAX_READ_BYTES = 256 * 1024     # max bytes scanned backwards from end of file
MAX_OUTPUT_BYTES = 64 * 1024    # max bytes of log text returned per call
MAX_LINE_CHARS = 2000           # per-line truncation
BLOCK_SIZE = 8192
MAX_REQUEST_BYTES = 1024 * 1024
MAX_CONCURRENCY = 8

MAX_LIST_LIMIT = 200
MAX_LIST_DEPTH = 3
MAX_LIST_SCAN = 5000

LOG_NAME_RE = re.compile(r"\.(log|txt|out|err|jsonl)(\.\d+)?$", re.IGNORECASE)
CRASH_HINT_RE = re.compile(
    r"crash|fatal|panic|traceback|exception|segfault|oom|error|\.err$", re.IGNORECASE
)

_REDACTIONS = (
    (re.compile(r"\bBearer\s+[A-Za-z0-9._~+/=-]{8,}"), "Bearer [REDACTED]"),
    (re.compile(r"\bAKIA[0-9A-Z]{16}\b"), "[REDACTED]"),
    (re.compile(r"\b(?:sk|pk|ghp|xox[bp])[-_][A-Za-z0-9_-]{16,}"), "[REDACTED]"),
    (
        re.compile(
            r"(?i)(password|passwd|secret|token|api[_-]?key|authorization)"
            r"(\"?\s*[:=]\s*\"?)(?!Bearer\b)([^\s\"',;&]+)"
        ),
        r"\1\2[REDACTED]",
    ),
)


class RpcError(Exception):
    """JSON-RPC protocol-level error."""

    def __init__(self, code, message):
        super().__init__(message)
        self.code = code
        self.message = message


class ToolError(Exception):
    """Tool-execution error, reported to the agent with isError=true."""


# ---------------------------------------------------------------------------
# Path validation
# ---------------------------------------------------------------------------

def allowed_roots():
    raw = os.environ.get("LOG_FORGE_ROOTS", "")
    roots = [os.path.realpath(p) for p in raw.split(os.pathsep) if p.strip()]
    return roots or [os.path.realpath(os.getcwd())]


def _within(root, path):
    try:
        return os.path.commonpath([root, path]) == root
    except ValueError:  # different drives on Windows
        return False


def resolve_allowed(raw, roots):
    """Resolve symlinks/.. and return a real path inside an allowed root."""
    if not isinstance(raw, str) or not raw.strip() or "\x00" in raw:
        raise ToolError("path must be a non-empty string")
    candidate = raw if os.path.isabs(raw) else os.path.join(roots[0], raw)
    real = os.path.realpath(candidate)
    if not any(_within(root, real) for root in roots):
        raise ToolError("path is outside the allowed log roots: " + ", ".join(roots))
    return real


def _int_arg(args, name, default, low, high):
    value = args.get(name, default)
    if isinstance(value, bool) or not isinstance(value, int):
        raise ToolError("%s must be an integer" % name)
    if not low <= value <= high:
        raise ToolError("%s must be between %d and %d" % (name, low, high))
    return value


def redact(text):
    for pattern, repl in _REDACTIONS:
        text = pattern.sub(repl, text)
    return text


# ---------------------------------------------------------------------------
# Tool: read_live_telemetry
# ---------------------------------------------------------------------------

def _tail_file(real, n, since):
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
    try:
        fd = os.open(real, flags)
    except OSError as exc:
        raise ToolError("cannot open file: %s" % (exc.strerror or exc.__class__.__name__))
    try:
        st = os.fstat(fd)
        if not stat.S_ISREG(st.st_mode):
            raise ToolError("not a regular file")
        end = st.st_size
        floor = 0
        reset = False
        if since is not None:
            if since > end:
                reset = True        # truncated or rotated: fall back to the tail
            else:
                floor = since
        lines = []
        start = end
        if end > floor:
            lower = max(floor, end - MAX_READ_BYTES)
            chunks = []
            newlines = 0
            while start > lower and newlines <= n:
                step = min(BLOCK_SIZE, start - lower)
                start -= step
                os.lseek(fd, start, os.SEEK_SET)
                chunk = os.read(fd, step)
                if not chunk:
                    break
                chunks.append(chunk)
                newlines += chunk.count(b"\n")
            data = b"".join(reversed(chunks))
            parts = data.split(b"\n")
            if start > floor:
                parts = parts[1:]   # first element is a partial line
            if parts and parts[-1] == b"":
                parts.pop()
            lines = parts
    finally:
        os.close(fd)

    truncated = len(lines) > n or (end > floor and start > floor)
    lines = lines[-n:] if lines else []

    do_redact = os.environ.get("LOG_FORGE_REDACT", "1") != "0"
    out = []
    for raw_line in lines:
        text = raw_line.rstrip(b"\r").decode("utf-8", errors="replace")
        if do_redact:
            text = redact(text)
        if len(text) > MAX_LINE_CHARS:
            text = "%s...[+%d chars]" % (text[:MAX_LINE_CHARS], len(text) - MAX_LINE_CHARS)
        out.append(text)

    total = 0
    kept = []
    for text in reversed(out):
        total += len(text.encode("utf-8")) + 1
        if total > MAX_OUTPUT_BYTES:
            truncated = True
            break
        kept.append(text)
    kept.reverse()
    return {"size": end, "next_offset": end, "lines": kept,
            "truncated": truncated, "reset": reset}


def read_live_telemetry(args):
    roots = allowed_roots()
    real = resolve_allowed(args.get("path"), roots)
    if not LOG_NAME_RE.search(os.path.basename(real)):
        raise ToolError("only .log/.txt/.out/.err/.jsonl files (optionally rotated .N) are readable")
    n = _int_arg(args, "lines", MAX_LINES, 1, MAX_LINES)
    since = args.get("since_offset")
    if since is not None:
        since = _int_arg(args, "since_offset", 0, 0, 2 ** 63 - 1)
    result = _tail_file(real, n, since)

    header = "# file=%s size=%d next_offset=%d lines=%d" % (
        real, result["size"], result["next_offset"], len(result["lines"]))
    if result["truncated"]:
        header += " truncated=true"
    if result["reset"]:
        header += " rotated_reset=true"
    if since is not None and not result["lines"] and not result["reset"]:
        header += " (no new data since offset; do not re-poll immediately)"
    return "\n".join([header] + result["lines"])


# ---------------------------------------------------------------------------
# Tool: list_active_logs
# ---------------------------------------------------------------------------

def _scan(directory, recursive, depth, budget, found):
    try:
        entries = list(os.scandir(directory))
    except OSError:
        return
    for entry in entries:
        if budget[0] <= 0:
            return
        budget[0] -= 1
        try:
            if entry.is_symlink():
                continue
            if entry.is_dir(follow_symlinks=False):
                if recursive and depth < MAX_LIST_DEPTH:
                    _scan(entry.path, recursive, depth + 1, budget, found)
            elif entry.is_file(follow_symlinks=False) and LOG_NAME_RE.search(entry.name):
                found.append((entry.path, entry.stat(follow_symlinks=False)))
        except OSError:
            continue


def list_active_logs(args):
    roots = allowed_roots()
    directory = resolve_allowed(args.get("directory", roots[0]), roots)
    if not os.path.isdir(directory):
        raise ToolError("directory does not exist or is not a directory")
    recursive = args.get("recursive", False)
    if not isinstance(recursive, bool):
        raise ToolError("recursive must be a boolean")
    window = _int_arg(args, "active_within_seconds", 86400, 0, 10 * 365 * 86400)
    limit = _int_arg(args, "limit", 50, 1, MAX_LIST_LIMIT)

    found = []
    _scan(directory, recursive, 0, [MAX_LIST_SCAN], found)
    now = datetime.now(timezone.utc).timestamp()
    rows = []
    for path, st in found:
        age = max(0, int(now - st.st_mtime))
        if window and age > window:
            continue
        rows.append((st.st_mtime, path, st.st_size, age))
    rows.sort(reverse=True)

    lines = ["# directory=%s matched=%d shown=%d" % (directory, len(rows), min(len(rows), limit)),
             "path\tbytes\tmodified_utc\tage_s\tcrash_hint"]
    for mtime, path, size, age in rows[:limit]:
        stamp = datetime.fromtimestamp(mtime, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        hint = "yes" if CRASH_HINT_RE.search(os.path.basename(path)) else "no"
        lines.append("%s\t%d\t%s\t%d\t%s" % (path, size, stamp, age, hint))
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# MCP tool registry
# ---------------------------------------------------------------------------

_READ_ONLY = {"readOnlyHint": True, "destructiveHint": False,
              "idempotentHint": True, "openWorldHint": False}

TOOLS = {
    "read_live_telemetry": {
        "handler": read_live_telemetry,
        "definition": {
            "name": "read_live_telemetry",
            "title": "Read live telemetry",
            "description": (
                "Return the last N (max 100) lines of a log file inside the allowed roots. "
                "To avoid re-reading, pass since_offset=<next_offset from the previous call>: "
                "only bytes appended after that offset are returned, and an empty result means "
                "nothing new happened. Do not poll in a tight loop."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "path": {"type": "string",
                             "description": "Log file path (absolute, or relative to the first allowed root)."},
                    "lines": {"type": "integer", "minimum": 1, "maximum": MAX_LINES,
                              "default": MAX_LINES},
                    "since_offset": {"type": "integer", "minimum": 0,
                                     "description": "Byte offset from a previous call's next_offset."},
                },
                "required": ["path"],
                "additionalProperties": False,
            },
            "annotations": _READ_ONLY,
        },
    },
    "list_active_logs": {
        "handler": list_active_logs,
        "definition": {
            "name": "list_active_logs",
            "title": "List active logs",
            "description": (
                "List recently modified log files (newest first) with size, age and a "
                "filename-based crash hint, so you can choose which file to read."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "directory": {"type": "string",
                                  "description": "Directory inside the allowed roots (default: first root)."},
                    "recursive": {"type": "boolean", "default": False,
                                  "description": "Descend up to %d levels." % MAX_LIST_DEPTH},
                    "active_within_seconds": {"type": "integer", "minimum": 0, "default": 86400,
                                              "description": "Only files modified this recently; 0 = no filter."},
                    "limit": {"type": "integer", "minimum": 1, "maximum": MAX_LIST_LIMIT,
                              "default": 50},
                },
                "additionalProperties": False,
            },
            "annotations": _READ_ONLY,
        },
    },
}


# ---------------------------------------------------------------------------
# JSON-RPC dispatch
# ---------------------------------------------------------------------------

def _ok(msg_id, result):
    return {"jsonrpc": "2.0", "id": msg_id, "result": result}


def _err(msg_id, code, message):
    return {"jsonrpc": "2.0", "id": msg_id, "error": {"code": code, "message": message}}


async def _call_tool(params):
    if not isinstance(params, dict) or not isinstance(params.get("name"), str):
        raise RpcError(-32602, "tools/call requires a string 'name'")
    tool = TOOLS.get(params["name"])
    if tool is None:
        raise RpcError(-32602, "unknown tool: %s" % params["name"])
    arguments = params.get("arguments")
    if arguments is None:
        arguments = {}
    if not isinstance(arguments, dict):
        raise RpcError(-32602, "'arguments' must be an object")
    loop = asyncio.get_running_loop()
    try:
        text = await loop.run_in_executor(None, tool["handler"], arguments)
        is_error = False
    except ToolError as exc:
        text, is_error = str(exc), True
    except Exception as exc:  # never crash the server on a tool bug
        print("log-forge: tool %s failed: %r" % (params["name"], exc), file=sys.stderr)
        text, is_error = "internal error (%s)" % exc.__class__.__name__, True
    return {"content": [{"type": "text", "text": text}], "isError": is_error}


async def handle_message(msg):
    """Return a response dict, or None for notifications / client responses."""
    if not isinstance(msg, dict) or msg.get("jsonrpc") != "2.0":
        return _err(None, -32600, "Invalid Request")
    if "method" not in msg:
        return None  # a response from the client; nothing to answer
    method = msg["method"]
    is_notification = "id" not in msg
    msg_id = msg.get("id")
    if not isinstance(method, str) or isinstance(msg_id, (bool, dict, list)):
        return None if is_notification else _err(None, -32600, "Invalid Request")
    params = msg.get("params")
    try:
        if method == "initialize":
            requested = params.get("protocolVersion") if isinstance(params, dict) else None
            version = requested if requested in SUPPORTED_PROTOCOLS else SUPPORTED_PROTOCOLS[0]
            result = {
                "protocolVersion": version,
                "capabilities": {"tools": {"listChanged": False}},
                "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION},
                "instructions": "Read-only local log access. Use list_active_logs, then "
                                "read_live_telemetry with since_offset to poll cheaply.",
            }
        elif method == "ping":
            result = {}
        elif method == "tools/list":
            result = {"tools": [t["definition"] for t in TOOLS.values()]}
        elif method == "tools/call":
            result = await _call_tool(params)
        elif is_notification:
            return None  # notifications/initialized, notifications/cancelled, ...
        else:
            raise RpcError(-32601, "Method not found: %s" % method)
    except RpcError as exc:
        return None if is_notification else _err(msg_id, exc.code, exc.message)
    return None if is_notification else _ok(msg_id, result)


# ---------------------------------------------------------------------------
# Async stdin/stdout streaming loop
# ---------------------------------------------------------------------------

class _Writer:
    def __init__(self):
        self._lock = asyncio.Lock()
        self.closed = False

    async def send(self, obj):
        data = (json.dumps(obj, separators=(",", ":"), ensure_ascii=False) + "\n").encode("utf-8")
        async with self._lock:
            try:
                sys.stdout.buffer.write(data)
                sys.stdout.buffer.flush()
            except (BrokenPipeError, ValueError):
                self.closed = True


async def _open_stdin(loop):
    """Prefer a true async pipe reader; fall back to a thread for files/Windows."""
    try:
        reader = asyncio.StreamReader(limit=MAX_REQUEST_BYTES)
        await loop.connect_read_pipe(lambda: asyncio.StreamReaderProtocol(reader), sys.stdin)
        return reader.readline
    except (OSError, ValueError, NotImplementedError):
        return lambda: loop.run_in_executor(None, sys.stdin.buffer.readline)


async def serve():
    loop = asyncio.get_running_loop()
    readline = await _open_stdin(loop)
    writer = _Writer()
    gate = asyncio.Semaphore(MAX_CONCURRENCY)
    pending = set()

    async def process(msg):
        async with gate:
            response = await handle_message(msg)
        if response is not None:
            await writer.send(response)

    while not writer.closed:
        try:
            line = await readline()
        except (ValueError, asyncio.LimitOverrunError):
            await writer.send(_err(None, -32600, "Request too large"))
            break
        if not line:
            break  # EOF: client closed the pipe
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except ValueError:
            await writer.send(_err(None, -32700, "Parse error"))
            continue
        task = asyncio.ensure_future(process(msg))
        pending.add(task)
        task.add_done_callback(pending.discard)

    if pending:
        await asyncio.gather(*pending, return_exceptions=True)


def main():
    try:
        asyncio.run(serve())
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
