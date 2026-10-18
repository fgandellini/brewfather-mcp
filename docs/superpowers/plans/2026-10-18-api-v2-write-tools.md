# Brewfather API v2 Write Tools Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add rate-limit handling, write validation, search tools, relative stock changes, inventory create/edit and recipe create/update to the Brewfather MCP server.

**Architecture:** A new `validation.py` module holds field allowlists and range checks, and raises `ValueError` before any HTTP call. `api.py` gets one error path for HTTP 429 and generic write methods. `server.py` keeps one tool function per MCP tool and maps `ValueError` to a clear error message.

**Tech Stack:** Python 3.13, FastMCP (`mcp[cli]`), httpx, pydantic, pytest, pytest-asyncio, respx.

**Spec:** No separate design document. The design was agreed in chat (2026-10-18) and is in Global Constraints below. API reference, fetched 2026-10-18: https://docs.brewfather.app/api.md , https://docs.brewfather.app/api/types.md , https://docs.brewfather.app/api/enums.md .

## Global Constraints

- All values are metric: liters, kg, grams, Celsius, SG.
- Rate limit is 500 calls per hour per key. HTTP 429 carries a `Retry-After` header.
- Batch create is NOT in the public API. Do not add it. Do not add any delete tool (recipe, batch or inventory).
- The user is the only user of this server, so existing tools may be renamed or removed.
- Batch PATCH ranges: `status` in the `BatchStatus` values; gravities (`measuredFirstWortGravity`, `measuredPreBoilGravity`, `measuredPostBoilGravity`, `measuredOg`, `measuredFg`) from 0.1 to 1.9; `measuredMashPh` from 0 to 14; volumes (`measuredBoilSize`, `measuredKettleSize`, `measuredFermenterTopUp`, `measuredBatchSize`, `measuredBottlingSize`) 0 or more; `carbonationTemp` from -50 to 100. Sending `null` clears a measured value.
- Inventory PATCH: a body with only `inventory` and/or `inventory_adjust` changes stock only (`inventory` wins if both are sent). Any other field makes it a partial update. Numeric strings such as `5kg` are rejected by the API.
- Recipe PATCH is a shallow merge. Array fields (`fermentables`, `hops`, `miscs`, `yeasts`) replace the whole array. Fields starting with `_`, plus `createdAt`, `updatedAt` and `data`, are server-managed.
- Write checks use allowlists. An unknown field raises `ValueError`. Bool values are not valid numbers. NaN and infinity are not valid numbers.
- Tests must not call the real API. Use respx for HTTP and `MagicMock`/`AsyncMock` for the client, as the existing tests do.
- Run tests with `uv run pytest`.
- Work on branch `feat/api-v2-write-tools`. Commit messages end with `Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>`.

## Review Focus

- A 429 response without a `Retry-After` header: the error must still be clear and must not crash.
- `update_batch` with a field both set and listed in `clear_fields`, or with an unknown name in `clear_fields`: reject with a clear message.
- `set_inventory` with both `amount` and `adjust`, or with neither: reject. A negative `adjust` is valid.
- `find_*` and `list_inventory` with a name in a different case, with no match, or with more than 500 items on the account (the page limit): no crash, and a clear "no match" text.
- `update_recipe` with an empty ingredient array would erase all ingredients: reject it (my call, see Task 5).
- Numeric validation with `True`, `float("nan")` and strings: reject.

## File Structure

- Create `src/brewfather_mcp/validation.py`: allowlists, enums, range checks. No HTTP, no MCP.
- Modify `src/brewfather_mcp/api.py`: `RateLimitError`, one response check for all requests, generic inventory and recipe write methods, `status` query parameter.
- Modify `src/brewfather_mcp/server.py`: new and changed tools.
- Create `tests/test_validation.py`; modify `tests/test_brewfather_client.py` and `tests/test_mcp_server.py`.
- Create `scripts/live_check_writes.py`; modify `README.md` and `CLAUDE.md`.

---

### Task 1: Rate-limit handling

**Files:**
- Modify: `src/brewfather_mcp/api.py` (`_make_request`, `_make_patch_request`, `_make_post_request`)
- Test: `tests/test_brewfather_client.py`

**Interfaces:**
- Produces: `class RateLimitError(Exception)` in `api.py` with attribute `retry_after: str | None`; `BrewfatherClient._check_response(response: httpx.Response) -> None`, which raises `RateLimitError` on status 429 and calls `response.raise_for_status()` otherwise.

- [ ] **Step 1: Write failing tests** in `tests/test_brewfather_client.py` (respx, existing `client` fixture):
  - `test_rate_limit_get_with_retry_after`: GET `/batches/b1` returns 429 with header `Retry-After: 30`. Expect `RateLimitError`; `str(error)` contains `"30 seconds"` and `"500 calls per hour"`; `error.retry_after == "30"`.
  - `test_rate_limit_patch_without_retry_after`: PATCH returns 429 without the header. Expect `RateLimitError`, `error.retry_after is None`, and message contains `"try again later"`.
  - `test_rate_limit_post`: POST `/recipes` returns 429. Expect `RateLimitError`. (Call `client._make_post_request(f"{BASE_URL}/recipes", {})`.)
  - The existing 500 and 401 tests must still expect `httpx.HTTPStatusError`.
- [ ] **Step 2: Run** `uv run pytest tests/test_brewfather_client.py -k rate_limit -v`. Expected: FAIL (`RateLimitError` not defined).
- [ ] **Step 3: Implement** `RateLimitError` and `_check_response`, and call `_check_response` in the three request helpers instead of `raise_for_status()`.
- [ ] **Step 4: Run** `uv run pytest -v`. Expected: all PASS.
- [ ] **Step 5: Commit** `feat: surface Brewfather rate limit with Retry-After`.

---

### Task 2: Validation module and batch update

**Files:**
- Create: `src/brewfather_mcp/validation.py`
- Modify: `src/brewfather_mcp/server.py:658-714` (`update_batch`)
- Test: `tests/test_validation.py`, `tests/test_mcp_server.py`

**Interfaces:**
- Produces in `validation.py`:
  - `BATCH_UPDATE_RANGES: dict[str, tuple[float | None, float | None]]` (one entry per numeric batch field in Global Constraints).
  - `validate_batch_update(values: dict[str, object], clear_fields: list[str] | None = None) -> dict[str, object]`: returns the PATCH body. Fields in `clear_fields` become `None`. Raises `ValueError` for: unknown field, invalid status, value outside range, non-number value (bool, NaN, infinity, string), a field both set and cleared, `status` in `clear_fields`, empty result.
  - `require_number(name: str, value: object, minimum: float | None = None, maximum: float | None = None) -> float`: shared by later tasks.
- Consumes: `BatchStatus` from `brewfather_mcp.types.batch`.

- [ ] **Step 1: Write failing tests** in `tests/test_validation.py`:
  - `test_batch_update_valid`: `{"measuredOg": 1.055, "status": "Fermenting"}` returns the same dict.
  - `test_batch_update_clear`: `validate_batch_update({}, ["measuredFg"]) == {"measuredFg": None}`.
  - `test_batch_update_rejects`: parametrized with `{"measuredOg": 2.0}`, `{"measuredOg": 0.05}`, `{"measuredMashPh": 14.5}`, `{"measuredBatchSize": -1}`, `{"carbonationTemp": 101}`, `{"status": "Done"}`, `{"measuredOg": True}`, `{"measuredOg": float("nan")}`, `{"measuredOg": "1.05"}`, `{"colour": 1}`. All raise `ValueError`.
  - `test_batch_update_conflict`: `validate_batch_update({"measuredOg": 1.05}, ["measuredOg"])` raises `ValueError`. Also `clear_fields=["status"]` and `clear_fields=["nope"]` raise.
  - `test_batch_update_empty`: raises `ValueError`.
  - In `tests/test_mcp_server.py` update the three existing `update_batch` tests: `test_update_batch_no_params` expects the result `"No update parameters provided."` as today. Add `test_update_batch_clear_fields` (`update_batch(batch_id="b", clear_fields=["measuredFg"])` calls `update_batch_detail("b", {"measuredFg": None})`) and `test_update_batch_invalid_value` (`measuredOg=2.0` returns text starting with `"Invalid update:"` and does not call the client).
- [ ] **Step 2: Run** `uv run pytest tests/test_validation.py -v`. Expected: FAIL (module missing).
- [ ] **Step 3: Implement** `validation.py` as specified.
- [ ] **Step 4: Change `update_batch`** in `server.py`: add parameter `clear_fields: Optional[list[str]] = None`, build the values dict from the existing named parameters (keep names), call `validate_batch_update`, catch `ValueError` and return `f"Invalid update: {error}"`. Keep the "No update parameters provided." result when nothing is given, and the existing error logging.
- [ ] **Step 5: Run** `uv run pytest -v`. Expected: all PASS.
- [ ] **Step 6: Commit** `feat: validate batch updates and allow clearing measured values`.

---

### Task 3: Relative stock changes

**Files:**
- Modify: `src/brewfather_mcp/api.py` (replace the four `update_*_inventory` methods), `src/brewfather_mcp/server.py:806-860` (replace the four update tools)
- Test: `tests/test_brewfather_client.py`, `tests/test_mcp_server.py`

**Interfaces:**
- Produces in `api.py`: `BrewfatherClient.update_inventory(category: InventoryCategory, id: str, data: dict) -> None` (PATCH `inventory/{category}/{id}`).
- Produces in `server.py`: tool `set_inventory(kind: str, item_id: str, amount: float | None = None, adjust: float | None = None) -> str`. `kind` is one of `fermentables`, `hops`, `miscs`, `yeasts`. The tool sends `{"inventory": amount}` or `{"inventory_adjust": adjust}`.
- Consumes: `require_number` from Task 2.

- [ ] **Step 1: Write failing tests.**
  - Client: `test_update_inventory_patch` (respx PATCH `/inventory/hops/h1`, body `{"inventory_adjust": -20}`, request JSON equals that body).
  - Server: `test_set_inventory_amount` (calls `update_inventory(InventoryCategory.HOPS, "h1", {"inventory": 50.0})`), `test_set_inventory_adjust` (negative adjust `-20.0` sends `{"inventory_adjust": -20.0}`), `test_set_inventory_both_or_neither` (returns text starting `"Invalid request:"`, client not called), `test_set_inventory_unknown_kind` (`kind="grains"` returns `"Invalid request:"`).
  - Remove the old `update_*_inventory` tool tests and mock lines in the `mock_brewfather_client` fixture; add `client.update_inventory.return_value = None`.
- [ ] **Step 2: Run** `uv run pytest -k "inventory" -v`. Expected: FAIL.
- [ ] **Step 3: Implement** `update_inventory` and `set_inventory`; delete the four old methods and four old tools.
- [ ] **Step 4: Run** `uv run pytest -v`. Expected: all PASS.
- [ ] **Step 5: Commit** `feat: add set_inventory with absolute and relative stock changes`.

---

### Task 4: Inventory create and edit

**Files:**
- Modify: `src/brewfather_mcp/validation.py`, `src/brewfather_mcp/api.py`, `src/brewfather_mcp/server.py`
- Test: `tests/test_validation.py`, `tests/test_brewfather_client.py`, `tests/test_mcp_server.py`

**Interfaces:**
- Produces in `validation.py`:
  - `INVENTORY_FIELDS: dict[InventoryCategory, set[str]]`: the writable fields per kind. Copy them from the Fermentable, Hop, Yeast and Misc objects in https://docs.brewfather.app/api/types.md , excluding every `_`-prefixed field, `createdAt`, `updatedAt`, `amount`/`percentage`/`ibu` recipe-only fields for fermentables and hops, and `inventory_adjust`.
  - `validate_inventory_fields(category: InventoryCategory, fields: dict[str, object]) -> dict[str, object]`: raises `ValueError` for unknown fields, enum values outside `docs.brewfather.app/api/enums.md` (fermentable `type`, hop `use` and `type`, yeast `type`, `form` and `flocculation`, misc `type`), and non-finite numbers in numeric fields.
- Produces in `api.py`: `BrewfatherClient.create_inventory_item(category: InventoryCategory, data: dict) -> str` (POST, returns response text).
- Produces in `server.py`: tools `create_inventory_item(kind: str, name: str, fields: dict | None = None, amount: float | None = None) -> str` (`amount` is sent as `inventory`) and `update_inventory_item(kind: str, item_id: str, fields: dict) -> str`.
- Consumes: `update_inventory` from Task 3.

- [ ] **Step 1: Write failing tests.**
  - Validation: `test_inventory_valid_hop` (`{"name": "Citra", "alpha": 12.0, "type": "Pellet"}` passes), `test_inventory_rejects_unknown_field` (`{"alphaa": 1}`), `test_inventory_rejects_bad_enum` (hop `type="Powder"`, yeast `form="Cube"`), `test_inventory_rejects_server_fields` (`{"_id": "x"}`, `{"createdAt": "x"}`).
  - Client: `test_create_inventory_item_post` (respx POST `/inventory/hops` returns 200 with body `{"_id": "new1"}`; request JSON equals the sent data).
  - Server: `test_create_inventory_item` (sends `{"name": "Citra", "alpha": 12.0, "inventory": 100.0}`; returned text contains the new ID parsed from the response `_id`), `test_create_inventory_item_invalid` (returns `"Invalid request:"`, no HTTP call), `test_update_inventory_item` (calls `update_inventory(category, "h1", {"alpha": 11.5})`), `test_update_inventory_item_rejects_stock_fields` (`fields={"inventory": 5}` returns text telling to use `set_inventory`).
- [ ] **Step 2: Run** `uv run pytest -k "inventory" -v`. Expected: FAIL.
- [ ] **Step 3: Implement** the allowlists, the validator, the client method and the two tools. Parse the POST response with `json.loads` and read `_id`; if it is missing, return the raw text.
- [ ] **Step 4: Run** `uv run pytest -v`. Expected: all PASS.
- [ ] **Step 5: Commit** `feat: add create and update tools for inventory items`.

---

### Task 5: Search tools

**Files:**
- Modify: `src/brewfather_mcp/api.py` (`ListQueryParams.status`, generic list method), `src/brewfather_mcp/server.py`
- Test: `tests/test_brewfather_client.py`, `tests/test_mcp_server.py`

**Interfaces:**
- Produces in `api.py`: field `ListQueryParams.status: str | None = None` (query string `status=...`); `BrewfatherClient.get_inventory_list(category: InventoryCategory, query_params: ListQueryParams | None = None)` returning the matching list model (`FermentableList`, `HopList`, `MiscList` or `YeastList`).
- Produces in `server.py`: tools `find_batches(name: str | None = None, status: str | None = None) -> str`, `find_recipes(name: str | None = None) -> str`, `list_inventory(kind: str, name: str | None = None, in_stock_only: bool = False) -> str`.
- Name matching is a case-insensitive substring match done locally. `status` and `in_stock_only` (`inventory_exists=true`) are sent to the API. `status` is validated against `BatchStatus`.

- [ ] **Step 1: Write failing tests.**
  - Client: `test_query_params_status` (`ListQueryParams(status="Fermenting").as_query_param_str()` contains `status=Fermenting`); `test_get_inventory_list_hops` (respx GET `/inventory/hops` returns one hop; result is a `HopList` with one item).
  - Server (mock client with three batches named `"IPA #1"`, `"ipa #2"`, `"Stout"`): `test_find_batches_by_name_case_insensitive` returns both IPA batches and not the stout; `test_find_batches_no_match` returns `"No batches found."`; `test_find_batches_invalid_status` returns `"Invalid request:"`; `test_find_batches_status_sent` (client called with params whose `status == "Fermenting"`); `test_find_recipes_by_name`; `test_list_inventory_in_stock_only` (params have `inventory_exists is True`); `test_list_inventory_name_filter`; `test_list_inventory_unknown_kind`.
  - Output lines use the existing formats for batches and recipes (ID, name, status/style). For inventory each item is one line: `ID | name | stock`.
- [ ] **Step 2: Run** `uv run pytest -k "find or list_inventory or query_params or inventory_list" -v`. Expected: FAIL.
- [ ] **Step 3: Implement** the parameter, the client method (reuse `_get_paginated_list`) and the three tools.
- [ ] **Step 4: Run** `uv run pytest -v`. Expected: all PASS.
- [ ] **Step 5: Commit** `feat: add find_batches, find_recipes and list_inventory`.

---

### Task 6: Recipe create and update

**Files:**
- Modify: `src/brewfather_mcp/validation.py`, `src/brewfather_mcp/api.py`, `src/brewfather_mcp/server.py`
- Test: `tests/test_validation.py`, `tests/test_brewfather_client.py`, `tests/test_mcp_server.py`

**Interfaces:**
- Produces in `validation.py`: `RECIPE_FIELDS: set[str]` and `validate_recipe_payload(data: dict[str, object], *, creating: bool) -> dict[str, object]`. Allowed top-level fields come from the Recipe Object in types.md, minus server-managed and calculated ones (`_`-prefixed, `createdAt`, `updatedAt`, `data`, totals, `og`, `fg`, `abv`, `ibu`, `color`, and the other computed values). Rules: `creating` requires a non-empty string `name`; `type` must be `Extract`, `Partial Mash` or `All Grain`; `batchSize` at least 0.5; `efficiency` from 35 to 100; `mashEfficiency` from 0 to 100; ingredient arrays must be lists of dicts; when not `creating`, an empty `fermentables`, `hops`, `miscs` or `yeasts` list raises `ValueError` (it would erase all of them; my call, the user can clear them in the app); `None` clears an optional top-level field.
- Produces in `api.py`: `BrewfatherClient.create_recipe(data: dict) -> str` (POST `recipes`) and `BrewfatherClient.update_recipe(id: str, data: dict) -> None` (PATCH `recipes/{id}`).
- Produces in `server.py`: tools `create_recipe(name: str, fields: dict | None = None) -> str` and `update_recipe(recipe_id: str, fields: dict) -> str`. Both descriptions must say: metric units, array fields replace the whole array, and calculated values (OG, IBU, color) may be empty until the recipe is opened in the Brewfather app.

- [ ] **Step 1: Write failing tests.**
  - Validation: `test_recipe_create_minimal` (`{"name": "Test"}` passes); `test_recipe_create_requires_name` (`{}` and `{"name": ""}` raise); `test_recipe_rejects_server_fields` (`_id`, `data`, `createdAt`, `og`); `test_recipe_rejects_bad_type`; `test_recipe_rejects_ranges` (`batchSize=0.1`, `efficiency=20`); `test_recipe_update_rejects_empty_ingredient_array` (`{"hops": []}` raises for `creating=False`, passes for non-empty); `test_recipe_update_clear_author` (`{"author": None}` passes).
  - Client: `test_create_recipe_post` and `test_update_recipe_patch` (respx; request JSON equals the data).
  - Server: `test_create_recipe` (client called with `{"name": "Test", "batchSize": 20.0}`; result contains the new ID), `test_create_recipe_invalid` (`"Invalid request:"`, client not called), `test_update_recipe` (client called with the fields), `test_update_recipe_invalid`.
- [ ] **Step 2: Run** `uv run pytest -k recipe -v`. Expected: FAIL for the new tests.
- [ ] **Step 3: Implement** the validator, the two client methods and the two tools.
- [ ] **Step 4: Run** `uv run pytest -v`. Expected: all PASS.
- [ ] **Step 5: Commit** `feat: add create_recipe and update_recipe tools`.

---

### Task 7: Live check script and docs

**Files:**
- Create: `scripts/live_check_writes.py`
- Modify: `README.md`, `CLAUDE.md`

- [ ] **Step 1: Create `scripts/live_check_writes.py`.** It reads credentials from `.env`, and creates one scratch recipe named `ZZ-MCP-SCRATCH <timestamp>` and one scratch hop with the same prefix, using the new client methods. It then: updates the recipe `notes` and `batchSize`; reads the recipe back and prints which computed fields (`og`, `ibu`, `color`) are empty; creates the hop with `inventory` 10, adjusts it by `-4`, reads it back and checks the value is 6; prints the two IDs and a reminder to delete them in the Brewfather app. It must take a `--yes` flag and refuse to run without it. It must not touch any other item.
- [ ] **Step 2: Update `README.md` and `CLAUDE.md`:** the tool list (new tools, removed `update_*_inventory` tools), the API key scope advice (read scopes for read-only use, `*.write` only for write tools, never grant `*.delete` scopes), the 500 calls per hour limit, and the fact that batches cannot be created through the API.
- [ ] **Step 3: Run** `uv run pytest -v`. Expected: all PASS.
- [ ] **Step 4: Commit** `docs: document new tools and add live write check script`.
- [ ] **Step 5 (needs user approval, writes to the real account):** run `uv run python scripts/live_check_writes.py --yes`, report the output, and ask the user to delete the two scratch items in the app.
