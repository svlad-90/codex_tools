# C++ code workflow

These rules apply to C and C++ code under the workspace root.

Assembly files follow the local kernel style: use a tab between the
instruction mnemonic and operands (for example `mov	x1, x0`), matching
the surrounding `.S` files.

When explaining C/C++ or assembly changes in reviews, diagrams, commit
messages, or task notes, treat low-level systems concepts as teaching moments.
Describe the plain-language purpose first, then map it to the concrete symbol
or API. This is especially important for memory layout, bit manipulation,
cache maintenance, MMIO, interrupts, bootloader flows, Xen/Zephyr/U-Boot
sequences, and hypervisor interfaces.

1. Use `codex_tools/cpp_code_map` whenever C or C++ code is inspected,
   changed, reviewed, or validated.
2. Run commands from the workspace root with:

   ```sh
   python -m codex_tools.cpp_code_map <command> ...
   ```

3. Prefer passing the build directory or compile database explicitly:

   ```sh
   python -m codex_tools.cpp_code_map map path/to/file.cpp \
     --compile-db path/to/build
   ```

4. Run `cpp_code_map` in the project's real build environment. If the project
   is built in Docker or another container, run the tool in that same
   environment so compiler paths, generated headers, sysroots, and module
   paths match the build. A host-side copy of `compile_commands.json` with
   container paths is not a complete substitute for the build environment.

5. For a task that is mainly about C or C++ code, establish a working
   `cpp_code_map` context before continuing with implementation, review, or
   validation work. This means `map` must succeed for at least one relevant
   translation unit using the real build directory or compile database needed
   by the task. If that context is missing, generate or locate the proper
   `compile_commands.json` first. Do not continue by treating repeated
   `cpp_code_map` failures as a harmless warning.

6. Before reading or changing an existing C or C++ source file, inspect its
   structure:

   ```sh
   python -m codex_tools.cpp_code_map map path/to/file.cpp \
     --compile-db path/to/build
   ```

7. Before changing an existing class, function, method, or C function, resolve
   its exact span and current hash:

   ```sh
   python -m codex_tools.cpp_code_map symbol-get path/to/file.cpp \
     --symbol Qualified::Name --compile-db path/to/build
   ```

8. After every C or C++ edit, validate every changed C or C++ source file:

   ```sh
   python -m codex_tools.cpp_code_map parse-check path/to/file.cpp \
     --compile-db path/to/build
   ```

9. If no `compile_commands.json` is available, generate one first. For CMake
   projects, prefer:

   ```sh
   cmake -S . -B build -DCMAKE_EXPORT_COMPILE_COMMANDS=ON
   ```

10. If `cpp_code_map` cannot process a file because libclang or a compile
   database is missing, report the limitation explicitly and stop C/C++
   implementation or review work until the tool context is fixed. Use a
   fallback only for non-C/C++ surrounding files or when the user explicitly
   asks to bypass this rule after the limitation has been reported.
