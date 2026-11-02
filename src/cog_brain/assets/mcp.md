# MCP compatibility

When the local runtime is unavailable but the client has cog-brain MCP tools,
use the same vault conventions through those tools. Discover exact schemas.

| Local API | MCP tool |
| --- | --- |
| search | semantic_search |
| read | read_note |
| create | write_note |
| update | update_note |
| list_notes / outline / find_related / backlinks | Same names |

Use vault_status for index health and index_now for an explicit refresh. Report
partial failures; do not repeatedly reindex malformed notes. Existing read/update
paths come from results; a new note may use a new valid root filename.

Capture into daily and the handoff helper require the local runtime. Do not invent
MCP tools for them. Durable knowledge can use write_note/update_note with the
same description, link and retraction rules. Full-body updates should pass the
expected_hash revision when available; read_note returns text, so obtain the
revision through the local API before replacing a body. Prefer append for a
small addition through MCP. Preserve warnings on retracted notes.
