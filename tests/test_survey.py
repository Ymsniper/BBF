from bbf.survey import parse_survey_results


def test_no_survey_results_header_returns_empty():
    needs_bf, ready = parse_survey_results("just some noise\nno header here\n")
    assert needs_bf == []
    assert ready == []


def test_separates_resolved_and_unresolved_uap():
    output = "\n".join([
        "junk preamble",
        "Survey Results",
        "??:??:BE:B4:F1:3F",
        "??:??:??:C5:9D:87",
        "??:??:AA:11:22:33",
        "not a valid addr line at all",
        "",
    ])
    needs_bf, ready = parse_survey_results(output)
    assert needs_bf == ["C5:9D:87"]
    assert ready == [("BE", "B4:F1:3F"), ("AA", "11:22:33")]


def test_skips_lines_with_unresolved_lap():
    output = "\n".join([
        "Survey Results",
        "??:??:??:??:9D:87",  # LAP itself partly unresolved -- not usable
        "??:??:BE:B4:F1:3F",
    ])
    needs_bf, ready = parse_survey_results(output)
    assert needs_bf == []
    assert ready == [("BE", "B4:F1:3F")]


def test_deduplicates_repeated_entries():
    output = "\n".join([
        "Survey Results",
        "??:??:??:C5:9D:87",
        "??:??:??:C5:9D:87",
        "??:??:BE:B4:F1:3F",
        "??:??:BE:B4:F1:3F",
    ])
    needs_bf, ready = parse_survey_results(output)
    assert needs_bf == ["C5:9D:87"]
    assert ready == [("BE", "B4:F1:3F")]
