# MCP Server Setup

This repo configures four MCP servers in [`.mcp.json`](./.mcp.json):

| Server | Transport | Auth | Notes |
|--------|-----------|------|-------|
| **playwright** | stdio (`npx @playwright/mcp`) | none | Browser automation. Pinned to the cloud VM's bundled Chromium. |
| **composio** | HTTP | OAuth | Sign in interactively (`/mcp`). |
| **firecrawl** | HTTP | API key in URL | Key via `${FIRECRAWL_API_KEY}`. |
| **perplexity** | HTTP | Bearer token | Key via `${PERPLEXITY_API_KEY}`. |

**Secrets are never committed.** The two API-key servers read their keys from
environment variables, so `.mcp.json` stays free of credentials.

---

## Running in Claude Code on the web (cloud sessions)

`.mcp.json` HTTP servers connect *from the session VM*, so their hosts must be
allowed by the environment's **egress allowlist**. By default the environment is
**Trusted**, which only allows package registries + GitHub — so Composio,
Firecrawl, and Perplexity are blocked (Playwright works, since it only needs
npm). To fix:

1. Go to **[claude.ai/code](https://claude.ai/code)** → environment dropdown →
   **Configure**.
2. **Network access → `Custom`**, then add to **Allowed domains** (one per line):
   ```
   connect.composio.dev
   mcp.firecrawl.dev
   api.perplexity.ai
   ```
   Check **"Also include default list of common package managers"** (Playwright
   needs npm). Or set Network access → `Full`.
3. Add environment variables:
   ```
   FIRECRAWL_API_KEY = fc-...
   PERPLEXITY_API_KEY = pplx-...
   ```
   > ⚠️ No dedicated secrets store exists yet — env vars are readable by anyone
   > who can use the environment.
4. Authorize **Composio** once via OAuth: run `claude` → `/mcp` → select
   `composio` → complete browser sign-in. (Required even after egress is open.)
5. Start a **fresh** cloud session so it re-clones `.mcp.json` and picks up the
   new network + env settings.

### Connector alternative

For any server that offers a **claude.ai connector** (Composio does), adding it
under **claude.ai → Settings → Connectors** routes its traffic through
Anthropic's MCP proxy, which **bypasses the environment egress allowlist**. Such
connectors work in web sessions without step 2. Firecrawl and Perplexity here
are configured as raw MCP URLs, so they use the `.mcp.json` + allowlist path.

---

## Running locally (Claude Code CLI / Desktop)

Local sessions have unrestricted network access. Add the servers at local scope
(writes to `~/.claude.json`; local scope overrides the repo's `.mcp.json` for
same-named servers):

```bash
# Playwright — plain command; Playwright finds/downloads its own browser locally
claude mcp add playwright -- npx @playwright/mcp@latest

# Firecrawl — key goes in the URL path
claude mcp add --transport http firecrawl "https://mcp.firecrawl.dev/YOUR_FC_KEY/v2/mcp"

# Perplexity — key as a Bearer header
claude mcp add --transport http perplexity https://api.perplexity.ai/mcp \
  --header "Authorization: Bearer YOUR_PPLX_KEY"

# Composio — add, then authorize
claude mcp add --transport http composio https://connect.composio.dev/mcp
# then run:  claude  →  /mcp  →  select composio  →  sign in
```

Verify connections:

```bash
claude mcp list
```

> The committed `.mcp.json` pins Playwright to the cloud path
> `/opt/pw-browsers/chromium`. Opening this repo locally would apply that path,
> so the local `claude mcp add playwright` above overrides it (local scope wins).

---

## Getting the API keys

- **Firecrawl** (free tier): [firecrawl.dev](https://firecrawl.dev) → dashboard →
  API Keys (`fc-...`).
- **Perplexity** (paid): [perplexity.ai](https://perplexity.ai) → Settings → API
  (`pplx-...`).

## Test prompts

- **Playwright:** "Open example.com, snapshot it, and tell me the page heading."
- **Composio:** "List the Composio apps/toolkits I'm authorized to use."
- **Firecrawl:** "Use Firecrawl to scrape https://firecrawl.dev and summarize it in 2 sentences."
- **Perplexity:** "Use Perplexity to find this month's top AI model releases, with sources."
