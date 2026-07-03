import pytest

from bbf.args import parse_args


def test_defaults():
    args = parse_args(["1E:B7:E4"])
    assert args.known_octets == "1E:B7:E4"
    assert args.prefix == "00:00"
    assert args.hcidev == "hci0"
    assert args.pageto == 1600
    assert args.retries == 2
    assert args.only is None
    assert args.scan_time is None


def test_known_octets_is_optional():
    args = parse_args([])
    assert args.known_octets is None


def test_rejects_malformed_known_octets():
    with pytest.raises(SystemExit):
        parse_args(["not-an-address"])


def test_rejects_malformed_prefix():
    with pytest.raises(SystemExit):
        parse_args(["1E:B7:E4", "--prefix", "zz:zz"])


def test_rejects_negative_retries():
    with pytest.raises(SystemExit):
        parse_args(["1E:B7:E4", "--retries", "-1"])


def test_rejects_non_positive_scan_time():
    with pytest.raises(SystemExit):
        parse_args(["--scan-time", "0"])


def test_only_parses_single_byte():
    args = parse_args(["1E:B7:E4", "--only", "5c"])
    assert args.only == [0x5C]


def test_only_parses_multiple_bytes():
    args = parse_args(["1E:B7:E4", "--only", "04,5c,a1"])
    assert args.only == [0x04, 0x5C, 0xA1]


def test_only_rejects_non_hex():
    with pytest.raises(SystemExit):
        parse_args(["1E:B7:E4", "--only", "zz"])


def test_only_rejects_out_of_range_byte():
    with pytest.raises(SystemExit):
        parse_args(["1E:B7:E4", "--only", "1ff"])


def test_save_and_name_resolution_defaults():
    args = parse_args(["1E:B7:E4"])
    assert args.save is None
    assert args.no_resolve_names is False
    assert args.name_timeout == 20


def test_save_accepts_path():
    args = parse_args(["1E:B7:E4", "--save", "found.tsv"])
    assert args.save == "found.tsv"


def test_no_resolve_names_flag():
    args = parse_args(["1E:B7:E4", "--no-resolve-names"])
    assert args.no_resolve_names is True


def test_rejects_non_positive_name_timeout():
    with pytest.raises(SystemExit):
        parse_args(["1E:B7:E4", "--name-timeout", "0"])
