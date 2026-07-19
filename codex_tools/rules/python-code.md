# Python code workflow

These rules apply to all Python code under the workspace root.

1. Use `codex_tools/code_map` whenever Python code is inspected, changed,
   reviewed, or validated.
2. Run commands from the workspace root with:

   ```sh
   python -m codex_tools.code_map <command> ...
   ```

3. Before reading or changing an existing Python file, inspect its structure:

   ```sh
   python -m codex_tools.code_map map path/to/file.py
   ```

4. Before changing an existing class, function, or method, resolve its exact
   span and current hash:

   ```sh
   python -m codex_tools.code_map symbol-get path/to/file.py \
     --symbol QualifiedName
   ```

5. Prefer the guarded symbol and import operations exposed by `code_map` when
   they fit the change. If another editing mechanism is required, still use the
   map and symbol snapshot to scope the edit.
6. After every Python edit, validate every changed Python file:

   ```sh
   python -m codex_tools.code_map parse-check path/to/file.py
   ```

7. Re-run `map` when a change alters classes, functions, methods, or their
   nesting, and use the relevant audit or diagram command for architectural
   changes.
8. If `code_map` cannot process a file, report the limitation explicitly and
   use the narrowest safe fallback.

Run `python -m codex_tools.code_map help` for the compact command reference.
