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


def select_target(needs_bruteforce, ready_to_use, prefix):
    """Show survey results and let the user pick a sweep target.
    Returns the chosen LAP string, or None if the user skipped."""
    if ready_to_use:
        print("\nReady to use (UAP already resolved -- no brute-force needed):")
        for uap, lap in ready_to_use:
            print(f"  [ready] {prefix}:{uap}:{lap}  "
                  f"(NAP assumed from --prefix; UAP+LAP confirmed by ubertooth)")
        print(f"  -> test one directly with: bbf {ready_to_use[0][1]} --only {ready_to_use[0][0]}")

    if not needs_bruteforce:
        print("\nNothing left to brute-force." if ready_to_use else "\nNo devices detected.")
        return None

    print("\nCandidates needing UAP brute-force:")
    for i, lap in enumerate(needs_bruteforce, 1):
        print(f"  {i}) ??:{lap}")

    while True:
        choice = input("\nSelect a target number, or press Enter to skip: ").strip()
        if not choice:
            return None
        if choice.isdigit() and 1 <= int(choice) <= len(needs_bruteforce):
            return needs_bruteforce[int(choice) - 1]
        print("Invalid selection.")
