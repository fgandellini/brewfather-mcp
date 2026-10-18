# Deploy the MCP server to Cloudflare Workers

Date: 2026-10-18
Status: approved by the owner on 2026-10-18

## Intent

The MCP server runs on the owner's home server. Tailscale Funnel exposes it, and the claude.ai "Brewfather MCP" connector uses it. That path fails sometimes, for example with a Cloudflare 502 when the home machine or network is down. The owner wants a host that stays up without the home server.

The server will run as a Cloudflare Python Worker. Every push to `main` deploys the latest `main` automatically.

## Goals

- The server runs on Cloudflare as a Python Worker named `brewfather-mcp`. The MCP endpoint is `https://brewfather-mcp.fgandellini.workers.dev/mcp`.
- The claude.ai connector works against that URL with the existing bearer-token authentication.
- Every push to `main` runs the tests. If they pass, it deploys to Cloudflare. If the tests fail, there is no deploy.
- One code base. The same `brewfather_mcp` package serves stdio, the home HTTP server (`src/http_runner.py`) and the Worker. No code is copied.

## Non-goals

- OAuth. The connector sends `Authorization: Bearer <MCP_AUTH_TOKEN>`, and that is enough.
- A TypeScript or Bun port. It was considered and rejected: it means a full rewrite, and the Python code already runs on Workers.
- Upgrading to the MCP Python SDK 2.x. The project stays on `mcp<2`.
- Changes to the tools themselves.
- A custom domain.

## Anti-goals (a failure even if it works)

- A Worker that answers MCP requests without a valid token. The write tools can change the owner's real Brewfather data.
- Brewfather credentials or `MCP_AUTH_TOKEN` stored in GitHub, in the repo or in CI logs.
- A paid Cloudflare plan. The owner is on the free plan and wants to stay on it.
- Breaking stdio use (`brewfather-mcp`, `uvx`) or the home HTTP server.

## What the spike proved

A throwaway spike, not committed, ran the unchanged `brewfather_mcp` package as the Worker `brewfather-mcp-spike` on the owner's free-plan account. The claude.ai connector connected to it and finished the MCP handshake (`initialize`, `tools/list`, `prompts/list`, `resources/list`). `list_hops` and `inventory_summary` returned real data. The facts below come from the spike. The builder should treat them as constraints.

1. **FastMCP 1.x works under Pyodide.** Async `httpx`, pydantic and starlette work too.
2. **Imports must be at module level in the Worker entry file.** Cloudflare snapshots the Worker's memory at deploy time, but only for imports made at the top of the entry module. In the spike, importing the server inside the handler cost about 2 s of CPU on every cold start, and Cloudflare killed those requests (`1101`, and `1102` "exceeded CPU").
3. **The API client must not need credentials at import time.** Secrets do not exist at deploy time, when the snapshot is made. Today `server.py` builds `BrewfatherClient()` on import, and the constructor raises if the environment variables are missing. The spike worked around this with placeholder values. The real code should read the credentials lazily, on first use.
4. **Worker secrets are on `env`, not in `os.environ`.** The entry point must pass them to the client.
5. **The Workers ASGI adapter runs ASGI lifespan on every request.** FastMCP 1.x's `StreamableHTTPSessionManager.run()` works only once per instance, so the second request failed. The spike's fix: set `mcp._session_manager = None` before each request, then call `mcp.streamable_http_app()` again. This needs `stateless_http = True`. It uses a private attribute, so it needs a comment and a test.
6. **Shutting down that per-request session manager logs an error every time:** `mcp.server.streamable_http - ERROR - Error in message router` followed by an `anyio.ClosedResourceError` traceback. It is harmless, because every request still returns `200`. Cloudflare labels all of it as `error`, so the dashboard is full of noise.
7. **Writing logs to a file fails on Workers.** `server.py` calls `logging.basicConfig(filename="/tmp/application.log")`. On the Worker every flush raised `OSError: [Errno 8] Bad file descriptor`, which printed a "logging error" traceback each time and cost CPU.
8. **Node 26 does not work with `pywrangler`.** Creating the Pyodide venv fails with `node: bad option: --experimental-wasm-stack-switching`. Node 22 works.
9. **Bearer auth works with the claude.ai connector.** Before the token was set in the connector, it tried OAuth discovery (`/.well-known/oauth-protected-resource`, `/.well-known/oauth-authorization-server`, `POST /register`). The Worker answered `401` to all of those, which is correct.
10. **Local dev (`pywrangler dev`) keeps stale state.** After you change `.dev.vars`, restart the dev server. A hot reload does not pick up the change.

Spike measurements on the free plan, warm requests: CPU per request had a median of 44–59 ms, a 90th percentile of 333–425 ms and a maximum of 544–1129 ms. Wall time was 0.6 s for `tools/list` and 0.9–2 s for a Brewfather call. Bundle: about 10 MiB uncompressed, 2.6 MiB gzip. Reported Worker startup time was 643 ms with lazy imports and 3.1–5.5 s with module-level imports.

## Constraints

- **Cloudflare free plan limits** (from https://developers.cloudflare.com/workers/platform/limits/, read 2026-10-18): 10 ms CPU per HTTP request, 1 s startup time, 64 MiB uncompressed Worker size, 128 MB memory, 50 subrequests per invocation and 100,000 requests per day.
  - **Known gap:** the spike went far above the documented CPU and startup limits, and nothing was blocked. We don't know why. It may stop working later. The design accepts that risk, and the fallback is below. Don't spend effort on it now, but don't make CPU use worse either. For example, don't add work to every request.
  - 50 subrequests: a list reads at most 10 pages (`LIST_MAX_PAGES`). `inventory_summary` reads several categories, so its worst case is near the limit. Keep that in mind, but it is not in scope to change.
- **Runtime dependencies must be installable under Pyodide.** `pywrangler` bundles `[project].dependencies` from `pyproject.toml`. The project lists `uv` and `pytest-cov` as runtime dependencies today. `uv` is a native binary, and `pytest-cov` is a test tool. Both must move to the dev group. The spike bundled only `mcp`, `httpx`, `pydantic` and `python-dotenv`. The real bundle will also have `mcp[cli]`, `starlette` and `uvicorn`. These are expected to be pure Python, but the builder must confirm that the deploy bundles them. If one fails, move it to an optional extra that only the home HTTP server uses.
- **Python 3.13.** The spike used `compatibility_date: 2026-09-07` with the `python_workers` flag and without `python_workers_314`, so the Worker runs Python 3.13. This matches `requires-python = ">=3.13"`.
- **Node 22** in CI and for local Worker work.
- **Tests must not call the real API.** Follow the existing patterns: respx, mocks, VCR cassettes.
- **Tests patch `brewfather_mcp.server.brewfather_client`.** Keep that name as a module-level object that tools look up at call time.
- **Never add delete tools, and never give the API key `*.delete` scopes** (from CLAUDE.md).

## The design

### Worker entry point

- A new entry file, for example `src/worker.py`. `wrangler.jsonc` sits at the repo root, with `"main"` pointing at the entry file, `"name": "brewfather-mcp"` and observability turned on.
- The entry file imports `brewfather_mcp.server` at module level (spike fact 2).
- At startup, the Worker passes `BREWFATHER_API_USER_ID` and `BREWFATHER_API_KEY` from `env` to the client (spike facts 3 and 4).
- The FastMCP settings for the Worker are `stateless_http = True`, `json_response = True` and `streamable_http_path = "/mcp"`. Set them only in the Worker. The home HTTP server keeps its current settings.
- Each request to `/mcp` gets a fresh session manager (spike fact 5). Any other path returns `404`.
- Leave `BREWFATHER_MCP_DEBUG` unset on the Worker. Debug mode writes files.

### Authentication

- Every request needs `Authorization: Bearer <MCP_AUTH_TOKEN>`, compared with `hmac.compare_digest`. Anything else returns `401`, and that check runs before any MCP code.
- **The Worker fails closed:** if the `MCP_AUTH_TOKEN` secret is missing or empty, every request returns `401`. This differs from `http_runner.py`, which runs without auth when no token is set. Leave `http_runner.py` as it is.
- Put the check in one place that both runners can use, if that is easy. `http_runner.py` already has `BearerAuthMiddleware`. If sharing makes the code worse, a small separate check in the Worker is acceptable. This is the builder's call.

### Logging

- Remove `logging.basicConfig(...)` from `server.py`, because a library module should not configure logging (spike fact 7). Each entry point sets up its own logging:
  - stdio entry points (`src/main.py`, `src/brewfather_mcp/main.py`): keep logging to `/tmp/application.log`, as today. stdout carries the MCP protocol, so these entry points must not log there.
  - `http_runner.py`: today its own `basicConfig` call does nothing, because `server.py` already ran one on import. After the change it takes effect and logs to stderr, which is what that code was written to do.
  - Worker: log to stderr, which is the default, at `INFO`.
- Filter out the harmless shutdown log (spike fact 6) on the Worker only: drop records from the `mcp.server.streamable_http` logger whose exception is `anyio.ClosedResourceError`. Every other error must still show.

### Secrets and configuration

| Secret | Where | Set by | When |
| --- | --- | --- | --- |
| `BREWFATHER_API_USER_ID`, `BREWFATHER_API_KEY`, `MCP_AUTH_TOKEN` | Cloudflare Worker secrets on `brewfather-mcp` | the owner, with `wrangler secret put` | once; they stay across deploys |
| `CLOUDFLARE_API_TOKEN` (template "Edit Cloudflare Workers"), `CLOUDFLARE_ACCOUNT_ID` | GitHub Actions repository secrets | the owner | once |

The account ID is `8c8660fa9720bdee18a1efa54f918d1e`. `.dev.vars` holds local Worker secrets for `pywrangler dev`. It must be in `.gitignore`.

### Continuous deploy

- Add a `deploy` job to the existing `.github/workflows/python-app.yml`. It needs the existing `build` (test) job, and it runs only on `push` to `main`, never on pull requests.
- Steps: checkout, Node 22, uv, then `uv run pywrangler deploy` with `CLOUDFLARE_API_TOKEN` and `CLOUDFLARE_ACCOUNT_ID` from GitHub secrets.
- After the deploy, run a smoke check: `POST /mcp` without a token must return `401`. If the check fails, the job fails. The check proves that the Worker is up and fails closed. It does not prove that the new version is live, because the old version also returns `401`. Proof that a deploy went live comes from `wrangler deploy`'s own exit code and printed version ID. Don't expose version information without auth, and don't put `MCP_AUTH_TOKEN` in GitHub to make a deeper check possible. *(Designer's call.)*
- On pull requests, also build the Worker bundle without deploying it (`uv run pywrangler deploy --dry-run`). A dependency that Pyodide can't install then fails the PR, not the deploy after the merge. The cost is a slower PR job and Node 22 in that job. *(Designer's call.)*
- Use a concurrency group, so two quick pushes don't deploy at the same time.

### Tests

- Unit-test the logic that does not need the Workers runtime: the bearer check (no token configured, missing header, wrong token, right token), the log filter, and the client reading credentials lazily (importing `server` with no credentials set must not raise).
- The `workers` module exists only inside the Workers runtime. Keep the Worker entry file thin, so the tested logic lives in normal modules.
- The existing test suite must still pass.

### Documentation

Update CLAUDE.md and README with:
- how to run the Worker locally (`uv run pywrangler dev`, Node 22, `.dev.vars`, restart after secret changes)
- the one-time secret setup
- how deploys happen
- the free-plan risk

Remove the Railway, Fly.io and Render deployment notes from CLAUDE.md (and from the README if they are there). The owner approved this cleanup. Keep the notes about running the HTTP server locally and with Docker, because the home server stays as the fallback.

## Fallback

The home server and `http_runner.py` stay as they are. The owner keeps them running until the Worker has proven reliable, and will remove them later (outside this work). If Cloudflare starts enforcing the free-plan CPU limit (`1102` errors), the options are the Workers Paid plan (about $5 a month) or a Cloudflare Container. Neither needs a change to this design's code layout.

## After the build (owner's steps)

1. Set the Worker secrets and the GitHub secrets.
2. Merge to `main` and confirm the deploy job passes.
3. Point the claude.ai connector at `https://brewfather-mcp.fgandellini.workers.dev/mcp` with the same token.
4. Delete the spike Worker `brewfather-mcp-spike` (`wrangler delete`) and the local `spike-cf/` folder. `spike-cf/` holds copies of the real credentials and the Cloudflare API token.

## Left to the builder

- File names and module layout for the Worker entry and the shared auth check.
- How the client reads its credentials lazily, as long as `brewfather_mcp.server.brewfather_client` stays patchable.
- Whether to keep a root `package.json` that pins `wrangler`, or let `pywrangler` fetch it.
- The exact wording of the docs.
- FastMCP's allowed-hosts and DNS-rebinding settings on the Worker. With the defaults, the spike accepted the `workers.dev` host.
- Whether to tighten version ranges in `pyproject.toml`. `pywrangler` may resolve the bundle from `pyproject.toml` and not from `uv.lock`, so check what it uses.
- If a dependency moves to an optional extra, update the `uv sync` call in the `Dockerfile` so the home server still gets it.
