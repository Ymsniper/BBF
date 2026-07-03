"""Shared regexes and defaults used across the bbf package."""
import re

OCTET3_RE = re.compile(r"^[0-9A-Fa-f]{2}(:[0-9A-Fa-f]{2}){2}$")
OCTET2_RE = re.compile(r"^[0-9A-Fa-f]{2}:[0-9A-Fa-f]{2}$")
PAGETO_RE = re.compile(r"Page timeout:\s*(\d+)\s*slots")
SURVEY_ADDR_RE = re.compile(r"^(?:(?:[0-9A-Fa-f]{2}|\?\?):){5}(?:[0-9A-Fa-f]{2}|\?\?)$")

DEFAULT_SCAN_TIME = 30
