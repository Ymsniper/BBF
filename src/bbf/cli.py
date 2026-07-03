"""Top-level orchestration: ties the optional ubertooth survey to the
l2ping sweep and handles pageto save/restore around the run.
"""
import shutil
import subprocess
import sys

from .args import parse_args
from .survey import parse_survey_results, prompt_scan_timeout, run_ubertooth_scan, select_target
from .sweep import get_pageto, probe_one, set_pageto


def _resolve_target_via_survey(args):
    """No LAP given on the CLI -- interactively survey for one. Mutates
    args.known_octets in place, or exits the process if the user bails."""
    if shutil.which("ubertooth-rx") is None:
        sys.exit("No known_octets given and ubertooth-rx not found on PATH "
                  "(try: sudo apt install ubertooth).")
    try:
        while True:
            timeout = args.scan_time if args.scan_time is not None else prompt_scan_timeout()
            args.scan_time = None  # only honor the CLI value on the first pass

            output = run_ubertooth_scan(timeout)
            needs_bf, ready = parse_survey_results(output)
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

    if args.known_octets is None:
        _resolve_target_via_survey(args)

    if shutil.which("l2ping") is None:
        sys.exit("l2ping not found on PATH (try: sudo apt install bluez-hcidump / bluez)")

    # Pre-authenticate sudo *before* the loop starts. Otherwise "sudo
    # l2ping" prompts for a password on stderr, which is captured/hidden
    # by subprocess -> the first probe just silently hangs until you
    # notice nothing is happening.
    print("Caching sudo credentials (you may be prompted for your password)...")
    if subprocess.run(["sudo", "-v"]).returncode != 0:
        sys.exit("sudo authentication failed")

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
        sys.exit(0)
    else:
        print("\nNot found")
        sys.exit(1)


if __name__ == "__main__":
    main()
