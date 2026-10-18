"""Exercise the write tools against the real Brewfather account.

Creates ONE scratch recipe and ONE scratch hop (names start with ZZ-MCP-SCRATCH) and
touches nothing else. The server has no delete tools, so remove both items in the
Brewfather app afterwards.

Usage: uv run python scripts/live_check_writes.py --yes
Needs BREWFATHER_API_USER_ID and BREWFATHER_API_KEY (from .env) with the recipes.write
and inventory.write scopes.
"""

import argparse
import asyncio
import json
import sys
from datetime import datetime

from dotenv import load_dotenv

from brewfather_mcp.api import BrewfatherClient, created_id
from brewfather_mcp.types import InventoryCategory
from brewfather_mcp.validation import validate_inventory_fields, validate_recipe_payload


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--yes", action="store_true", help="confirm writing scratch items to the account"
    )
    if not parser.parse_args().yes:
        print("Refusing to write to the real account without --yes.", file=sys.stderr)
        return 2

    load_dotenv()
    client = BrewfatherClient()
    name = f"ZZ-MCP-SCRATCH {datetime.now():%Y-%m-%d %H:%M:%S}"

    print("== Recipe ==")
    recipe = validate_recipe_payload(
        {"name": name, "type": "All Grain", "batchSize": 20.0}, creating=True
    )
    response = await client.create_recipe(recipe)
    recipe_id = created_id(response)
    if not recipe_id:
        print(f"create_recipe succeeded but no ID found in the response: {response!r}")
        return 1
    print(f"created recipe {recipe_id}")

    update = validate_recipe_payload(
        {"notes": "scratch recipe created by live_check_writes.py", "batchSize": 23.0},
        creating=False,
    )
    await client.update_recipe(recipe_id, update)
    detail = await client.get_recipe_detail(recipe_id)
    print(f"notes after update: {getattr(detail, 'notes', None)!r}")
    raw = json.loads(
        await client._make_request(client._build_url("recipes", id=recipe_id))
    )
    for field in ("og", "ibu", "color"):
        print(f"  calculated {field}: {raw.get(field)!r}")

    print("== Inventory (hop) ==")
    hop = validate_inventory_fields(
        InventoryCategory.HOPS, {"name": name, "alpha": 5.0, "type": "Pellet"}
    )
    response = await client.create_inventory_item(
        InventoryCategory.HOPS, {**hop, "inventory": 10}
    )
    hop_id = created_id(response)
    if not hop_id:
        print(f"create_inventory_item succeeded but no ID found in the response: {response!r}")
        return 1
    print(f"created hop {hop_id} with stock 10")
    await client.update_inventory(InventoryCategory.HOPS, hop_id, {"inventory_adjust": -4})
    stock = (await client.get_hop_detail(hop_id)).inventory
    print(f"stock after adjust -4: {stock} (expected 6)")

    print("\nDone. Delete these two items in the Brewfather app:")
    print(f"  recipe {recipe_id}  /  hop {hop_id}  (both named {name!r})")
    return 0 if stock == 6 else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
