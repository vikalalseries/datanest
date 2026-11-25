from datetime import date, timedelta

import pytest
from fastapi import HTTPException

from app.services import activity_service as act
from app.services import analytics_service as an
from app.services import notification_service as ns
from app.services import templates_service as tpl

TODAY = date(2026, 11, 24)
JOB_COLS = [
    {"id": "c_co", "name": "Company", "type": "text"}, {"id": "c_pos", "name": "Position", "type": "text"},
    {"id": "c_ap", "name": "Applied Date", "type": "date"}, {"id": "c_dl", "name": "Deadline", "type": "date"},
    {"id": "c_st", "name": "Status", "type": "status"},
]


# ---------------- status classification ----------------
@pytest.mark.parametrize("value,expected", [
    ("Applied", "pending"), ("pending", "pending"), ("Waiting for reply", "pending"), (None, "pending"), ("", "pending"),
    ("Interview scheduled", "interview"), ("Technical round", "interview"), ("Phone screening", "interview"),
    ("Offer received", "offer"), ("Accepted", "offer"), ("Hired", "offer"),
    ("Rejected", "rejected"), ("Declined by company", "rejected"), ("Not selected", "rejected"),
    ("Withdrawn", "withdrawn"), ("Cancelled", "withdrawn"), ("Ghosted lol", "other"),
])
def test_classify_status(value, expected):
    assert an.classify_status(value) == expected


# ---------------- category gating: no irrelevant analytics ----------------
@pytest.mark.parametrize("cat,job,exp", [
    ("job_application", True, False), ("internship_application", True, False), ("Internship Tracker", True, False),
    ("expense", False, True), ("personal_expense", False, True), ("Expenses", False, True),
    ("general", False, False), ("customer", False, False), ("meeting", False, False), ("project_task", False, False), ("academic_task", False, False), ("", False, False),
])
def test_category_gating(cat, job, exp):
    assert an.is_job_category(cat) is job and an.is_expense_category(cat) is exp


# ---------------- job analytics ----------------
def rows(*statuses, applied=None):
    return [{"c_st": s, "c_ap": applied or "2026-11-02"} for s in statuses]


def metrics(out):
    return {m["key"]: m["value"] for m in out["metrics"]}


def test_job_metrics_and_response_rate():
    r = rows("Applied", "Applied", "Interview", "Rejected", "Offer", None, "Withdrawn", "Ghosted")
    out = an.compute_job(JOB_COLS, r, TODAY)
    m = metrics(out)
    assert m["applications"] == 8 and m["interviews"] == 1 and m["rejections"] == 1 and m["offers"] == 1 and m["pending"] == 3
    assert m["response_rate"] == 37.5  # (1 + 1 + 1) / 8
    assert m["this_month"] == 8
    assert {b["label"] for b in out["breakdown"]} >= {"Applied", "Interview", "(no status)"}
    assert any("isn't counted" in n for n in out["notes"])  # Withdrawn/Ghosted are explained, not hidden


def test_job_analytics_edge_cases():
    assert metrics(an.compute_job(JOB_COLS, [], TODAY))["response_rate"] == 0.0  # no division by zero
    no_status = an.compute_job([c for c in JOB_COLS if c["type"] != "status"], [{"c_co": "A"}], TODAY)
    assert [m["key"] for m in no_status["metrics"]] == ["applications"] and "Status column" in no_status["notes"][0]  # tells the user what to add
    last_month = an.compute_job(JOB_COLS, rows("Applied", applied="2026-10-30"), TODAY)
    assert metrics(last_month)["this_month"] == 0


# ---------------- expense analytics ----------------
EXP_COLS = [{"id": "e_d", "name": "Date", "type": "date"}, {"id": "e_i", "name": "Item", "type": "text"}, {"id": "e_a", "name": "Amount", "type": "currency"},
            {"id": "e_c", "name": "Category", "type": "status"}]


def test_expense_metrics():
    r = [{"e_d": "2026-11-03", "e_a": 500, "e_c": "Food"}, {"e_d": "2026-11-10", "e_a": 250.5, "e_c": "Travel"},
         {"e_d": "2026-10-30", "e_a": 100, "e_c": "Food"}, {"e_d": "2026-11-11", "e_a": None, "e_c": "Food"}, {"e_d": "2026-11-12", "e_a": 49.5}]
    out = an.compute_expense(EXP_COLS, r, TODAY)
    m = metrics(out)
    assert m["total_spent"] == 900 and m["entries"] == 4 and m["average"] == 225 and m["largest"] == 500 and m["this_month"] == 800
    assert out["breakdown"][0] == {"label": "Food", "value": 600} and {"label": "(uncategorised)", "value": 49.5} in out["breakdown"]
    assert "Amount column" in an.compute_expense([EXP_COLS[1]], [{}], TODAY)["notes"][0]


# ---------------- templates ----------------
def test_the_eight_required_templates_exist_and_are_valid():
    names = {t["name"] for t in tpl.TEMPLATES}
    assert names == {"Internship Tracker", "Job Application Tracker", "Expense Tracker", "Project Management", "Student Academic Tracker",
                     "Customer Management", "Meeting Records", "Personal Task Tracker"}
    assert len({t["key"] for t in tpl.TEMPLATES}) == 8
    ok_types = {"text", "number", "currency", "date", "boolean", "email", "url", "status", "tags"}
    for t in tpl.TEMPLATES:
        cols = t["columns"]
        assert 4 <= len(cols) <= 12 and len({c["name"].lower() for c in cols}) == len(cols), t["key"]
        assert all(c["type"] in ok_types for c in cols)
        assert all(("options" in c) == (c["type"] == "status") for c in cols), t["key"]  # options only on status columns
    # trackers feed the analytics: their categories must switch the right insights on
    assert an.is_job_category(tpl.BY_KEY["internship_tracker"]["category"]) and an.is_job_category(tpl.BY_KEY["job_application_tracker"]["category"])
    assert an.is_expense_category(tpl.BY_KEY["expense_tracker"]["category"])
    assert not an.is_job_category(tpl.BY_KEY["customer_management"]["category"])


def test_ai_template_output_is_sanitised():
    g = tpl.GTemplate(name="  My   Tasks  ", description="x" * 900, category="Project Task!", columns=[
        tpl.GColumn(name="Task", type="text", options=["ignored"]), tpl.GColumn(name="task", type="text", options=[]),  # duplicate (case-insens.)
        tpl.GColumn(name="Stage", type="status", options=["Todo", "Todo", "Doing", " ", "Done"]), tpl.GColumn(name="", type="text", options=[]),
    ] + [tpl.GColumn(name=f"C{i}", type="number", options=[]) for i in range(30)])
    out = tpl.clean_template(g)
    names = [c["name"] for c in out["columns"]]
    assert out["name"] == "My Tasks" and len(out["description"]) == 500 and out["category"] == "project_task"
    assert names[:2] == ["Task", "Stage"] and len(names) == 20 and len(set(n.lower() for n in names)) == len(names)
    assert "options" not in out["columns"][0] and out["columns"][1]["options"] == ["Todo", "Doing", "Done"]
    with pytest.raises(HTTPException):
        tpl.clean_template(tpl.GTemplate(name="x", description="", category="", columns=[tpl.GColumn(name=" ", type="text", options=[])]))


# ---------------- notifications ----------------
def notif(rows_, cols=JOB_COLS, category="job_application"):
    return ns.compute_for_sheet("s1", "Jobs", category, cols, [(f"r{i}", r) for i, r in enumerate(rows_)], TODAY)


def d(n):
    return (TODAY + timedelta(days=n)).isoformat()


def test_deadline_notifications_soon_overdue_and_far():
    out = notif([
        {"c_co": "Dobbe AI", "c_dl": d(0), "c_st": "Applied"}, {"c_co": "Globex", "c_dl": d(5), "c_st": "Applied"},
        {"c_co": "Far Co", "c_dl": d(30), "c_st": "Applied"}, {"c_co": "Late Inc", "c_dl": d(-3), "c_st": "Applied"},
        {"c_co": "Ancient", "c_dl": d(-90), "c_st": "Applied"},
    ], category="general")
    by = {i["title"].split(":")[0]: i for i in out}
    assert by["Dobbe AI"]["kind"] == "due_soon" and "today" in by["Dobbe AI"]["title"]
    assert by["Globex"]["kind"] == "due_soon" and "in 5 days" in by["Globex"]["title"]
    assert by["Late Inc"]["kind"] == "overdue" and by["Late Inc"]["severity"] == "danger" and "3 days ago" in by["Late Inc"]["title"]
    assert "Far Co" not in by and "Ancient" not in by  # far-future and long-gone deadlines are noise


def test_finished_items_do_not_nag():
    out = notif([{"c_co": "A", "c_dl": d(-2), "c_st": "Rejected"}, {"c_co": "B", "c_dl": d(2), "c_st": "Offer"}, {"c_co": "C", "c_dl": d(2), "c_st": "Done"}], category="general")
    assert out == []


def test_stale_application_rules():
    out = notif([
        {"c_co": "Quiet Co", "c_ap": d(-20), "c_st": "Applied"}, {"c_co": "Fresh Co", "c_ap": d(-3), "c_st": "Applied"},
        {"c_co": "Replied Co", "c_ap": d(-30), "c_st": "Interview"}, {"c_co": "Old Co", "c_ap": d(-400), "c_st": "Applied"},
    ])
    assert [i["kind"] for i in out] == ["no_response"] and "Quiet Co" in out[0]["title"] and "20 days" in out[0]["title"]
    assert notif([{"c_co": "Quiet Co", "c_ap": d(-20), "c_st": "Applied"}], category="general") == []  # only for job/internship sheets


def test_notification_ids_are_stable_and_unique():
    r = [{"c_co": "A", "c_dl": d(1)}, {"c_co": "B", "c_dl": d(1)}]
    a, b = notif(r, category="general"), notif(r, category="general")
    assert [i["id"] for i in a] == [i["id"] for i in b] and len({i["id"] for i in a}) == 2


# ---------------- activity descriptions ----------------
def test_activity_descriptions():
    names = {"c1": "Company", "c2": "Status"}
    s, ch = act.describe("record.update", {"before": {"c2": "Applied"}, "after": {"c2": "Interview", "c1": None}}, "Jobs", names)
    assert s == "Edited a row in “Jobs”" and {"column": "Status", "before": "Applied", "after": "Interview"} in ch and {"column": "Company", "before": "(empty)", "after": "(empty)"} in ch
    assert act.describe("records.bulk_add", {"added": 3}, "Jobs", {})[0] == "Added extracted rows to “Jobs” (3 rows)"
    assert act.describe("export.sheet", {"format": "csv"}, "Jobs", {})[0] == "Exported “Jobs” as CSV"
    assert act.describe("some.new_action", {}, None, {})[0] == "Some new action"
