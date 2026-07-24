from nocturne.core.auto_enhance import detect_data_type


def test_lp_filter_is_dualband():
    assert detect_data_type({"filter": "LP"}) == "dualband"
    assert detect_data_type({"filter": "lp"}) == "dualband"       # case-insensitive


def test_other_filter_is_broadband():
    assert detect_data_type({"filter": "IRCUT"}) == "broadband"
    assert detect_data_type({"filter": "UV/IR"}) == "broadband"


def test_absent_filter_is_unknown():
    assert detect_data_type({}) == "unknown"
    assert detect_data_type({"filter": ""}) == "unknown"
