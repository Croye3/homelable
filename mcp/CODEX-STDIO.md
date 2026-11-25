# Scoped Homelable MCP over stdio

Run from `mcp/` with the MCP dependencies installed:

```bash
python -m app.codex_stdio
```

Set `BACKEND_URL` to your Homelable API and provide `MCP_SERVICE_KEY` through the process's credential setup. The stdio process does not open a listener. An SSH deployment should invoke a fixed launcher on a trusted host, load the backend credential on that host, and keep it out of the client configuration.

The default catalog reads canvases, nodes, links, zones, inventory, racks, and documents. Add `--allow-writes` to let the client opt in to writes:

- Create designs, nodes, links, and zones.
- Update nodes and links, and move one node into or out of a zone per call.
- Create and update manually maintained inventory records and documents.

Canvas mutations require the exact network design ID. The adapter checks node and link membership before dispatching a mutation. Its catalog omits deletion, scan execution and scan settings, monitoring probe settings, and rack rewrites. The existing HTTP MCP transport and its catalog are independent of this entry point.

For Codex, configure a stdio command that launches this process and use `default_tools_approval_mode = "writes"` to prompt before tools marked as writes. The transport must be trusted because the stdio process relies on caller authentication outside MCP, such as SSH. Tool annotations inform the client; the server separately enforces its catalog and input schemas.
