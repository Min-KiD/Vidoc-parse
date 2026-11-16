from tables.flag_checks import document_flags, flag_malformed, page_flags


def test_malformed_flag_shape():
    for s in ("1.", "59,00", "27.1"):
        assert not flag_malformed(s), s
    for s in ("143.000000", "3.882.700.00"):
        assert flag_malformed(s), s


def test_page_flags_empty_inputs():
    assert page_flags([], []) == []
    assert page_flags([{"rows": [["a", "b"]], "header_rows": [], "bbox": [0, 0, 1, 1]}], []) == []


def test_coded_row_empty_is_flagged_on_its_row():
    rows = [["Chỉ tiêu", "Mã số", "Kỳ này"],  # line 36 is listed by B03 only: the form is known
            ["Cổ tức đã trả", "36", "(5)"],
            ["Lưu chuyển tiền thuần trong kỳ", "50", "0"],
            ["Tiền đầu kỳ", "60", "100"],
            ["Ảnh hưởng của thay đổi tỷ giá", "61", ""],
            ["Tiền cuối kỳ", "70", "100"]]
    flags = document_flags({3: [{"rows": rows, "header_rows": [0]}]})
    assert flags == {3: [{"table": 0, "row": 4, "col": None, "kind": "coded_row_empty", "form": "B03", "code": "61"}]}
