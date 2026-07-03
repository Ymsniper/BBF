"""Append-only result logging for --save.

Deliberately append rather than overwrite: this is a running discovery
log across possibly many invocations (survey pass, sweep, a later rerun
against a different LAP), not a single-run snapshot. Nothing here ever
truncates a file the caller pointed at.
"""
from datetime import datetime


def append_result(path, addr, name, source):
    """Append one 'timestamp<TAB>address<TAB>name<TAB>source' line to
    path, creating the file if it doesn't exist yet. `source` is a short
    tag ('survey' or 'sweep') recording how the UAP was known, since a
    later reader may care whether an address was ever actually paged."""
    ts = datetime.now().isoformat(timespec="seconds")
    resolved = name if name else "(no name response)"
    with open(path, "a") as f:
        f.write(f"{ts}\t{addr}\t{resolved}\t{source}\n")
