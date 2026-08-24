# MCP Server Setup

Four MCP servers, set up two different ways depending on how each authenticates.

| Server | How it's set up | Auth | Where |
|--------|-----------------|------|-------|
| **Playwright** | `.mcp.json` (stdio) | none | Runs inside the session VM |
| **Perplexity** | `.mcp.json` (HTTP) | API key (Bearer) | Needs egress + `PERPLEXITY_API_KEY` |
| **Composio** | claude.ai **Connector** | OAuth | Bypasses VM egress |
| **Firecrawl** | claude.ai **Connector** | OAuth / account sign-in | Bypasses VM egress |

## Why two approaches

`.mcp.json` HTTP servers dial out **from the session VM**, so their hosts must be
on the environment's egress allowlist. claude.ai **Connectors** route through
Anthropic's MCP proxy instead, which **bypasses that allowlist** — so OAuth-based
remote servers are simplest to add as Connectors.

- **Composio & Firecrawl** use OAuth / account sign-in → added as Connectors.
- **Perplexity** authenticates with an **API key, not OAuth**, so the Connector
  flow can't register it ("Couldn't register with Perplexity's sign-in
  service"). It stays in `.mcp.json` with a Bearer header.
- **Playwright** is a local stdio process — no remote host, no auth.

---

## Composio & Firecrawl — add as Connectors

1. **claude.ai → Settings → Connectors → Add custom connector.**
2. Composio URL: `https://connect.composio.dev/mcp`
   Firecrawl URL: `https://mcp.firecrawl.dev/v2/mcp`
3. Open each connector and **Connect / Sign in** to finish authentication.
   - Composio is a hub: after connecting, authorize individual apps as you use them.
   - Firecrawl: sign into your Firecrawl account (or supply your `fc-` key if prompted).

Connectors sync into cloud coding sessions automatically once authenticated.

---

## Perplexity — `.mcp.json` + egress + env var

Configured in [`.mcp.json`](./.mcp.json) with `Authorization: Bearer
${PERPLEXITY_API_KEY}`. To make it connect:

**Cloud sessions** — at [claude.ai/code](https://claude.ai/code) → environment →
**Configure**:
- **Network access = `Custom`**, add `api.perplexity.ai` (tick "Also include
  default list of common package managers").
- Add env var `PERPLEXITY_API_KEY = pplx-...`
  > ⚠️ No secrets store yet — env vars are readable by anyone who can use the
  > environment.
- Start a fresh session.

**Local** — full network access, add at local scope:
```bash
claude mcp add --transport http perplexity https://api.perplexity.ai/mcp \
  --header "Authorization: Bearer YOUR_PPLX_KEY"
```

Get a paid key at [perplexity.ai](https://perplexity.ai) → Settings → API.

---

## Playwright — already configured

In [`.mcp.json`](./.mcp.json) as a stdio server. In cloud sessions it uses the
VM's bundled Chromium (`/opt/pw-browsers/chromium`); only npm egress is needed,
which the Trusted default already allows.

**Running this repo locally?** That committed path won't exist on your machine —
override Playwright at local scope, which wins over the repo entry:
```bash
claude mcp add playwright -- npx @playwright/mcp@latest
```

---

## Verify

```bash
claude mcp list          # .mcp.json servers: playwright, perplexity
```
Connectors show under **claude.ai → Settings → Connectors**.

## Test prompts

- **Playwright:** "Open example.com, snapshot it, and tell me the page heading."
- **Composio:** "List the Composio apps/toolkits I'm authorized to use."
- **Firecrawl:** "Use Firecrawl to scrape https://firecrawl.dev and summarize it in 2 sentences."
- **Perplexity:** "Use Perplexity to find this month's top AI model releases, with sources."
