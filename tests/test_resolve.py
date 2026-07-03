import subprocess
from unittest.mock import patch

from bbf.log import append_result
from bbf.resolve import resolve_name


def _fake_run_found(cmd, capture_output, text, timeout):
    assert cmd[0] == "sudo"
    assert "hcitool" in cmd
    assert "name" in cmd
    class R:
        stdout = "JBL TUNE BEAM\n"
    return R()


def _fake_run_empty(cmd, capture_output, text, timeout):
    class R:
        stdout = ""
    return R()


def _fake_run_timeout(cmd, capture_output, text, timeout):
    raise subprocess.TimeoutExpired(cmd, timeout)


@patch("bbf.resolve.shutil.which", return_value="/usr/bin/hcitool")
@patch("bbf.resolve.subprocess.run", side_effect=_fake_run_found)
def test_resolve_name_found(mock_run, mock_which):
    name = resolve_name("00:00:5c:06:3e:0f", hcidev="hci0")
    assert name == "JBL TUNE BEAM"


@patch("bbf.resolve.shutil.which", return_value="/usr/bin/hcitool")
@patch("bbf.resolve.subprocess.run", side_effect=_fake_run_empty)
def test_resolve_name_no_response(mock_run, mock_which):
    assert resolve_name("00:00:be:b4:f1:3f") is None


@patch("bbf.resolve.shutil.which", return_value="/usr/bin/hcitool")
@patch("bbf.resolve.subprocess.run", side_effect=_fake_run_timeout)
def test_resolve_name_timeout(mock_run, mock_which):
    assert resolve_name("00:00:be:b4:f1:3f", timeout=1) is None


@patch("bbf.resolve.shutil.which", return_value=None)
def test_resolve_name_missing_hcitool(mock_which):
    assert resolve_name("00:00:be:b4:f1:3f") is None


def test_append_result_creates_and_appends(tmp_path):
    path = tmp_path / "found.tsv"
    append_result(str(path), "00:00:be:b4:f1:3f", "Redmi Note 14 5G", "survey")
    append_result(str(path), "00:00:5c:06:3e:0f", None, "sweep")

    lines = path.read_text().splitlines()
    assert len(lines) == 2
    assert "00:00:be:b4:f1:3f" in lines[0]
    assert "Redmi Note 14 5G" in lines[0]
    assert "survey" in lines[0]
    assert "00:00:5c:06:3e:0f" in lines[1]
    assert "(no name response)" in lines[1]
    assert "sweep" in lines[1]
