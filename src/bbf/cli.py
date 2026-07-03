"""Top-level orchestration: ties the optional ubertooth survey to the
l2ping sweep, resolves names for any address with a known UAP along the
way, and handles pageto save/restore around the run.
"""
import shutil
import subprocess
import sys

from .args import parse_args
from .log import append_result
from .resolve import resolve_name
from .survey import parse_survey_results, prompt_scan_timeout, run_ubertooth_scan, select_target
from .sweep import get_pageto, probe_one, set_pageto


def _resolve_and_log(addr, args, source):
    """Resolve addr's name via hcitool (unless disabled), print it, and
    append it to --save's file if one was given. `source` records how
    the UAP became known ('survey' or 'sweep') for the log line. Returns
    the resolved name, or None if resolution was skipped/unsuccessful."""
    if args.no_resolve_names:
        return None
    name = resolve_name(addr, hcidev=args.hcidev, timeout=args.name_timeout)
    print(f"  [{source}] {addr} -> {name if name else '(no name response)'}")
    if args.save:
        append_result(args.save, addr, name, source)
    return name


def _resolve_target_via_survey(args):
    """No LAP given on the CLI -- interactively survey for one. Mutates
    args.known_octets in place, or exits the process if the user bails.

    Every survey pass that turns up 'ready to use' (UAP already
    resolved) candidates gets those names resolved and logged
    immediately, regardless of which candidate (if any) the user goes
    on to pick for brute-forcing -- they're already complete addresses
    modulo the assumed NAP, so there's no reason to wait."""
    if shutil.which("ubertooth-rx") is None:
        sys.exit("No known_octets given and ubertooth-rx not found on PATH "
                  "(try: sudo apt install ubertooth).")
    try:
        while True:
            timeout = args.scan_time if args.scan_time is not None else prompt_scan_timeout()
            args.scan_time = None  # only honor the CLI value on the first pass

            output = run_ubertooth_scan(timeout)
            needs_bf, ready = parse_survey_results(output)

            if ready and not args.no_resolve_names:
                print(f"\nResolving names for {len(ready)} known-UAP address(es) from the survey...")
                for uap, lap in ready:
                    addr = f"{args.prefix}:{uap}:{lap}"
                    _resolve_and_log(addr, args, source="survey")

            target = select_target(needs_bf, ready, args.prefix)
            if target is not None:
                args.known_octets = target
                return

            again = input("\nScan again? [y/N]: ").strip().lower()
            if again not in ("y", "yes"):
                sys.exit("No target selected. Exiting.")
    except KeyboardInterrupt:
        sys.exit("\nInterrupted during scan.")


def main(argv=None):
    args = parse_args(argv)

    # Checked and authenticated up front, before the (possibly interactive,
    # possibly repeated) survey step -- that step now also resolves names
    # for any 'ready to use' hit it finds, so it needs hcitool+sudo just as
    # much as the sweep below does.
    if shutil.which("l2ping") is None:
        sys.exit("l2ping not found on PATH (try: sudo apt install bluez-hcidump / bluez)")
    if not args.no_resolve_names and shutil.which("hcitool") is None:
        sys.exit("hcitool not found on PATH (try: sudo apt install bluez), "
                  "or pass --no-resolve-names to skip name resolution.")

    # Pre-authenticate sudo *before* anything else runs. Otherwise "sudo
    # l2ping"/"sudo hcitool" prompts for a password on stderr, which is
    # captured/hidden by subprocess -> the first probe just silently hangs
    # until you notice nothing is happening.
    print("Caching sudo credentials (you may be prompted for your password)...")
    if subprocess.run(["sudo", "-v"]).returncode != 0:
        sys.exit("sudo authentication failed")

    if args.known_octets is None:
        _resolve_target_via_survey(args)

    orig_pageto = None
    if not args.no_pageto_override:
        orig_pageto = get_pageto(args.hcidev)
        print(f"Setting {args.hcidev} pageto to {args.pageto} slots "
              f"(was {orig_pageto} slots)...")
        set_pageto(args.hcidev, args.pageto)
        # Verify it actually stuck. bluetoothd (if running) periodically
        # re-touches adapter parameters and can silently stomp this back
        # to its own default -- if that happens, every probe waits out
        # the *original* (larger) pageto no matter what we asked for.
        actual_pageto = get_pageto(args.hcidev)
        if actual_pageto is not None and actual_pageto != args.pageto:
            print(f"Warning: {args.hcidev} pageto reads back as {actual_pageto} slots, "
                  f"not the {args.pageto} requested. Something (often bluetoothd) is "
                  f"overriding it -- try `sudo systemctl stop bluetooth` before rerunning.")

    found_addr = None
    unresolved = []
    pageto_restored = False

    try:
        candidates = args.only if args.only is not None else range(256)
        print(f"Starting scan, trying {args.prefix}:XX:{args.known_octets} "
              f"({len(candidates)} candidate(s))\n")

        for byte_val in candidates:
            addr = f"{args.prefix}:{byte_val:02x}:{args.known_octets}"
            status = probe_one(addr)
            if status == "FOUND":
                found_addr = addr
                break
            unresolved.append(addr)

        # Serial recheck pass: a first-pass "no" under the shortened
        # pageto can be a real device whose page-scan window the probe
        # simply missed. Re-check with the original (larger) pageto
        # restored, and give each address multiple attempts since even a
        # fair single attempt can still miss the target's duty cycle.
        if found_addr is None and unresolved and not args.no_retry:
            if not args.no_pageto_override and orig_pageto is not None:
                print(f"\nRestoring {args.hcidev} pageto to {orig_pageto} slots for recheck pass...")
                set_pageto(args.hcidev, orig_pageto)
                pageto_restored = True

            total_attempts = args.retries + 1
            print(f"Rechecking {len(unresolved)} address(es), up to {total_attempts} "
                  f"attempt(s) each...\n")
            for addr in unresolved:
                for attempt in range(1, total_attempts + 1):
                    label = "retry" if total_attempts == 1 else f"retry {attempt}/{total_attempts}"
                    status = probe_one(addr, label=label)
                    if status == "FOUND":
                        found_addr = addr
                        break
                if found_addr is not None:
                    break

    except KeyboardInterrupt:
        print("\nInterrupted, shutting down...")
        sys.exit(130)
    finally:
        if orig_pageto is not None and not pageto_restored:
            print(f"\nRestoring {args.hcidev} pageto to {orig_pageto} slots...")
            set_pageto(args.hcidev, orig_pageto)

    if found_addr is not None:
        print(f"\nFound device at: {found_addr}")
        _resolve_and_log(found_addr, args, source="sweep")
        sys.exit(0)
    else:
        print("\nNot found")
        sys.exit(1)


if __name__ == "__main__":
    main()
