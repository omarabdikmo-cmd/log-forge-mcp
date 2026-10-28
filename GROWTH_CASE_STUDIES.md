# Log-Forge: Case Studies

> **Read first.** Log-Forge has no customer measurements yet. Part 1 holds two **illustrative scenarios**. They are composites built from how the tool works, not reports from real customers, and every number in them is a placeholder for you to replace. Do not publish them as testimonials. Part 2 is the template to use once a real user gives you measured data and written permission.

## What Log-Forge does (and does not do)

- It is a local, read-only MCP server. The agent calls `list_active_logs` and `read_live_telemetry` instead of you pasting logs into chat.
- `read_live_telemetry` accepts `since_offset`. Polling returns only new bytes, and an empty reply means nothing new.
- It returns at most 100 lines and 64 KiB per call.
- It does **not** detect or stop agent loops. It can only make each log read smaller, which cuts the token cost of a loop that is reading logs.
- Redaction is best-effort and will miss some secrets.
- Your AI client still sends tool output to its model provider.

## Cost model (fill in your own numbers)

```
monthly_cost = calls_per_day x days x avg_input_tokens_per_call x (price_per_input_token)
saving       = monthly_cost_before - monthly_cost_after
```

Take `price_per_input_token` from your provider's current price page. Take the token counts from your provider's usage dashboard, before and after.

---

## Part 1: Illustrative scenarios (not real customers)

### Scenario A: The agent that re-pastes the same log

**Setup.** A small agency runs a coding agent against a staging API. When a build fails, the agent asks for the log. Someone pastes 2,000 lines. After each fix attempt, the agent asks again and the full log goes back into the context.

**Failure mode.** Every retry resends the whole log, and the context grows with each pass.

**Change.** Install Log-Forge and set `LOG_FORGE_ROOTS` to the staging log folder. The agent calls `list_active_logs`, then `read_live_telemetry` with the last 50 lines. On later passes it sends `since_offset` and receives only new lines.

**What you would measure:** input tokens per failed-build session, before and after, and the number of retries per session.

**Result:** `[MEASURED_BEFORE]` -> `[MEASURED_AFTER]` input tokens per session. Leave this blank until you have real data.

### Scenario B: The tight polling loop

**Setup.** An agent waits on a long job and re-reads the log every few seconds, whether or not anything changed.

**Failure mode.** Each poll costs tokens. The loop runs until someone notices.

**Change.** With `since_offset`, an unchanged log returns an empty reply. The tool description tells the agent not to re-poll in a tight loop. This is a hint to the model, not enforcement. A loop caused by the agent's own logic will still run, so also set a step or budget limit in your client or at your API provider.

**What you would measure:** tokens per poll before and after, and total polls per job.

**Result:** `[MEASURED_BEFORE]` -> `[MEASURED_AFTER]`.

---

## Part 2: Template for a real case study

Publish only when all of these are true:

- [ ] The customer agreed in writing to be named, or to be described anonymously.
- [ ] Token numbers come from their provider dashboard or invoices (attach screenshots to your records).
- [ ] The before and after periods are stated, with the workload described.
- [ ] Other changes made in the same period are disclosed.
- [ ] Any dollar figure shows the arithmetic.

```
## [Customer / "A 12-person agency"]
Client and agent: [e.g. Claude Desktop / Cursor / Cline]
Problem: [what the agent was doing, in the customer's words]
Change: [what was installed and configured]
Measured period: [dates] vs [dates]
Input tokens/day: [before] -> [after]
Spend: [before] -> [after]   (source: [dashboard/invoice])
Other changes in that period: [none / list]
Quote (verbatim, approved): "[...]"
Permission on file: [date]
```
