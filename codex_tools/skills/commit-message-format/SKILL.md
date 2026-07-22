---
name: commit-message-format
description: Format, rewrite, amend, or prepare git commit messages with the workspace commit-message formatter. Use when Codex drafts commit messages, rewrites a commit series, amends commits, cherry-picks with new messages, checks 72-column wrapping, or needs to add/normalize Signed-off-by trailers.
---

# Commit Message Format

Use the workspace formatter instead of hand-wrapping commit-message bodies.
The formatter reads the target repository's `git config user.name` and
`user.email`, wraps body paragraphs to 72 columns, keeps trailers in a final
trailer block, and adds the matching `Signed-off-by` line.

## Workflow

1. Write the intended message as normal prose in a draft file or pipe it on
   stdin. Keep the first line as the commit subject.
2. Run from the workspace root:

   ```sh
   python -m codex_tools.commit_msg --repo path/to/repo draft-message.txt \
     --output formatted-message.txt --check
   ```

3. Use the formatted file for the git operation:

   ```sh
   git -C path/to/repo commit -F formatted-message.txt
   git -C path/to/repo commit --amend -F formatted-message.txt
   ```

4. For history rewrites, prefer `cherry-pick --no-commit` followed by
   `commit -F formatted-message.txt` so each replayed commit receives the
   checked message.

## Checks

- Re-run the formatter whenever message text changes.
- Run this final check on the resulting series:

  ```sh
  git -C path/to/repo log --format=%B --reverse base..HEAD |
    awk 'length($0)>72 {print NR ":" length($0) ":" $0}'
  ```

- If the subject itself is longer than 72 columns, rewrite the subject
  manually. Do not split a git subject across multiple lines.
