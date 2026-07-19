# C++ code workflow

These rules apply to C and C++ code under the workspace root.

1. Use `codex_tools/cpp_code_map` whenever C++ code is inspected, changed,
   reviewed, or validated.
2. Run commands from the workspace root with:

   ```sh
   python -m codex_tools.cpp_code_map <command> ...
   ```

3. Prefer passing the build directory or compile database explicitly:

   ```sh
   python -m codex_tools.cpp_code_map map path/to/file.cpp \
     --compile-db path/to/build
   ```

4. Before reading or changing an existing C++ file, inspect its structure:

   ```sh
   python -m codex_tools.cpp_code_map map path/to/file.cpp \
     --compile-db path/to/build
   ```

5. Before changing an existing class, function, or method, resolve its exact
   span and current hash:

   ```sh
   python -m codex_tools.cpp_code_map symbol-get path/to/file.cpp \
     --symbol Qualified::Name --compile-db path/to/build
   ```

6. After every C++ edit, validate every changed C++ file:

   ```sh
   python -m codex_tools.cpp_code_map parse-check path/to/file.cpp \
     --compile-db path/to/build
   ```

7. If no `compile_commands.json` is available, generate one first. For CMake
   projects, prefer:

   ```sh
   cmake -S . -B build -DCMAKE_EXPORT_COMPILE_COMMANDS=ON
   ```

8. If `cpp_code_map` cannot process a file because libclang or a compile
   database is missing, report the limitation explicitly and use the narrowest
   safe fallback.
