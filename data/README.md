# Local data directories

- `runtime/` is created and populated at runtime with `embodied_alife.db` and SQLite sidecar files.
- `agent_memory/` is the sandboxed Markdown vault. Its category folders are committed empty through `.gitkeep` files.

The release ZIP intentionally contains no generated database, snapshots, model responses, secrets, or prewritten agent memories.
