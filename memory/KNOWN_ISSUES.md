# KNOWN_ISSUES.md

Bugs, limitations, and deliberately-deferred rough edges. Not a task tracker for planned future
work — that's ROADMAP.md. This is specifically for "this is broken or limited, here's the
current status," so nobody re-discovers the same problem from scratch in a future session.

Entry format:
```
## [STATUS] Short title
**Discovered:** date
**Severity:** low / medium / high
**Description:** what's actually wrong or limited.
**Workaround / status:** what to do about it now, or why it's intentionally left as-is.
```
Status tags: `[OPEN]` not fixed, `[WORKAROUND]` has a workaround in place, `[WONTFIX-V1]`
deliberately deferred past v1, `[RESOLVED]` fixed (keep the entry for history, don't delete it —
move resolved entries to the bottom under a "Resolved" heading rather than removing them).

---

*(No issues logged yet — this is the initial scaffold. Add entries as they come up during
implementation. Don't leave this section empty for long; the first real session should
populate at least the known structural limitations of v1, e.g. no cross-document comparison,
no table extraction until v2, once implementation starts surfacing them concretely.)*
