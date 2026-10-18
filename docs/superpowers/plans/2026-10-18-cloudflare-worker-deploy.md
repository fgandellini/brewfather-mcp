# Cloudflare Worker Deploy Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Run the Brewfather MCP server as a Cloudflare Python Worker, deployed automatically from `main` by GitHub Actions.

**Architecture:** The existing `brewfather_mcp` package is reused unchanged in behavior. Small testable modules hold the new logic (bearer check, log setup, per-request ASGI app). A thin `src/worker.py` wires them to the Workers runtime. CI gets a bundle check on every build and a `deploy` job on pushes to `main`.

**Tech Stack:** Python 3.13, FastMCP (`mcp>=1.9.0,<2.0.0`), starlette, pytest, `workers-py` (`pywrangler`), Node 22, GitHub Actions.

**Spec:** `docs/superpowers/specs/2026-10-18-cloudflare-worker-deploy-design.md` (read it first; its "What the spike proved" section holds the facts this plan depends on).

## Global Constraints

- Branch `feat/cloudflare-worker` (already exists, holds the spec). Commit messages end with `Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>`.
- Run tests with `uv run pytest`. Tests must not call the real Brewfather API (use respx, mocks, VCR as the existing tests do).
- Keep `brewfather_mcp.server.brewfather_client` a module-level object that tools look up at call time (tests patch it).
- Stay on `mcp<2`. Never add delete tools. Never give the API key `*.delete` scopes.
- Worker name `brewfather-mcp`; URL `https://brewfather-mcp.fgandellini.workers.dev/mcp`; account ID `8c8660fa9720bdee18a1efa54f918d1e`.
- `wrangler.jsonc`: `compatibility_date` `2026-09-07`, `compatibility_flags` `["python_workers"]` only (Python 3.13; do NOT add `python_workers_314`).
- Auth: `Authorization: Bearer <MCP_AUTH_TOKEN>`, compared in constant time. The Worker fails closed when the token is missing or empty. `http_runner.py` keeps running without auth when no token is set.
- Node 22 for everything that runs `pywrangler` (Node 26 fails with `node: bad option: --experimental-wasm-stack-switching`).
- Only `CLOUDFLARE_API_TOKEN` and `CLOUDFLARE_ACCOUNT_ID` go into GitHub secrets. Brewfather credentials and `MCP_AUTH_TOKEN` live only in Cloudflare Worker secrets.
- Free plan: do not add per-request work. The Worker imports at module level and keeps `BREWFATHER_MCP_DEBUG` unset.
- Never print, log or commit secret values. `.env` and `.dev.vars` hold real ones.

## Review Focus

1. Authorization header edge cases: wrong scheme or case, trailing space, `Bearer ` with an empty configured token, non-ASCII bytes. Expected: always "not authorized", never an exception (a `500`). Pinned in Task 3.
2. Credentials absent at import time and at first tool call. Expected: import succeeds; the first call that needs them raises an error naming `BREWFATHER_API_USER_ID` and `BREWFATHER_API_KEY`. Pinned in Task 1.
3. Unauthenticated request to any path (`/`, `/.well-known/...`, `/register`). Expected: `401` before routing. Authenticated request to an unknown path: `404`. Pinned in Task 5.
4. The log filter hides only the one harmless record. Other exception types on that logger, and `ClosedResourceError` on other loggers, still show. Pinned in Task 2.
5. Calling `configure_file_logging` twice (for example via `mcp run` and `main()`) must not duplicate handlers, and stdio entry points must never log to stdout. Pinned in Task 2.

---

### Task 1: Read Brewfather credentials lazily

**Files:**
- Modify: `src/brewfather_mcp/api.py` (`BrewfatherClient.__init__` at line 108, `self.auth` uses at lines 126, 140, 145)
- Test: `tests/test_brewfather_client.py` (new class `TestLazyCredentials`)

**Interfaces:**
- Produces: `BrewfatherClient()` never raises in `__init__`. `BrewfatherClient.auth` becomes a read-only property returning `httpx.BasicAuth`, built from `os.environ` on each access, raising `ValueError` (message names both variables, as today) when either is empty or unset. `max_pages` unchanged.

- [ ] **Step 1: Write the failing tests** in `TestLazyCredentials`:
  - `test_constructor_without_credentials_does_not_raise` (delenv both, `BrewfatherClient()`).
  - `test_auth_without_credentials_raises_value_error_naming_both_variables` (`pytest.raises(ValueError, match="BREWFATHER_API_USER_ID")`, and the message also contains `BREWFATHER_API_KEY`).
  - `test_credentials_set_after_construction_are_used` (construct with env unset, then `setenv`, assert `client.auth` is an `httpx.BasicAuth`).
  - `test_importing_server_without_credentials_succeeds`: run `[sys.executable, "-c", "import brewfather_mcp.server"]` with `PYTHONPATH=src` and an env where both variables are set to the empty string `""`. Empty, not removed: `server.py` calls `load_dotenv()`, which would otherwise read the real `.env`, and `load_dotenv` does not override existing variables. Assert return code 0.
- [ ] **Step 2: Run** `uv run pytest tests/test_brewfather_client.py::TestLazyCredentials -v`. Expected: FAIL (constructor raises).
- [ ] **Step 3: Implement** the property in `api.py`. Remove the credential check and `self.auth` assignment from `__init__`. The existing fixtures set the variables before constructing the client, so they keep working.
- [ ] **Step 4: Run** `uv run pytest -q`. Expected: all pass.
- [ ] **Step 5: Commit** `feat: read Brewfather credentials on first use`.

### Task 2: Move logging setup out of `server.py`; add the log noise filter

**Files:**
- Create: `src/brewfather_mcp/logconfig.py`
- Modify: `src/brewfather_mcp/server.py:44-49` (delete the `logging.basicConfig(...)` call), `src/main.py`, `src/brewfather_mcp/main.py`
- Test: `tests/test_logconfig.py`

**Interfaces:**
- Produces in `logconfig.py`:
  - `configure_file_logging(path: str) -> None`: `logging.basicConfig` at `INFO` with the current format string `"%(asctime)s - %(name)s - %(levelname)s - %(message)s"`, writing to `path` in append mode. Calling it twice must not add a second handler (`basicConfig` already ignores later calls; keep that true).
  - `class DropClosedResourceNoise(logging.Filter)`: `filter(record) -> bool` returns `False` only when `record.name == "mcp.server.streamable_http"` and `record.exc_info` holds an `anyio.ClosedResourceError`.
  - `install_noise_filter() -> None`: adds one `DropClosedResourceNoise` to the logger `"mcp.server.streamable_http"`. Idempotent.

- [ ] **Step 1: Write the failing tests** in `tests/test_logconfig.py`:
  - `test_filter_drops_closed_resource_error_from_streamable_http_logger`
  - `test_filter_keeps_other_exceptions_from_that_logger` (`RuntimeError` record passes)
  - `test_filter_keeps_closed_resource_error_from_other_loggers`
  - `test_filter_keeps_records_without_exception_info`
  - `test_install_noise_filter_is_idempotent` (count filters of that type on the logger == 1 after two calls; remove it in teardown)
  - `test_configure_file_logging_twice_adds_one_file_handler` (use `tmp_path`; snapshot and restore root handlers around the test)
  - `test_importing_server_does_not_add_a_file_handler`: subprocess as in Task 1 (empty credentials), print whether the root logger has a `logging.FileHandler`; assert it does not.
- [ ] **Step 2: Run** `uv run pytest tests/test_logconfig.py -v`. Expected: FAIL (module missing).
- [ ] **Step 3: Implement** `logconfig.py` and delete the `basicConfig` call in `server.py`. In `src/main.py` call `configure_file_logging("/tmp/application.log")` at module level (CLAUDE.md runs it with `mcp run src/main.py`, which imports the file and skips the `__main__` block). In `src/brewfather_mcp/main.py` call it at the start of `main()`.
- [ ] **Step 4: Run** `uv run pytest -q`. Expected: all pass. Also run `uv run python -c "import sys; sys.path.insert(0,'src'); import http_runner"` to confirm `http_runner` still imports.
- [ ] **Step 5: Commit** `refactor: configure logging in entry points, not in server.py`.

### Task 3: Shared bearer check

**Files:**
- Create: `src/brewfather_mcp/auth.py`
- Modify: `src/http_runner.py` (`BearerAuthMiddleware.__call__`)
- Test: `tests/test_auth.py`

**Interfaces:**
- Produces: `is_authorized(authorization: str | None, token: str | None) -> bool`. True only when `token` is non-empty and `authorization == f"Bearer {token}"`, compared with `hmac.compare_digest` on the UTF-8 **bytes** of both strings (a `str` with non-ASCII characters makes `compare_digest` raise `TypeError`). Never raises.

- [ ] **Step 1: Write the failing tests** in `tests/test_auth.py`:
  - `test_is_authorized_accepts_exact_bearer` (`("Bearer s3cret", "s3cret")` is True).
  - `test_is_authorized_rejects` parametrized over: `(None, "s3cret")`, `("", "s3cret")`, `("Bearer wrong", "s3cret")`, `("bearer s3cret", "s3cret")`, `("Basic s3cret", "s3cret")`, `("Bearer s3cret ", "s3cret")`, `("Bearer s3cret", "")`, `("Bearer s3cret", None)`, `("Bearer ", "")`, `("", "")`, `(None, None)`, `("Bearer é", "s3cret")`. Every case returns False without raising.
  - `test_middleware_returns_401_without_token_and_passes_with_it`: wrap a one-route starlette app in `BearerAuthMiddleware(app, "s3cret")`, use `TestClient`; no header gives 401 with body `{"error": "Unauthorized"}`; the right header gives 200.
- [ ] **Step 2: Run** `uv run pytest tests/test_auth.py -v`. Expected: FAIL.
- [ ] **Step 3: Implement** `auth.py`; make the middleware call `is_authorized` (keep its constructor signature `(app, token)`, the latin-1 header decoding, and the 401 JSON body).
- [ ] **Step 4: Run** `uv run pytest -q`. Expected: all pass.
- [ ] **Step 5: Commit** `feat: add shared bearer token check`.

### Task 4: Per-request ASGI app for the Worker

**Files:**
- Create: `src/brewfather_mcp/worker_support.py`
- Test: `tests/test_worker_support.py`

**Interfaces:**
- Produces: `configure_stateless(mcp: FastMCP) -> None` sets `settings.stateless_http = True`, `settings.json_response = True`, `settings.streamable_http_path = "/mcp"`. `fresh_asgi_app(mcp: FastMCP) -> ASGIApp` sets `mcp._session_manager = None` and returns `mcp.streamable_http_app()` (spike fact 5). Both take the FastMCP instance as a parameter so tests never touch the global `server.mcp`.

- [ ] **Step 1: Write the failing tests.** Build a throwaway `FastMCP("test")` with one tool per test. If the locked SDK answers `421` for the `TestClient` host, pass `transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False)` to the constructor.
  - `test_configure_stateless_sets_the_three_settings`
  - `test_fresh_asgi_app_serves_two_sequential_requests`: twice, `with TestClient(fresh_asgi_app(m)) as c:` POST `/mcp` with the MCP `initialize` JSON-RPC body and headers `Accept: application/json, text/event-stream`; assert status 200 and `result.serverInfo.name == "test"` both times (the `with` block runs ASGI lifespan, as the Workers adapter does on every request).
  - `test_reusing_one_app_fails_on_the_second_lifespan`: build `m.streamable_http_app()` once, enter `TestClient(app)` twice; the second raises `RuntimeError` mentioning "only be called once". This pins why the workaround exists. If a future SDK fixes it, this test fails and tells you to delete the workaround.
- [ ] **Step 2: Run** `uv run pytest tests/test_worker_support.py -v`. Expected: FAIL (module missing).
- [ ] **Step 3: Implement** the two functions. Put the one-line reason (adapter runs lifespan per request; the session manager can run only once) as a comment on `fresh_asgi_app`.
- [ ] **Step 4: Run** `uv run pytest -q`. Expected: all pass.
- [ ] **Step 5: Commit** `feat: add helpers to serve the MCP app from a Worker`.

### Task 5: Worker entry point and bundle

**Files:**
- Create: `src/worker.py`, `wrangler.jsonc`
- Modify: `pyproject.toml`, `uv.lock`, `.gitignore`

**Interfaces:**
- Consumes: `server.mcp`, `is_authorized`, `install_noise_filter`, `configure_stateless`, `fresh_asgi_app`.
- Produces: `class Default(WorkerEntrypoint)` in `src/worker.py`, the Worker entry.

- [ ] **Step 1: Dependencies.** In `pyproject.toml` move `uv` and `pytest-cov` from `dependencies` to the `dev` group; add `workers-py` and `workers-runtime-sdk` to `dev`. Run `uv lock` and `uv run pytest -q` (all pass). Add `.dev.vars`, `.wrangler/`, `node_modules/` and `.venv-workers/` to `.gitignore`.
- [ ] **Step 2: `wrangler.jsonc`** with exactly: `name` `brewfather-mcp`, `main` `src/worker.py`, `compatibility_date` `2026-09-07`, `compatibility_flags` `["python_workers"]`, `observability` `{"enabled": true}`. No `package.json` (my call: `pywrangler` runs `npx --yes wrangler`).
- [ ] **Step 3: Implement `src/worker.py`** as a thin file:
  - Module level, in this order: import `workers` (`Response`, `WorkerEntrypoint`, `asgi`); `from brewfather_mcp import server` (imports must be module level, spike fact 2); call `configure_stateless(server.mcp)` and `install_noise_filter()`.
  - `Default.__init__(self, ctx, env)`: copy `BREWFATHER_API_USER_ID` and `BREWFATHER_API_KEY` from `env` into `os.environ` using `getattr(env, name, None)`, skipping missing ones (the client then raises its clear error on first use).
  - `Default.fetch(self, request)`: first `is_authorized(request.headers.get("authorization"), getattr(self.env, "MCP_AUTH_TOKEN", None))`, otherwise `Response('{"error": "Unauthorized"}', status=401)`. Then if the path is `/mcp`, `return await asgi.fetch(fresh_asgi_app(server.mcp), request, self.env)`; any other path returns `Response("Not found", status=404)`.
- [ ] **Step 4: Bundle check.** With Node 22 on PATH run `uv run pywrangler deploy --dry-run`. Expected: it prints a module table and `Total Upload` (no Cloudflare credentials needed). The spike measured about 10 MiB uncompressed and 2.6 MiB gzip; report the new numbers. If the bundle fails because of `mcp[cli]`, `starlette` or `uvicorn`: move the offending package to an optional extra used only by `http_runner.py`, add that extra to the `uv sync` calls in the `Dockerfile` and to CI, and record the choice in the commit message.
- [ ] **Step 5: Local run.** Create `.dev.vars` with `BREWFATHER_API_USER_ID=placeholder`, `BREWFATHER_API_KEY=placeholder`, `MCP_AUTH_TOKEN=test-token` (placeholders, so no real data is touched). Start `uv run pywrangler dev --port 8787` (restart it after any `.dev.vars` change). Check with `curl`, all Expected:
  - `POST /mcp` without a header returns `401`; with `Authorization: Bearer wrong` returns `401`.
  - `GET /` and `GET /.well-known/oauth-protected-resource` without a header return `401`; `GET /` with the right token returns `404`.
  - `tools/list` with the right token returns 200 with all tools (26 at the time of the spike).
  - `tools/call` `list_inventory_categories` succeeds, and `list_hops` returns an error text containing `401 Unauthorized` (proves the outbound path works, and that missing credentials do not break import).
  - Two requests in a row both succeed. Then stop the dev server.
- [ ] **Step 6: Commit** `feat: add Cloudflare Worker entry point` (include `uv.lock`).

### Task 6: CI bundle check and deploy job

**Files:**
- Modify: `.github/workflows/python-app.yml`

- [ ] **Step 1:** In the existing `build` job, after "Set up Python" add `actions/setup-node@v4` with `node-version: "22"`, and after "Run tests" add a step "Check the Worker bundle" running `uv run pywrangler deploy --dry-run`. The job keeps running on pull requests and pushes.
- [ ] **Step 2:** Add a `deploy` job: `needs: build`; `if: github.event_name == 'push' && github.ref == 'refs/heads/main'`; `runs-on: ubuntu-latest`; `concurrency: {group: deploy-worker, cancel-in-progress: false}`; job `env` `CLOUDFLARE_API_TOKEN: ${{ secrets.CLOUDFLARE_API_TOKEN }}` and `CLOUDFLARE_ACCOUNT_ID: ${{ secrets.CLOUDFLARE_ACCOUNT_ID }}`. Steps: checkout, `astral-sh/setup-uv@v5`, setup-node 22, `uv python install`, `uv sync --locked --dev`, `uv run pywrangler deploy`, then a "Smoke check" step with `WORKER_URL: https://brewfather-mcp.fgandellini.workers.dev`: up to 5 attempts, 5 s apart, `curl -s -o /dev/null -w '%{http_code}' -X POST "$WORKER_URL/mcp" -H 'Content-Type: application/json' -d '{}'`; succeed on `401`, otherwise print the last code and exit 1.
- [ ] **Step 3: Verify** the YAML parses (`uv run python -c "import yaml,sys; yaml.safe_load(open('.github/workflows/python-app.yml'))"` or `actionlint` if installed). The workflow itself is exercised in Task 8.
- [ ] **Step 4: Commit** `ci: check the Worker bundle and deploy main to Cloudflare`.

### Task 7: Documentation

**Files:**
- Modify: `CLAUDE.md`, `README.md`

- [ ] **Step 1: CLAUDE.md.** Delete the Railway, Fly.io and Render notes under "Cloud Deployment" (owner-approved). Keep the HTTP/stdio and Docker notes. Add a "Cloudflare Worker" section covering: entry `src/worker.py`; run locally with `uv run pywrangler dev` (Node 22; `.dev.vars` for local secrets; restart after changing it); one-time secrets via `wrangler secret put` for the three Worker secrets; deploys happen from the CI `deploy` job on push to `main`; the free-plan risk (documented 10 ms CPU limit vs 44-59 ms median measured, so errors `1102` mean the plan or a Container is needed); and the three spike facts a future change could break (module-level imports, per-request session manager, no file logging). Add `src/worker.py` to the Entry Points list.
- [ ] **Step 2: README.md.** Add a short "Cloudflare Worker" section after the HTTP Server section: what it is, the MCP URL, the bearer-token header, and a link to the design doc.
- [ ] **Step 3: Verify** with `grep -n "Railway\|Fly.io\|Render" CLAUDE.md README.md` (Expected: no matches) and `uv run pytest -q` (all pass).
- [ ] **Step 4: Commit** `docs: document the Cloudflare Worker deployment`.

### Task 8: First deploy, secrets and cutover (owner-gated)

Each step changes the owner's real accounts. Do not run one without the owner's go-ahead in chat. The owner has saved `CLOUDFLARE_API_TOKEN` and `CLOUDFLARE_ACCOUNT_ID` in `.env`; read them into the environment without printing them.

- [ ] **Step 1: First deploy.** With Node 22: `uv run pywrangler deploy`. Expected: `Deployed brewfather-mcp`, URL `https://brewfather-mcp.fgandellini.workers.dev`.
- [ ] **Step 2: Worker secrets.** For each of `BREWFATHER_API_USER_ID`, `BREWFATHER_API_KEY`, `MCP_AUTH_TOKEN`: pipe the value from `.env` into `npx wrangler secret put <NAME>` (never echo it). Expected: three `Success! Uploaded secret` lines.
- [ ] **Step 3: Live check.** `POST /mcp`: no token returns `401`; the right token with `tools/list` returns 200; `tools/call list_hops` returns real inventory (read-only). Then query the Worker logs and confirm there are no `OSError` lines and no `Error in message router` lines.
- [ ] **Step 4: GitHub secrets.** `gh secret set CLOUDFLARE_API_TOKEN` and `gh secret set CLOUDFLARE_ACCOUNT_ID` (from `.env`, via stdin).
- [ ] **Step 5: Open the PR** from `feat/cloudflare-worker` (description ends with `🤖 Generated with [Claude Code](https://claude.com/claude-code)`). Expected: the PR runs `build` including the bundle check, and no `deploy` job. After the owner merges, expected: `build` then `deploy` pass, and the smoke check returns `401`.
- [ ] **Step 6: Connector.** The owner points the claude.ai connector at `https://brewfather-mcp.fgandellini.workers.dev/mcp` with the same bearer token and confirms it lists the tools and returns inventory.
- [ ] **Step 7: Spike cleanup** (after the owner confirms step 6): `npx wrangler delete --name brewfather-mcp-spike`, then delete the local `spike-cf/` directory (it holds copies of the real credentials and the Cloudflare token) and remove the `spike-cf/` line from `.git/info/exclude`. The home server stays running as the fallback.
