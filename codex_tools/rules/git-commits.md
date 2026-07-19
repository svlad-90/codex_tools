# Git commit workflow

These rules apply to every repository under the workspace root.

1. Unless the user explicitly asks for a different format, every commit
   message must wrap lines at 72 characters.
2. Every commit message must include a `Signed-off-by` trailer matching the
   repository author's local Git identity. Prefer `git commit -s` when it fits.

   ```text
   Signed-off-by: Name <email@example.com>
   ```

3. Paragraphs in the commit body are allowed. Do not add gratuitous blank
   lines that create empty paragraphs.
4. Put trailers in a separate trailer block: add one blank line before
   `Signed-off-by`.
