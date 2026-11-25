from app.services import matching_service as m


def E(*pairs):
    return [{"name": n, "type": t} for n, t in pairs]


def S(*pairs):
    return [{"id": f"c_{i}", "name": n, "type": t} for i, (n, t) in enumerate(pairs)]


def test_norm_drops_units_and_punctuation():
    assert m.norm("Amount (INR)") == "amount"
    assert m.norm("  Date_Applied! ") == "date applied"


def test_job_fields_map_to_job_sheet_with_synonyms():
    e = E(("Company", "text"), ("Position", "text"), ("Date Applied", "date"), ("Source", "text"), ("Status", "status"))
    s = S(("Employer", "text"), ("Role", "text"), ("Applied Date", "date"), ("Platform", "text"), ("Status", "status"), ("Notes", "text"))
    mp = {x.extracted: x for x in m.deterministic_match(e, s)}
    assert mp["Company"].sheet_column_name == "Employer" and mp["Company"].method == "synonym"
    assert mp["Position"].sheet_column_name == "Role"
    assert mp["Date Applied"].sheet_column_name == "Applied Date"
    assert mp["Source"].sheet_column_name == "Platform"
    assert mp["Status"].method == "exact"


def test_mapping_is_one_to_one():
    e = E(("Company", "text"), ("Employer", "text"))
    s = S(("Company", "text"))
    mapped = [x for x in m.deterministic_match(e, s) if x.sheet_column_id]
    assert len(mapped) == 1 and mapped[0].extracted == "Company"  # exact beats synonym


def test_incompatible_types_do_not_match():
    assert m.deterministic_match(E(("Amount", "number")), S(("Amount", "date")))[0].sheet_column_id is None
    assert m.deterministic_match(E(("Amount", "currency")), S(("Cost", "number")))[0].sheet_column_id is not None


def test_unrelated_names_do_not_match():
    assert m.deterministic_match(E(("Merchant", "text")), S(("Company", "text"), ("Position", "text")))[0].sheet_column_id is None


def records(*dicts):
    return [{"values": d} for d in dicts]


def test_summary_good_match_suggests_add():
    e = E(("Company", "text"), ("Position", "text"))
    s = S(("Company", "text"), ("Position", "text"), ("Status", "status"))
    r = records({"Company": "A", "Position": "B"})
    sm = m.summarize(e, r, "Jobs", "job_application", "job_application", m.deterministic_match(e, s), s)
    assert sm["suggestion"] == "add" and sm["match_ratio"] == 1.0 and sm["category_match"] and sm["unfilled_sheet_columns"] == ["Status"]


def test_summary_mismatch_explains_and_suggests_new_sheet():
    e = E(("Merchant", "text"), ("Amount", "currency"), ("Date", "date"), ("Category", "text"))
    s = S(("Company", "text"), ("Position", "text"), ("Applied Date", "date"), ("Status", "status"))
    r = records({"Merchant": "Uber", "Amount": 230, "Date": "2026-11-19", "Category": "Travel"})
    sm = m.summarize(e, r, "Jobs", "job_application", "expense", m.deterministic_match(e, s), s)
    assert sm["suggestion"] == "create_new_sheet"
    assert "expense" in sm["explanation"] and "job application" in sm["explanation"]
    assert set(sm["unmapped_extracted"]) >= {"Merchant", "Amount", "Category"}  # reported, never hidden


def test_summary_partial_lists_unmapped_fields():
    e = E(("Company", "text"), ("Position", "text"), ("Salary", "currency"))
    s = S(("Company", "text"), ("Position", "text"))
    sm = m.summarize(e, records({"Company": "A", "Position": "B", "Salary": 5}), "Jobs", "job_application", "job_application", m.deterministic_match(e, s), s)
    assert sm["suggestion"] in ("add", "add_with_new_columns") and sm["unmapped_extracted"] == ["Salary"]
    assert "Salary" in sm["explanation"]


# ---------- duplicates ----------
COLS = {c["id"]: c for c in S(("Company", "text"), ("Position", "text"), ("Status", "status"), ("Applied", "date"))}


def ids():
    return {n: c["id"] for c in COLS.values() for n in [c["name"]]}


def test_same_application_is_duplicate_despite_case_and_spacing():
    i = ids()
    a = {i["Company"]: "Dobbe AI", i["Position"]: "AI Intern", i["Applied"]: "2026-11-23"}
    b = {i["Company"]: "  dobbe  ai ", i["Position"]: "AI intern", i["Applied"]: "2026-11-23", i["Status"]: "Interview"}
    sim, matched = m.compare_rows(COLS, a, b)
    assert sim == 1.0 and set(matched) == {"Company", "Position", "Applied"}


def test_same_company_different_role_is_not_duplicate():
    i = ids()
    a = {i["Company"]: "Dobbe AI", i["Position"]: "AI Intern"}
    b = {i["Company"]: "Dobbe AI", i["Position"]: "Data Analyst"}
    assert m.compare_rows(COLS, a, b)[0] == 0.0


def test_matching_only_on_status_is_not_duplicate():
    i = ids()
    assert m.compare_rows(COLS, {i["Status"]: "Applied"}, {i["Status"]: "Applied"})[0] == 0.0


def test_single_overlap_exact_match_is_duplicate_but_short_values_are_not():
    i = ids()
    assert m.compare_rows(COLS, {i["Company"]: "Dobbe AI"}, {i["Company"]: "Dobbe AI", i["Status"]: "x"})[0] == 1.0
    assert m.compare_rows(COLS, {i["Company"]: "A"}, {i["Company"]: "A"})[0] == 0.0


def test_empty_rows_never_duplicates():
    assert m.compare_rows(COLS, {}, {})[0] == 0.0
