# backend/tests

- `_supabase_mock.py` — shared Supabase chained-mock helpers; import `fluent` and `result` instead of writing local copies
- `fluent(return_data)` returns a MagicMock where every Supabase chain method (`.table`, `.select`, `.eq`, `.insert`, `.upsert`, `.rpc`, etc.) returns itself; `.execute()` returns `result(return_data)`
- `result(data)` wraps data in a `SimpleNamespace` with `.data` and `.count` fields, matching the real Supabase response shape
- Add new chain methods to `fluent()` in `_supabase_mock.py` rather than creating file-local helpers
