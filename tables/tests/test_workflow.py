from collections import Counter

from tables.flag_checks import digit_vote
from tables.workflow import column_maps, fix_separators, own_part, spelling, text_join, total_row, value_flags, with_rereads

ROLE = ["label", "text", "value"]
SAME_COLUMNS = {0: 0, 1: 1, 2: 2}
GROUPS = [["A", "x", "100"],
          ["B", "y", "250"],
          ["", "", "350"],
          ["Nhóm 2", "", ""],
          ["C", "z", "2.500.000"],
          ["D", "z", "587.772"]]


def test_total_of_the_rows_above_is_added_with_its_amounts_only():
    gemini = ["Nhóm 2", "", "3.087.772"]  # Gemini names the unlabelled total after the heading of its group
    assert total_row(GROUPS, ROLE, 5, gemini, SAME_COLUMNS) == ["", "", "3.087.772"]


def test_amount_that_is_not_the_sum_is_not_added():
    assert total_row(GROUPS, ROLE, 5, ["", "", "3.087.773"], SAME_COLUMNS) is None


def test_row_without_amounts_is_not_added():
    assert total_row(GROUPS, ROLE, 5, ["Ghi chú", "", ""], SAME_COLUMNS) is None


def test_total_of_one_row_needs_a_total_of_several_rows_in_the_table():
    one = [["Vay dài hạn", "", ""], ["C", "z", "938.000"]]
    repeat = ["", "", "938.000"]
    assert total_row(one, ROLE, 1, repeat, SAME_COLUMNS) is None  # could be Gemini repeating the row above
    assert total_row(GROUPS[:4] + one[1:], ROLE, 4, repeat, SAME_COLUMNS) == ["", "", "938.000"]


def test_comma_before_the_last_group_becomes_the_separator_of_the_table():
    tables = [{"rows": [["Doanh thu", "7.807.034", "4,835.204"]]}]
    assert fix_separators(tables) == [(0, 0, 2, "4,835.204")]
    assert tables[0]["rows"][0] == ["Doanh thu", "7.807.034", "4.835.204"]


def test_mark_at_the_last_group_is_left_because_it_can_be_a_decimal_mark():
    rows = [["Tỷ lệ", "7.807.034", "18,82"], ["Tỷ giá", "4.835,204", "4,835"]]
    tables = [{"rows": [list(r) for r in rows]}]
    assert fix_separators(tables) == []
    assert tables[0]["rows"] == rows


def test_table_that_groups_with_commas_keeps_its_decimal_point():
    tables = [{"rows": [["Revenue", "7,807,034", "4,835.204"]]}]
    assert fix_separators(tables) == []


def test_own_part():
    assert own_part("A. Tài sản ngắn hạn", "A.", "Tài sản ngắn hạn") == "Tài sản ngắn hạn"
    assert own_part("ii) Chi phí lãi vay", "ii)", "Chi phi lai vay") == "Chi phí lãi vay"
    assert own_part("100 cổ phiếu", "1", "100 cổ phiếu") == "100 cổ phiếu"      # m starts the same way: not cut
    assert own_part("Tiền", "1.", "Tiền") == "Tiền"
    assert own_part("Tiền", "", "Tien") == "Tiền"


def test_digit_vote():
    extra, g = Counter({"147027941663523": 1}), Counter({"147027941663523": 1})
    assert digit_vote("117.027.941.663.523", extra, g) == "147.027.941.663.523"
    assert digit_vote("(117.027.941.663.523)", extra, g) == "(147.027.941.663.523)"
    assert digit_vote("117.027.941.663.523", extra, Counter()) is None                     # Gemini silent
    assert digit_vote("117.027.941.663.523", extra, g + Counter({"117027941663523": 1})) is None
    assert digit_vote("117.027.941.663.523", Counter({"999027941663523": 1}), Counter({"999027941663523": 1})) is None  # 3 digits differ


def test_accepted_second_read_replaces_its_table_before_trim():
    raw = [{"rows": [["", ""]], "bbox": None, "title": ""},          # dropped by trim: output numbers move up
           {"rows": [["Tiền", "1.000"]], "bbox": [0, 0, 9, 9], "title": "A"},
           {"rows": [["", "2.000"]], "bbox": [0, 10, 9, 19], "title": "B"}]
    second = {"rows": [["Phải thu", "2.000", ""], ["Cộng", "3.000", ""]], "bbox": [0, 8, 9, 30]}
    tables, reread = with_rereads(raw, {"2": second})
    assert reread == [1]
    assert tables[1]["rows"] == [["Phải thu", "2.000"], ["Cộng", "3.000"]]
    assert tables[1]["bbox"] == [0, 8, 9, 30] and tables[1]["title"] == "B"
    assert tables[0]["rows"] == [["Tiền", "1.000"]]
    assert with_rereads(raw[1:], {})[1] == []


def gem(rows, fields=("label",)):
    return {"rows": [["", *[""] * (len(rows[0]) - 1)]] + rows, "fields": list(fields), "header_rows": [0]}


def test_text_join_list_cut_differently_by_one_header_row():
    M = [{"rows": [["STT", "Tên", "Địa điểm"], ["", "", "(a)"],
                   ["1", "Công ty Cổ phần Alpha", "Hà Nội"], ["2", "Công ty TNHH Beta", "Đà Nẵng"]]}]
    G = [gem([["Công ty Cổ phần Alpha", "1", "Hà Nội"], ["Công ty TNHH Beta", "2", "Đà Nẵng"]], ("label", "code"))]
    assert text_join(M, G, {}) == {(0, 2): (1, "text"), (0, 3): (2, "text")}


def test_text_join_near_equal_rows_keep_page_order_and_take_each_gemini_row_once():
    M = [{"rows": [["Công ty Cổ phần An Phú 1", "Hà Nội"], ["Công ty Cổ phần An Phú 2", "Hà Nội"],
                   ["Công ty Cổ phần An Phú 3", "Hà Nội"]]}]
    G = [gem([["Công ty Cổ phần An Phú 1", "Hà Nội"], ["Công ty Cổ phần An Phú 2", "Hà Nội"],
              ["Công ty Cổ phần An Phú 3", "Hà Nội"]])]
    # the middle row is already joined (by step 2): the rows around it join on their own side of it
    J = text_join(M, G, {(0, 1): (2, "position")})
    assert J == {(0, 0): (1, "text"), (0, 1): (2, "position"), (0, 2): (3, "text")}


def test_text_join_cells_in_another_order_and_their_column_map():
    M = [{"rows": [["Công ty Cổ phần Alpha", "Thành phố Hà Nội"], ["Công ty TNHH Beta", "Tỉnh Lâm Đồng"]]}]
    G = [gem([["Thành phố Hà Nội", "Công ty Cổ phần Alpha"], ["Tĩnh Lâm Đồng", "Công ty TNHH Beta"]])]
    J = text_join(M, G, {})
    assert J == {(0, 0): (1, "text"), (0, 1): (2, "text")}
    mref, gref = [(0, 0), (0, 1)], [(0, r) for r in range(3)]
    assert column_maps(M, G, mref, gref, {mref.index(k): v for k, v in J.items()})[0, 0] == {0: 1, 1: 0}


def test_text_join_leaves_a_split_wrapped_label_alone():
    M = [{"rows": [["Công ty Cổ phần Đầu tư", "Hà Nội"], ["và Phát triển Nam Long", ""]]}]
    G = [gem([["Công ty Cổ phần Đầu tư và Phát triển Nam Long", "Hà Nội"]])]
    assert text_join(M, G, {}) == {}


def test_rule2_keeps_a_mineru_cell_with_no_letter_and_no_digit():
    assert spelling("-", "–") == "-"          # a dash keeps MinerU's character
    assert spelling("", "-") == ""            # Gemini fills no empty cell
    assert spelling("", "") == ""
    assert spelling("Tĩnh Lâm Đồng", "Tỉnh Lâm Đồng") == "Tỉnh Lâm Đồng"


def test_value_cell_mineru_left_empty_where_gemini_has_a_dash_is_flagged_not_changed():
    assert value_flags(0, 9, 3, "", "-") == [{"table": 0, "row": 9, "col": 3, "kind": "blank_or_dash",
                                              "mineru": "", "gemini": "-"}]
    assert value_flags(0, 9, 3, "-", "") == []                  # MinerU's dash, Gemini empty: not flagged
    assert value_flags(0, 9, 3, "", "") == [] and value_flags(0, 9, 3, "-", "–") == []
    assert [f["kind"] for f in value_flags(0, 9, 3, "1.000", "1.001")] == ["amount_mismatch"]
