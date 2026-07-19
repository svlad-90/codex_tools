# diff_report

Generate a GitHub-style HTML diff report with optional file-level and inline
review comments.

## Usage

```sh
python -m codex_tools.diff_report \
  --repo path/to/repo \
  --range HEAD^..HEAD \
  --comments comments.json \
  --output review.html
```

You can also render an already prepared unified git diff:

```sh
python -m codex_tools.diff_report \
  --diff-file change.patch \
  --comments comments.json \
  --output review.html
```

## Comments JSON

```json
{
  "summary": "Optional plain-text summary shown above the diff.",
  "files": {
    "path/to/file.py": "File-level review note shown under the file header."
  },
  "inline": [
    {
      "file": "path/to/file.py",
      "line": 42,
      "title": "Review comment",
      "body": "Inline review note shown under the target new-file line."
    }
  ]
}
```

Inline comments are attached to new-file line numbers in the rendered diff.
