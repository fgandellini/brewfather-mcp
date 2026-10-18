# Brewfather MCP Server

A Model Context Protocol (MCP) server that integrates with the Brewfather API to provide brewing inventory management and recipe analysis capabilities. This server allows MCP clients like Claude to interact with your Brewfather brewing data.

## Features

- **Inventory Management**: List, search, create, edit and adjust the stock of fermentables, hops, yeasts, and miscellaneous brewing supplies
- **Recipes**: Read detailed recipe information, search recipes, create new recipes and update existing ones
- **Batch Tracking**: Monitor brewing batches, update or clear measurements, and track progress
- **Brewing Insights**: Get brewing process guidance and sensor readings
- **Dockerized HTTP Deployment**: Run the server as a container exposing a secured Streamable HTTP endpoint

## Prerequisites

- Python 3.13 or later
- Brewfather account with API access
- Brewfather API credentials (User ID and API Key)

## Getting Your Brewfather API Credentials

1. Log in to your Brewfather account
2. Navigate to Settings → API
3. Generate or copy your API User ID and API Key
4. Keep these credentials secure - you'll need them for configuration

### API key scopes

When you generate the key you choose its scopes. Grant only what you need:

| Use | Scopes |
| --- | --- |
| Read-only (all list/get/find tools) | `recipes.read`, `batches.read`, `inventory.read` |
| Change data | add `recipes.write`, `batches.write`, `inventory.write` as needed |
| Delete | **never grant** `*.delete` - no tool in this server deletes anything |

Brewfather allows 500 API calls per hour per key. When the limit is reached, the tools return an error that includes the retry delay. Batches cannot be created through the API: create the batch from a recipe in the Brewfather app, then use this server to update it.

## Installation

### Option 1: Direct Installation with uvx (Recommended)

The easiest way to use this MCP server is with `uvx`, directly from the GitHub repository:

```bash
# Set your credentials as environment variables
export BREWFATHER_API_USER_ID="your-api-user-id"
export BREWFATHER_API_KEY="your-api-key"

# Run the server
uvx --from git+https://github.com/mindsocket/brewfather-mcp.git brewfather-mcp
```

For debugging:
```bash
uvx --from git+https://github.com/mindsocket/brewfather-mcp.git brewfather-mcp --debug
```

### Option 2: Local Development Installation

1. Clone this repository
2. Install dependencies:
```bash
uv sync
```

## Configuration

### Claude Desktop Configuration

#### Option 1: Using uvx (Recommended)

To use this server with Claude Desktop via uvx, add the following to your Claude Desktop configuration file:

**Location of config file:**
- macOS: `~/Library/Application Support/Claude/claude_desktop_config.json`
- Windows: `%APPDATA%\\Claude\\claude_desktop_config.json`

**Configuration:**
```json
{
  "mcpServers": {
    "brewfather": {
      "command": "uvx",
      "args": [
        "--from",
        "git+https://github.com/mindsocket/brewfather-mcp.git",
        "brewfather-mcp"
      ],
      "env": {
        "BREWFATHER_API_USER_ID": "your-api-user-id",
        "BREWFATHER_API_KEY": "your-api-key"
      }
    }
  }
}
```

#### Option 2: Using Local Installation

To use this server with Claude Desktop from a local clone, use the same config file location as above with this configuration:
```json
{
  "mcpServers": {
    "brewfather": {
      "command": "uv",
      "args": [
        "run",
        "--with",
        "mcp[cli]",
        "mcp",
        "run",
        "/absolute/path/to/brewfather-mcp/src/main.py"
      ],
      "cwd": "/absolute/path/to/brewfather-mcp",
      "env": {
        "BREWFATHER_API_USER_ID": "your-api-user-id",
        "BREWFATHER_API_KEY": "your-api-key"
      }
    }
  }
}
```

Replace:
- `/absolute/path/to/brewfather-mcp` with the full path to your cloned repository
- `your-api-user-id` with your Brewfather API User ID
- `your-api-key` with your Brewfather API Key

You may also need to provide the full path to the uv command.

#### Other MCP Clients

For other MCP clients that support stdio transport, use:
- **Command**: `uv run --with mcp[cli] mcp run src/main.py`
- **Working Directory**: Path to this repository
- **Environment Variables**: `BREWFATHER_API_USER_ID` and `BREWFATHER_API_KEY`

### For Local Development & Testing

When developing or testing the server locally, there is the option of providing credentials via a `.env` file instead:
```bash
cp .env.example .env
# Edit .env with your Brewfather API credentials
```

## Available Tools

The server provides the following MCP tools:

### Inventory Management
- `list_fermentables` - List all fermentables (malts, adjuncts, grains)
- `get_fermentable_detail(identifier)` - Get detailed fermentable information
- `list_hops` - List all hops with properties like alpha acids
- `get_hop_detail(identifier)` - Get detailed hop information
- `list_yeasts` - List all yeasts with attenuation and type
- `get_yeast_detail(identifier)` - Get detailed yeast information
- `list_misc_items` - List miscellaneous brewing supplies
- `get_misc_detail(item_id)` - Get detailed misc item information
- `inventory_summary` - Get comprehensive inventory overview
- `list_inventory(kind, name?, in_stock_only?)` - Compact list of one kind (`fermentables`, `hops`, `miscs`, `yeasts`), filtered by name or by stock

### Inventory Updates
- `set_inventory(kind, item_id, amount? | adjust?)` - Set the stock to a new total (`amount`) or add/subtract a quantity (`adjust`)
- `create_inventory_item(kind, name, fields?, amount?)` - Create an inventory item, optionally with starting stock
- `update_inventory_item(kind, item_id, fields)` - Edit item properties (not stock). Unknown fields and invalid values are rejected before anything is sent

### Recipe Management
- `list_recipes` - List all recipes
- `find_recipes(name?)` - Search recipes by name
- `get_recipe_detail(recipe_id)` - Get detailed recipe information
- `create_recipe(name, fields?)` - Create a recipe (metric units). Calculated values such as OG, IBU and color are computed by Brewfather and may be empty until the recipe is opened in the app
- `update_recipe(recipe_id, fields)` - Update top-level recipe fields. An ingredient list replaces the whole list, and empty lists are refused

### Batch Management
- `list_batches` - List all brewing batches
- `find_batches(name?, status?)` - Search batches by name and/or status
- `get_batch_detail(batch_id)` - Get detailed batch information
- `update_batch(batch_id, ..., clear_fields?)` - Update batch status and measured values (validated); `clear_fields` clears measured values
- `get_batch_brewtracker(batch_id)` - Get brewing process guidance
- `get_batch_last_reading(batch_id)` - Get latest sensor readings
- `get_batch_readings_summary(batch_id)` - Get sensor readings summary

## Development

### Running Tests
```bash
uv run pytest
```

### Checking the write tools against the real API

`scripts/live_check_writes.py` creates one scratch recipe and one scratch hop (both named `ZZ-MCP-SCRATCH ...`) in your account and exercises the write tools on them. The server cannot delete, so remove the two items in the Brewfather app afterwards.
```bash
uv run python scripts/live_check_writes.py --yes
```

### Testing the Server Locally

[mcptools](https://github.com/f/mcptools) can be handy for local testing:

```bash
# List available tools
mcpt tools uv run --with 'mcp[cli]' mcp run src/main.py

# Call a specific tool
mcpt call list_inventory_categories uv run --with 'mcp[cli]' mcp run src/main.py
```

### HTTP Server (for cloud/remote deployment)

`src/http_runner.py` serves the MCP server over **Streamable HTTP** (the modern MCP transport that replaced SSE) rather than stdio, so it can be reached over the network by remote clients.

```bash
PYTHONPATH=src uv run python src/http_runner.py --port 8000
```

By default the server accepts unauthenticated requests from `localhost`/`127.0.0.1` only. When exposing it beyond your own machine, set:

- `MCP_AUTH_TOKEN` – requires every request to send `Authorization: Bearer <token>`. Without this, the server logs a warning and runs open. Generate a token with:
  ```bash
  python3 -c "import secrets; print(secrets.token_urlsafe(32))"
  ```
- `ALLOWED_HOSTS` – comma-separated list of `Host` header values the server will accept (DNS-rebinding protection), e.g. `ALLOWED_HOSTS=mcp.example.com`.

Both can also be passed as CLI flags (`--auth-token`, `--allowed-host`, repeatable).

Connect to it with an MCP client at `http://<host>:<port>/mcp`, sending the bearer token as an `Authorization` header if you set one.

## Docker Deployment

The included `Dockerfile` and `docker-compose.yml` package the HTTP server for easy self-hosting.

```bash
cp .env.example .env
# Edit .env: set BREWFATHER_API_USER_ID, BREWFATHER_API_KEY, and MCP_AUTH_TOKEN

docker compose up -d --build
```

This builds the image, installs dependencies with `uv`, and runs `src/http_runner.py` on port 8000 inside the container (mapped to `8010` on the host by default — adjust in `docker-compose.yml` as needed). Credentials and server options (`BREWFATHER_API_USER_ID`, `BREWFATHER_API_KEY`, `MCP_AUTH_TOKEN`, `ALLOWED_HOSTS`) are read from the `.env` file via `env_file`.

Point your MCP client at `http://<docker-host>:8010/mcp` with the `MCP_AUTH_TOKEN` value as a bearer token.

## Troubleshooting

### Common Issues

1. **Import errors**: Make sure you've run `uv sync` to install all dependencies

2. **API authentication errors**: 
   - For MCP clients: Check that credentials are correctly set in your client configuration 
   - For local development: Ensure your `.env` file exists with valid credentials
   - Verify your Brewfather API credentials are correct and have the necessary permissions

3. **Rate limit errors**: Brewfather allows 500 calls per hour per API key. The error message includes the delay to wait. The search tools read up to 10 pages (500 items) of a list, which can cost up to 10 calls each, and they warn when a list was cut at 500 items; prefer them over repeated list calls

4. **Connection timeouts**: Check your internet connection and Brewfather API status

5. **Path issues in Claude Desktop**: Ensure you're using absolute paths in the configuration file

### Debug Mode

Enable debug mode to save API responses into a debug folder for troubleshooting:
```bash
BREWFATHER_MCP_DEBUG=1 mcpt call get_batch_detail --params '{"batch_id": "your-batch-id"}' uv run --with 'mcp[cli]' mcp run src/main.py
```
