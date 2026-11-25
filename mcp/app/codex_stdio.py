"""Scoped Homelable MCP for a trusted stdio transport such as SSH."""

import asyncio
from copy import deepcopy
import json

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import TextContent

from .backend_client import backend, safe_id
from .tools import TOOLS, _dispatch


READS = frozenset({
    "list_designs", "list_node_summaries", "list_edges", "get_canvas", "get_node",
    "list_zones", "list_inventory", "list_documentation", "read_document",
    "list_racks", "get_rack",
})
CANVAS_WRITES = frozenset({
    "create_node", "update_node", "create_edge", "update_edge", "create_zone",
    "add_to_zone", "remove_from_zone",
})
WRITES = CANVAS_WRITES | {
    "create_design", "create_device", "update_device", "create_document", "update_document",
}
DESIGN = {"type": "string", "minLength": 1, "description": "Exact network canvas ID from list_designs."}
EXCLUDED_FIELDS = {
    "create_node": {"check_method", "check_target", "status"},
    "update_node": {"check_method", "check_target", "status", "parent_id"},
    "create_device": {"check_method", "check_target", "discovery_source"},
    "update_device": {"check_method", "check_target", "rack_faceplate_id", "rack_ports",
                      "rack_u_height", "rack_col_span", "rack_color"},
}


def scoped_catalog(allow_writes: bool):
    """Reuse the upstream schemas and select a deliberately small write surface."""
    allowed = READS | (WRITES if allow_writes else set())
    catalog = {}
    for tool in TOOLS:
        if tool.name not in allowed:
            continue
        schema = deepcopy(tool.inputSchema)
        properties = schema.setdefault("properties", {})
        schema["additionalProperties"] = False
        for field in EXCLUDED_FIELDS.get(tool.name, ()):
            properties.pop(field, None)
        if tool.name in CANVAS_WRITES:
            properties["design_id"] = DESIGN.copy()
            required = schema.setdefault("required", [])
            if "design_id" not in required:
                required.append("design_id")
        if tool.name in {"add_to_zone", "remove_from_zone"}:
            # Upstream applies one PATCH per node, so expose single-node changes.
            properties["node_ids"].update(minItems=1, maxItems=1)
        catalog[tool.name] = tool.model_copy(update={"inputSchema": schema})
    if set(catalog) != allowed:
        raise RuntimeError("The Homelable tool catalog is incompatible with this adapter")
    return catalog


async def canvas_arguments(name: str, arguments: dict) -> dict:
    design_id = safe_id(arguments["design_id"], field="design id")
    designs = await backend.get("/api/v1/designs")
    if not any(d["id"] == design_id and d["design_type"] == "network" for d in designs):
        raise ValueError("Choose an existing network canvas from list_designs")

    node_ids = []
    if name == "update_node":
        node_ids.append(arguments["id"])
    if name == "create_node" and arguments.get("parent_id") is not None:
        node_ids.append(arguments["parent_id"])
    if name == "create_edge":
        if arguments["source"] == arguments["target"]:
            raise ValueError("Choose two different nodes")
        node_ids.extend((arguments["source"], arguments["target"]))
    if name in {"add_to_zone", "remove_from_zone"}:
        node_ids.extend(arguments["node_ids"])
    if name == "add_to_zone":
        node_ids.append(arguments["zone_id"])

    if node_ids or name == "update_edge":
        canvas = await backend.get(f"/api/v1/canvas?design_id={design_id}")
        members = {node["id"] for node in canvas["nodes"] if node.get("design_id") == design_id}
        if any(safe_id(node_id, field="node id") not in members for node_id in node_ids):
            raise ValueError("The selected node does not belong to this canvas")
        if name == "update_edge" and not any(
            edge["id"] == arguments["id"] and edge.get("design_id") == design_id
            for edge in canvas["edges"]
        ):
            raise ValueError("The selected link does not belong to this canvas")

    if name not in {"create_node", "create_edge", "create_zone"}:
        return {k: v for k, v in arguments.items() if k != "design_id"}
    return arguments


def create_server(*, allow_writes: bool = False) -> Server:
    catalog = scoped_catalog(allow_writes)
    server = Server("homelable")
    write_lock = asyncio.Lock()

    @server.list_tools()
    async def list_tools():
        return list(catalog.values())

    @server.call_tool()
    async def call_tool(name: str, arguments: dict):
        if name not in catalog:
            raise ValueError("This tool is unavailable on the scoped Homelable server")
        arguments = dict(arguments)
        if name in WRITES:
            async with write_lock:
                if name in CANVAS_WRITES:
                    arguments = await canvas_arguments(name, arguments)
                result = await _dispatch(name, arguments)
        else:
            result = await _dispatch(name, arguments)
        return [TextContent(type="text", text=json.dumps(result, ensure_ascii=False))]

    return server


async def serve(*, allow_writes: bool = False):
    server = create_server(allow_writes=allow_writes)
    await backend.start()
    try:
        async with stdio_server() as (reader, writer):
            await server.run(reader, writer, server.create_initialization_options())
    finally:
        await backend.stop()


def main():
    from argparse import ArgumentParser

    parser = ArgumentParser(description=__doc__)
    parser.add_argument("--allow-writes", action="store_true")
    args = parser.parse_args()
    asyncio.run(serve(allow_writes=args.allow_writes))


if __name__ == "__main__":
    main()
