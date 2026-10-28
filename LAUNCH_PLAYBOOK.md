# Log-Forge Open-Core Launch Playbook

I could not verify the current submission rules of the directories below from this workspace. Before each step, read the target's own contribution or submission page and follow it. The format details below are placeholders.

## 0. Pre-flight (blocking)

- [ ] **Add a license.** `dist/open_core/` has no LICENSE file. Without one, the public code is "all rights reserved" by default. Your `EULA.txt` is a draft and the release gate says it is not counsel-reviewed. Choose the public license (for example MIT or Apache-2.0) with your attorney. Decide whether the paid tiers differ from this file (see `LOG_FORGE_DISTRIBUTION.md`). If the free file is identical, the paid tiers need other value such as adapters, rule packs, updates and support.
- [ ] Add a short `README.md` to the public repo. `README_LOG_FORGE.md` is a good base. Keep its data-flow notice and its known limitations.
- [ ] Verify the zero-network claim: `mcp_log_forge.py` imports only `asyncio, datetime, json, os, re, stat, sys`. Re-run `python3 verify_log_forge.py` before publishing.
- [ ] Test with at least two real MCP clients before claiming compatibility.
- [ ] Create the public GitHub repo, tag `v1.0.0`, and attach `SHA256SUMS`.

## 1. Sequence

| Step | Target | Action | Done when |
|---|---|---|---|
| 1 | GitHub public repo | Push `mcp_log_forge.py`, README, LICENSE, topics `mcp`, `mcp-server`, `logging`, `claude`, `cursor` | Repo is public and the tag exists |
| 2 | Awesome-MCP lists (the community GitHub lists) | Open a pull request adding one line in the list's required format | PR merged, or feedback addressed |
| 3 | mcpservers.org | Submit through the site's own submission flow | Listing is live |
| 4 | LobeHub MCP marketplace | Follow LobeHub's current publishing process for MCP servers | Listing is live |
| 5 | Announce | One post in each relevant developer community, read its self-promotion rules first | No rule violations |

Do steps 2 to 4 in that order, one at a time, so you can fix feedback once and reuse it. Record each submission date and URL in a tracking table.

## 2. Listing copy (reuse everywhere)

> Log-Forge: a local, read-only MCP server that lets your coding agent list and tail log files without you pasting logs into chat. Python standard library only, no network code, 100-line and 64 KiB cap per call, offset-based polling so repeated reads stay small.

Do not claim that it "fixes loops" or "saves $X". It reduces the size of log reads, and savings depend on the workload.

## 3. SEO keyword mapping

| Keyword | Intent | Landing page | What the page must honestly say |
|---|---|---|---|
| Claude agent infinite loop fix | Troubleshooting | "Stop re-pasting logs: cheaper log reads for agents" | Log-Forge shrinks log-read cost via `since_offset`. It does not detect loops. Add budget limits in your client. |
| Cursor runaway token costs | Cost control | "Cut token cost of log-heavy debugging in Cursor" | Config snippet for Cursor, a before/after measurement method, and the cost model from `GROWTH_CASE_STUDIES.md` |
| PII redaction for MCP | Compliance | "Best-effort secret redaction for MCP log access" | Redaction covers passwords, tokens, bearer tokens and AWS key IDs. It is best-effort and misses PII such as names and emails. State that plainly. Do not use "PII redaction" as a feature claim. |

Notes:
- The PII keyword is the riskiest. The tool masks secrets, not personal data. Either extend the redaction rules and test them first, or phrase the page as "secret redaction".
- One page per keyword, with the keyword in the title, H1 and first paragraph. Link the three pages to each other and to the repo.
- Measure with Google Search Console after indexing. Expect weeks, not days.

## 4. Metrics to track

GitHub stars and clones, listing referral traffic, search impressions and clicks per keyword, trial sign-ups, and the reason each trial user did or did not convert. The open-core build has no telemetry, so get these numbers only from the platforms above and from users who volunteer them.
