# Log-Forge (log-forge-mcp)

A local, read-only MCP (Model Context Protocol) server that lets your AI coding agent list and tail log files, without you pasting logs into chat.

- Single Python file (`mcp_log_forge.py`), standard library only. Requires Python 3.9+.
- Log-Forge itself opens no network connections and writes nothing to disk.
- Returns at most 100 lines (64 KiB) per call, and only from folders you allow.

> **Data-flow notice.** Log-Forge runs on your machine. But your AI client (Claude Desktop, Cursor, Cline, etc.) normally sends tool output to its model provider. Log lines you let the agent read may leave your machine through that client. Expose only folders you are comfortable sharing with that provider, or use a local model.

## Install

1. Put `mcp_log_forge.py` anywhere, for example `/opt/log-forge/`.
2. Add it to your MCP client config. Example for Claude Desktop (`claude_desktop_config.json`) and similar clients:

```json
{
  "mcpServers": {
    "log-forge": {
      "command": "python3",
      "args": ["/opt/log-forge/mcp_log_forge.py"],
      "env": { "LOG_FORGE_ROOTS": "/var/log/myapp:/srv/app/logs" }
    }
  }
}
```

`LOG_FORGE_ROOTS` is an allow-list of folders (separated by `:` on Linux/macOS, `;` on Windows). If unset, the client's working directory is used, so set it deliberately.

3. Restart the client. The agent now has two tools.

## Tools

| Tool | What it does |
|---|---|
| `list_active_logs` | Lists recently modified log files (newest first) with size, age and a filename-based crash hint. Options: `directory`, `recursive`, `active_within_seconds`, `limit`. |
| `read_live_telemetry` | Returns the last N lines (max 100) of one file. Pass `since_offset` (the `next_offset` from the previous call) to receive only new bytes. An empty reply means nothing new, so the agent should not re-poll in a tight loop. |

## Why `since_offset` matters

Re-reading the same log tail after every fix attempt sends the same bytes into the model context again. With `since_offset`, repeat reads return only new bytes, so each poll is smaller. This only makes each log read smaller. It does not detect or stop agent loops, so also set a step or budget limit in your client.

### Telemetry snapshot (dated, from the author's dev box)

Measured with a local meter driving the real `read_live_telemetry` tool against a small local log. This is not a customer workload.

| Metric | Value |
|---|---|
| Calls handled | 5,339 (1 full tail and 5,338 `since_offset` polls, 5,336 of them empty) |
| Bytes served | 1,158,513 |
| Estimated bytes avoided vs. re-reading the full tail each time | 192,254 (about 188 KiB) |
| Reduction | 14.2% |

The avoided figure is an estimate in bytes, not tokens or dollars. Your results will depend on how often your log changes and how often your agent polls.

## Safety limits
- Reads only `.log .txt .out .err .jsonl` files (and rotated `.1`, `.2`, ...), inside the allowed folders.
- Symlinks, `..` traversal, directories and other file types are rejected.
- Obvious secrets (`password=`, `token=`, bearer tokens, AWS key IDs) are masked. **This is best-effort and will miss some secrets.**
- Output caps: 100 lines, 64 KiB per call, 2000 characters per line.

## Known limitations
- Tested on Linux only. Windows and macOS are expected to work but are untested.
- Not tested against every MCP client.
- No gzip, journald or Docker log sources.

## License

MIT. See `LICENSE`.
