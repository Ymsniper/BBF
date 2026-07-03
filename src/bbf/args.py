"""Command-line argument parsing and validation."""
import argparse

from .constants import DEFAULT_SCAN_TIME, OCTET2_RE, OCTET3_RE


def parse_args(argv=None):
    p = argparse.ArgumentParser(
        prog="bbf",
        description="Brute-force one unknown BD_ADDR octet via l2ping.",
    )
    p.add_argument(
        "known_octets", nargs="?", default=None,
        help="the 3 known trailing octets (LAP), e.g. 1E:B7:E4. If omitted, runs "
             "an interactive ubertooth-rx survey to discover/select a target.",
    )
    p.add_argument("--prefix", default="00:00", help="the 2 known leading octets / NAP (default: 00:00)")
    p.add_argument("--hcidev", default="hci0", help="HCI adapter to tune (default: hci0)")
    p.add_argument(
        "--pageto", type=int, default=1600,
        help="controller page timeout in slots (1 slot = 0.625ms) to set for the "
             "duration of the sweep (default: 1600 / ~1s), so a dead address doesn't "
             "tie up the controller for long. Restored to the original value before "
             "the serial recheck pass, where a real device gets an unhurried shot "
             "with the original -- usually much larger -- pageto.",
    )
    p.add_argument(
        "--no-pageto-override", action="store_true",
        help="leave the adapter's page timeout untouched instead of using --pageto.",
    )
    p.add_argument(
        "--no-retry", action="store_true",
        help="skip the serial recheck pass entirely",
    )
    p.add_argument(
        "--retries", type=int, default=2,
        help="max additional attempts per address during the serial recheck pass "
             "before giving up on it (default: 2, so 3 total attempts). A Bluetooth "
             "device only listens for pages during its own page-scan window/interval "
             "-- a single miss, even against the exact right address with a healthy "
             "pageto, can just mean the attempt didn't land inside that window.",
    )
    p.add_argument(
        "--only", default=None,
        help="comma-separated hex byte(s) to test instead of sweeping 00..ff, e.g. "
             "'5c' or '04,5c,a1'. Skips straight to testing specific candidate(s). "
             "Also useful for directly testing a single 'ready to use' address found "
             "during a survey, e.g. --only be.",
    )
    p.add_argument(
        "--scan-time", type=int, default=None,
        help=f"ubertooth-rx -t duration in seconds for the interactive survey "
             f"(default: {DEFAULT_SCAN_TIME}, prompted interactively if not given "
             f"here). Only used when known_octets is omitted.",
    )
    p.add_argument(
        "--save", metavar="FILE", default=None,
        help="append 'timestamp<TAB>address<TAB>name<TAB>source' to FILE for every "
             "address with a known UAP as it's resolved -- both survey 'ready to "
             "use' hits and whatever the sweep finds live. Creates FILE if it "
             "doesn't exist; never truncates it, so repeated runs accumulate.",
    )
    p.add_argument(
        "--no-resolve-names", action="store_true",
        help="skip running `hcitool name` against known-UAP addresses; just report "
             "the addresses themselves (matches old behavior).",
    )
    p.add_argument(
        "--name-timeout", type=int, default=20,
        help="subprocess-level timeout in seconds for each hcitool name call "
             "(default: 20). Independent safety valve on top of --pageto, since "
             "hcitool has no --pageto concept of its own.",
    )
    args = p.parse_args(argv)

    if args.known_octets is not None and not OCTET3_RE.match(args.known_octets):
        p.error(f"known_octets must look like AA:BB:CC, got {args.known_octets!r}")
    if not OCTET2_RE.match(args.prefix):
        p.error(f"--prefix must look like AA:BB, got {args.prefix!r}")
    if args.retries < 0:
        p.error("--retries must be >= 0")
    if args.scan_time is not None and args.scan_time <= 0:
        p.error("--scan-time must be > 0")
    if args.name_timeout <= 0:
        p.error("--name-timeout must be > 0")
    if args.only is not None:
        try:
            args.only = [int(b, 16) for b in args.only.split(",")]
        except ValueError:
            p.error(f"--only must be comma-separated hex bytes, got {args.only!r}")
        for b in args.only:
            if not 0 <= b <= 0xFF:
                p.error(f"--only byte out of range: {b:x}")
    return args
