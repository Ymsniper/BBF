"""Name resolution for BD_ADDRs whose UAP is already known -- either
because ubertooth-rx's survey resolved it directly ("ready to use"), or
because bbf's own l2ping sweep found a live one.

A Remote_Name_Request doesn't require pairing/bonding to succeed; it's
answered by any page-scannable device, which is most devices, briefly,
even ones in "non-discoverable" mode -- page-scan and inquiry-scan are
separate radio states, and the spec doesn't gate name requests behind
authentication by default. That's what makes it worth running here even
for addresses that were only ever survey-resolved and never explicitly
paged by this tool.

Note this is a *different* radio exchange than l2ping. A device can
answer l2ping and decline/ignore a name request (some post-2022 stacks
throttle or restrict LMP_name_req as a tracking mitigation), or vice
versa. A "(no response)" here is itself a useful data point, not just a
failure -- it can mean the address is confirmed live but hardened
against name disclosure.
"""
import shutil
import subprocess


def resolve_name(addr, hcidev="hci0", timeout=20, use_sudo=True):
    """Run `hcitool name` against addr. Returns the resolved name string,
    or None if there was no response within timeout, hcitool isn't on
    PATH, or it exited without printing a name.

    timeout is a hard subprocess-level safety valve, separate from and
    in addition to whatever the adapter's page timeout (--pageto) is set
    to -- hcitool has no notion of --pageto itself, so without this a
    single unresponsive address could hang the run indefinitely.
    """
    if shutil.which("hcitool") is None:
        return None

    cmd = ["hcitool", "-i", hcidev, "name", addr]
    if use_sudo:
        cmd = ["sudo"] + cmd

    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return None

    name = proc.stdout.strip()
    return name if name else None
