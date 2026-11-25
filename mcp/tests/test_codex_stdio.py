import json
from unittest.mock import AsyncMock

from mcp.types import CallToolRequest, ListToolsRequest
import pytest

from app import codex_stdio, tools


@pytest.fixture
def calls(monkeypatch):
    api = AsyncMock()
    api.get.side_effect = [
        [{"id": "master", "design_type": "network"}, {"id": "rack", "design_type": "rack"}],
        {"nodes": [{"id": "here", "design_id": "master"}, {"id": "other", "design_id": "test"}], "edges": []},
    ]
    api.post.return_value = {"id": "new"}
    api.patch.return_value = {"id": "here", "label": "Renamed"}
    monkeypatch.setattr(codex_stdio, "backend", api)
    monkeypatch.setattr(tools, "backend", api)
    return api


async def invoke(server, name, arguments):
    request = CallToolRequest(method="tools/call", params={"name": name, "arguments": arguments})
    return (await server.request_handlers[CallToolRequest](request)).root


@pytest.mark.anyio
async def test_catalog_and_direct_call_exclude_unapproved_tools(calls):
    readonly = codex_stdio.create_server()
    writable = codex_stdio.create_server(allow_writes=True)
    request = ListToolsRequest(method="tools/list")
    public = (await writable.request_handlers[ListToolsRequest](request)).root.tools
    assert {tool.name for tool in public} == codex_stdio.READS | codex_stdio.WRITES
    for server, name in ((readonly, "create_node"), (writable, "trigger_scan"), (writable, "delete_design")):
        assert (await invoke(server, name, {})).isError
    assert calls.mock_calls == []


@pytest.mark.anyio
async def test_create_node_requires_explicit_canvas_and_rejects_extra_fields(calls):
    server = codex_stdio.create_server(allow_writes=True)
    base = {"type": "server", "label": "Pi04"}
    assert (await invoke(server, "create_node", base)).isError
    assert (await invoke(server, "create_node", {**base, "design_id": "master", "check_target": "test"})).isError
    assert calls.mock_calls == []
    result = await invoke(server, "create_node", {**base, "design_id": "master"})
    assert not result.isError
    assert json.loads(result.content[0].text) == {"id": "new"}
    calls.post.assert_awaited_once_with("/api/v1/nodes", {**base, "design_id": "master"})


@pytest.mark.anyio
async def test_update_node_checks_canvas_but_does_not_send_scope_as_edit(calls):
    server = codex_stdio.create_server(allow_writes=True)
    result = await invoke(server, "update_node", {"id": "here", "design_id": "master", "label": "Renamed"})
    assert not result.isError
    calls.patch.assert_awaited_once_with("/api/v1/nodes/here", {"label": "Renamed"})


@pytest.mark.anyio
async def test_cross_canvas_edge_is_rejected_without_post(calls):
    result = await invoke(codex_stdio.create_server(allow_writes=True), "create_edge",
                          {"source": "here", "target": "other", "design_id": "master"})
    assert result.isError
    calls.post.assert_not_awaited()


@pytest.mark.anyio
async def test_doc_update_reuses_upstream_route(monkeypatch):
    api = AsyncMock()
    api.patch.return_value = {"id": "notes", "body": "New notes"}
    monkeypatch.setattr("app.documents.backend", api)
    result = await invoke(codex_stdio.create_server(allow_writes=True), "update_document",
                          {"id": "notes", "body": "New notes"})
    assert not result.isError
    api.patch.assert_awaited_once_with("/api/v1/documents/notes", {"body": "New notes", "revision_reason": "mcp"})
