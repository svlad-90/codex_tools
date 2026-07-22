# Recurring findings

This file records workspace-level findings only when the user explicitly asks
to add another case. Do not add routine bugs, one-off task notes, or guesses
here without that request.

Before starting diagnostics in this workspace, scan this file for known failure
patterns that have already consumed significant time. Treat each item as a
checklist prompt, not as proof that the same root cause applies.

## Xen/Zephyr control ABI versions

When changing Xen versions, compare Zephyr's Xen control ABI config with the
matching Xen public headers before debugging higher-level runtime behavior.

Check at least:

- Zephyr `CONFIG_XEN_DOMCTL_INTERFACE_VERSION` matches Xen
  `XEN_DOMCTL_INTERFACE_VERSION`.
- Zephyr `CONFIG_XEN_SYSCTL_INTERFACE_VERSION` matches Xen
  `XEN_SYSCTL_INTERFACE_VERSION`.
- The Zephyr public `domctl.h` / `sysctl.h` struct layout is compatible with
  the Xen version being tested.

Known failure shape:

- XenStore client appears to connect, but first request hangs.
- Dom0 never actually starts the XenStore server because early domctl/sysctl
  calls fail.
- Xen may return `-EACCES` for mismatched control ABI versions.

## Zephyr XenStore server `XS_RM` missing-node errors

When testing remove/delete behavior, verify the server commit being tested
before choosing the expected missing-node errno.

Historical failure shape:

- Older Zephyr XenStore server code called `key_to_entry_check_perm()` from
  `xss_do_rm()`.
- That helper returned one `NULL` result both when the node was missing and
  when write permission was missing.
- `xss_do_rm()` converted that `NULL` to `-EINVAL`, so a missing remove target
  did not produce a clear missing-node error.

Practical checklist:

- In the current task series, commit `xenstore-srv: fix remove request
  handling` splits lookup from permission checking.
- For that current series, expect `xs_client_rm(missing_child)` to return
  `-ENOENT`.
- If an old build returns `-EINVAL`, check whether it contains the split
  lookup/permission fix in `xss_do_rm()`.

## Zephyr XenStore server transaction messages

Do not expose or test client transaction helpers as real transactions until the
server implements real transaction semantics.

Current server behavior to remember:

- The server has transaction message handling surface.
- It does not provide real staging, commit, abort, or rollback behavior for
  store mutations.

Practical checklist:

- Keep public client transaction helpers out of the API while validating
  against this server.
- Treat transaction support as a separate server feature, not as a client-side
  wrapper around ordinary requests.
