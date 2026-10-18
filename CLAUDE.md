# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

This is a Model Context Protocol (MCP) server that integrates with the Brewfather API to provide brewing inventory management and recipe analysis capabilities. The server exposes tools for managing fermentables, hops, yeasts, batches, recipes, and miscellaneous brewing supplies.

The API is documented, but not well, at https://docs.brewfather.app/api
In order to make robust code, we need to "test in production" by making calls to tools and debug the results. This is fine to do directly for get and list operations, but not for operations that change data. For that, we _might_ be able to create a test entry (inventory, recipe, batch) first, then test, then clean up by carefully deleting the test item.

## Development Commands

### Package Management
- `uv run pytest` - Run test suite
- `uv run pytest tests/test_file.py::TestClass::test_method` - Run specific test
- `uv run pytest --cov` - Run tests with coverage
- `uv install` - Install dependencies
- `uv sync` - Sync dependencies

### MCP Development

The server supports two transport modes:

#### stdio (Local Development)
When using claude code, use mcpt commands to test changes to this server. The inbuilt mcp tools don't get reloaded after changes.

- `uv run --with mcp[cli] mcp install` - Install MCP CLI tools
- `uv run --with 'mcp[cli]' mcp run src/main.py` - Run server
- `uv run --with 'mcp[cli]' mcp dev src/main.py` - Run server with inspector
- `mcpt tools uv run --with 'mcp[cli]' mcp run src/main.py` - Use MCP Tools to list tools
- `mcpt call list_batches  uv run --with 'mcp[cli]' mcp run src/main.py` - Call a tool
- `mcpt call get_batch_detail --params '{ "batch_id": "C3hZC7P4zeNH6QJsc7FXizVGN8dkQe" }'  uv run --with 'mcp[cli]' mcp run src/main.py` - Call a tool with params
- `BREWFATHER_MCP_DEBUG=1 mcpt call get_batch_detail --params '{ "batch_id": "C3hZC7P4zeNH6QJsc7FXizVGN8dkQe" }' uv run --with 'mcp[cli]' mcp run src/main.py` - Call tool with debug mode to save API calls to file
- `alias -g BF="uv run --with 'mcp[cli]' mcp run src/main.py"` - Alias to use with mcpt, eg `mcpt tools BF`

#### HTTP/SSE (Web/Cloud Deployment)
For testing the HTTP server or deployment to cloud platforms:

**Start HTTP Server:**
- `PYTHONPATH=src python src/http_runner.py --port 8000` - Start HTTP/SSE server on port 8000
- `PYTHONPATH=src python src/http_runner.py --host 0.0.0.0 --port 8000 --log-level DEBUG` - Start with custom settings

**Testing HTTP Server with mcpt:**
- `mcpt tools http://localhost:8000/sse` - List available tools via HTTP
- `mcpt call list_inventory_categories http://localhost:8000/sse` - Call a simple tool
- `mcpt call inventory_summary http://localhost:8000/sse` - Call a complex tool
- `mcpt call get_fermentable_detail --params '{"identifier": "default-08f456e"}' http://localhost:8000/sse` - Call tool with parameters
- `mcpt call set_inventory --params '{"kind": "fermentables", "item_id": "default-08f456e", "amount": 5.0}' http://localhost:8000/sse` - Call update tool

**Health Check:**
- `curl http://localhost:8000/sse` - Check if SSE endpoint is responding (will hang waiting for events, which is expected)

### Cloudflare Worker

The server also runs as a Cloudflare Python Worker named `brewfather-mcp`, MCP endpoint `https://brewfather-mcp.fgandellini.workers.dev/mcp`. Design: `docs/superpowers/specs/2026-10-18-cloudflare-worker-deploy-design.md`.

- **Code**: `src/worker.py` is a thin entry point; the logic lives in `brewfather_mcp/auth.py` (bearer check), `worker_support.py` (stateless settings, per-request ASGI app) and `logconfig.py` (log setup and filter). Config: `wrangler.jsonc`.
- **Run locally**: needs Node 22 (Node 26 fails with `bad option: --experimental-wasm-stack-switching`). Put `BREWFATHER_API_USER_ID`, `BREWFATHER_API_KEY` and `MCP_AUTH_TOKEN` in `.dev.vars` (git-ignored), then `uv run pywrangler dev --port 8787`. Restart it after every change to `.dev.vars`; a hot reload keeps the old values. Check that the bundle builds with `uv run pywrangler deploy --dry-run`.
- **Secrets**: set once with `npx wrangler secret put <NAME>` for `BREWFATHER_API_USER_ID`, `BREWFATHER_API_KEY` and `MCP_AUTH_TOKEN`. They stay across deploys. GitHub holds only `CLOUDFLARE_API_TOKEN` and `CLOUDFLARE_ACCOUNT_ID`.
- **Deploys**: the CI `deploy` job runs `pywrangler deploy` on every push to `main`, after the tests pass, then checks that an unauthenticated request gets `401`. Pull requests only run `pywrangler deploy --dry-run`.
- **Auth**: every path needs `Authorization: Bearer <MCP_AUTH_TOKEN>`. The Worker refuses everything when the secret is missing.
- **Rules that keep it working**:
  - `src/worker.py` imports at module level. Cloudflare snapshots memory at deploy time only for those imports; importing inside the handler costs about 2 s of CPU per cold start.
  - Every request gets a fresh MCP session manager (`fresh_asgi_app`). The Workers ASGI adapter runs lifespan per request, and the SDK's manager can run only once.
  - Library code must not configure logging or write files. Entry points do that (`logconfig.py`).
  - The Worker logs to stdout (`configure_stdout_logging`). Cloudflare labels anything written to stderr as an error, so stderr would show every INFO line as one.
  - The runtime dependency is `mcp` without the `[cli]` extra. `typer` pulls in `rich`, and `rich` calls `random.getrandbits()` at import, which Workers forbid while starting.
  - `pywrangler` bundles from `[project].dependencies` and resolves its own `mcp` version (1.12.4 when this was written), not the one in `uv.lock`. Check both when changing SDK code.
- **Free plan risk**: Cloudflare documents a 10 ms CPU limit per request on the free plan. Measured CPU was 44-59 ms median and nothing was blocked, but it is undocumented behavior. If requests start failing with error `1102`, the options are the Workers Paid plan or a Cloudflare Container.
- The home server (`src/http_runner.py`, Docker) stays as the fallback.

## Architecture

### Entry Points

- **CLI**: `brewfather-mcp` script (defined in pyproject.toml, installed via uvx or uv)
- **Local dev**: `src/main.py` or `src/brewfather_mcp/main.py` (both entry points exist)
- **HTTP server**: `src/http_runner.py` for SSE transport
- **Cloudflare Worker**: `src/worker.py` (see the Cloudflare Worker section)

### Core Components

**API Client (`src/brewfather_mcp/api.py`)**
- `BrewfatherClient` - Main HTTP client for Brewfather API
- Uses httpx with basic auth (BREWFATHER_API_USER_ID, BREWFATHER_API_KEY)
- Implements CRUD operations for all inventory categories and recipes
- Base URL: `https://api.brewfather.app/v2`
- Debug mode (`BREWFATHER_MCP_DEBUG=1`) saves API responses to `debug/` directory

**MCP Server (`src/brewfather_mcp/server.py`)**
- Uses FastMCP framework to expose tools and prompts
- Contains all MCP tool definitions that wrap API client methods
- Includes specialized prompts for beer style suggestions based on inventory
- Logs to `/tmp/application.log`

**Type Definitions (`src/brewfather_mcp/types/`)**
- Pydantic models organized by domain (fermentable, hop, yeast, misc, batch, recipe, brewtracker)
- Separate models for list views vs detail views
- Handles complex nested structures (recipes, water profiles, fermentation schedules)
- `base.py` contains shared types (MashStepType, FermentationStepType, etc)

**Validation (`src/brewfather_mcp/validation.py`)**
- Field allowlists, enums and ranges for every write (batches, inventory items, recipes). The API silently accepts unknown fields, so tools validate first and return `Invalid request: ...` without calling the API
- `RateLimitError` in `api.py` is raised on HTTP 429 (500 calls/hour per key) and carries the `Retry-After` value
- Never add delete tools, and never grant `*.delete` scopes to the API key

**Inventory Utilities (`src/brewfather_mcp/inventory.py`)**
- Helper functions for creating inventory summaries
- Used by the `inventory_summary` MCP tool

**Formatter Utilities (`src/brewfather_mcp/formatter.py`)**
- `format_recipe_details()` - Converts recipe objects to formatted text
- Used by recipe and batch detail tools

### Environment Configuration

Required environment variables:
- `BREWFATHER_API_USER_ID` - Your Brewfather API user ID
- `BREWFATHER_API_KEY` - Your Brewfather API key

For testing, use `.test.env` file (automatically loaded by pytest).
When developing, use `.env` file

### Testing Strategy

- Uses pytest with pytest-vcr for HTTP request recording/replay
- VCR cassettes stored in `tests/cassettes/`
- Test configuration in `tests/conftest.py` includes auth header filtering
- Coverage configuration excludes test files
- `scripts/live_check_writes.py --yes` exercises the write tools on scratch items in the real account (delete them in the app afterwards)

### Key MCP Tools

The server exposes these main tool categories:
- **Inventory**: List/detail/search for fermentables, hops, yeasts, misc items (`list_inventory` takes `order_by` and `order_by_direction`); `set_inventory` (absolute or relative stock), `create_inventory_item`, `update_inventory_item`
- **Recipes**: List (with `order_by`/`order_by_direction`), search, detail, `create_recipe`, `update_recipe` (shallow merge: ingredient lists replace the whole list)
- **Batches**: List (with `status`, `order_by`, `order_by_direction`), search, detail, and update brewing batches with measured values (batches cannot be created through the API)
- **Readings**: `get_batch_readings_summary` (newest raw readings), `get_batch_readings_curve` (whole batch or a date range averaged into N time buckets, logic in `readings.py`), `get_batch_last_reading`, `get_batch_brewtracker`
- **Summaries**: Combined inventory overviews and brewing style suggestions

### List Query Parameters

- `ListQueryParams` in `api.py` maps to the API's list query string: `limit`, `start_after`, `status`, `order_by`, `order_by_direction`, `inventory_exists`, `inventory_negative`, `complete` and `include`.
- `include` is a comma-separated list of extra fields for list calls (dotted paths work, for example `recipe.fermentables`). Recipe and batch lists use it (`RECIPE_LIST_INCLUDE`, `BATCH_LIST_INCLUDE` in `server.py`) to show OG, FG, IBU and ABV in summaries. Detail calls ignore it.
- `complete=true` returns full objects in list calls. No tool uses it, because no tool makes per-item detail calls.

### Code Patterns

- All API methods are async and use httpx
- Pydantic models validate all API responses
- MCP tools provide formatted string outputs for Claude consumption
- Error handling logs exceptions and re-raises them
- Consistent URL building pattern using `_build_url()` method