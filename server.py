import os
import json
import subprocess
import requests
from mcp.server.fastmcp import FastMCP

BASE_URL = os.getenv("TESTIT_BASE_URL")
if not BASE_URL:
    raise RuntimeError("TESTIT_BASE_URL environment variable is required")

def get_token() -> str:
    result = subprocess.run(
        ["security", "find-generic-password", "-a", os.getenv("USER", ""), "-s", "testit-mcp", "-w"],
        capture_output=True, text=True
    )
    return result.stdout.strip()

mcp = FastMCP("testit")

def headers():
    return {
        "Authorization": f"PrivateToken {get_token()}",
        "Content-Type": "application/json"
    }

def api(method, path, **kwargs):
    url = f"{BASE_URL}/api/v2{path}"
    resp = requests.request(method, url, headers=headers(), **kwargs)
    resp.raise_for_status()
    if resp.content:
        return resp.json()
    return {}


# ── Work Items ───────────────────────────────────────────────────────────────

@mcp.tool()
def get_work_item(item_id: str) -> str:
    """Get a test case, checklist or shared step by Id or GlobalId"""
    result = api("GET", f"/workItems/{item_id}")
    return json.dumps(result, ensure_ascii=False, indent=2)


@mcp.tool()
def search_work_items(
    project_ids: list[str] = None,
    section_ids: list[str] = None,
    name: str = None,
    states: list[str] = None,
    types: list[str] = None,
    skip: int = 0,
    take: int = 20
) -> str:
    """Search for work items (test cases) with filters.
    states: Ready, Draft, NeedsWork, Invalid
    types: TestCases, CheckLists, SharedSteps
    """
    body = {}
    if project_ids:
        body["projectIds"] = project_ids
    if section_ids:
        body["sectionIds"] = section_ids
    if name:
        body["name"] = name
    if states:
        body["states"] = states
    if types:
        body["entityTypes"] = types

    result = api("POST", f"/workItems/search?skip={skip}&take={take}", json=body)
    return json.dumps(result, ensure_ascii=False, indent=2)


@mcp.tool()
def update_work_item(
    item_id: str,
    name: str = None,
    description: str = None,
    state: str = None,
    steps: list[dict] = None,
    precondition_steps: list[dict] = None,
    postcondition_steps: list[dict] = None,
    priority: str = None,
) -> str:
    """Update a test case. First fetches current data, then patches it.
    state: Ready, Draft, NeedsWork, Invalid
    priority: Lowest, Low, Medium, High, Highest
    steps: list of {action, expected} dicts — main steps
    precondition_steps: list of {action, expected} dicts — preconditions
    postcondition_steps: list of {action, expected} dicts — postconditions
    """
    current = api("GET", f"/workItems/{item_id}")

    if name is not None:
        current["name"] = name
    if description is not None:
        current["description"] = description
    if state is not None:
        current["state"] = state
    if priority is not None:
        current["priority"] = priority
    if steps is not None:
        current["steps"] = [
            {"action": s.get("action", ""), "expected": s.get("expected", "")}
            for s in steps
        ]
    if precondition_steps is not None:
        current["preconditionSteps"] = [
            {"action": s.get("action", ""), "expected": s.get("expected", "")}
            for s in precondition_steps
        ]
    if postcondition_steps is not None:
        current["postconditionSteps"] = [
            {"action": s.get("action", ""), "expected": s.get("expected", "")}
            for s in postcondition_steps
        ]

    result = api("PUT", "/workItems", json=current)
    return json.dumps(result, ensure_ascii=False, indent=2)


# ── Projects & Sections ──────────────────────────────────────────────────────

@mcp.tool()
def get_projects() -> str:
    """Get list of all available projects"""
    result = api("GET", "/projects")
    return json.dumps(result, ensure_ascii=False, indent=2)


@mcp.tool()
def get_sections(project_id: str) -> str:
    """Get sections (folders) for a project"""
    result = api("GET", f"/sections?projectId={project_id}")
    return json.dumps(result, ensure_ascii=False, indent=2)


# ── Test Plans ────────────────────────────────────────────────────────────────

@mcp.tool()
def get_test_plans(
    project_id: str,
    name: str = None,
    is_archived: bool = False,
    skip: int = 0,
    take: int = 20
) -> str:
    """Get test plans for a project. Optionally filter by name substring.
    is_archived: False = active plans, True = archived
    Returns: id, name, status, build, startedOn, completedOn, counts (grouped by status)
    """
    body = {"isArchived": is_archived}
    if name:
        body["name"] = name
    result = api("POST", f"/projects/{project_id}/testPlans/search?skip={skip}&take={take}", json=body)
    # Return compact summary
    plans = result if isinstance(result, list) else result.get("items", result)
    summary = []
    for p in plans:
        analytic = p.get("analytic", {})
        counts = {s["status"]: s["value"] for s in analytic.get("countGroupByStatus", [])}
        summary.append({
            "id": p["id"],
            "globalId": p.get("globalId"),
            "name": p["name"],
            "status": p.get("status"),
            "build": p.get("build"),
            "startedOn": p.get("startedOn"),
            "completedOn": p.get("completedOn"),
            "counts": counts,
        })
    return json.dumps(summary, ensure_ascii=False, indent=2)


@mcp.tool()
def get_test_plan(plan_id: str) -> str:
    """Get a test plan by ID with full details and summary stats"""
    plan = api("GET", f"/testPlans/{plan_id}")
    summary = api("GET", f"/testPlans/{plan_id}/summaries")
    return json.dumps({"plan": plan, "summary": summary}, ensure_ascii=False, indent=2)


# ── Test Runs ─────────────────────────────────────────────────────────────────

@mcp.tool()
def get_test_runs(
    test_plan_id: str,
    skip: int = 0,
    take: int = 20
) -> str:
    """Get test runs (launches) for a test plan.
    Returns: id, name, status, build, startedDate, completedDate, analytic
    """
    result = api("POST", f"/testPlans/{test_plan_id}/testRuns/search?skip={skip}&take={take}", json={})
    runs = result if isinstance(result, list) else result.get("items", result)
    summary = []
    for r in runs:
        analytic = r.get("analytic") or {}
        counts = {}
        if isinstance(analytic, dict):
            counts = {s["status"]: s["value"] for s in analytic.get("countGroupByStatus", [])}
        summary.append({
            "id": r["id"],
            "name": r.get("name"),
            "status": r.get("status") or r.get("stateName"),
            "build": r.get("build"),
            "startedDate": r.get("startedDate"),
            "completedDate": r.get("completedDate"),
            "counts": counts,
        })
    return json.dumps(summary, ensure_ascii=False, indent=2)


# ── Test Results (points in a run) ────────────────────────────────────────────

@mcp.tool()
def get_plan_results(
    plan_id: str,
    status_filter: str = None,
    skip: int = 0,
    take: int = 50
) -> str:
    """Get all test point results for a test plan (last result per point).
    status_filter: Passed, Failed, Blocked, Skipped, InProgress, NoResults (optional)
    Returns: testPointId, workItemName, status, lastTestResultId — use lastTestResultId to read/update the result
    """
    params = f"?skip={skip}&take={take}"
    points = api("GET", f"/testPlans/{plan_id}/testPoints/lastResults{params}")
    if not isinstance(points, list):
        points = points.get("items", [])
    out = []
    for p in points:
        status = p.get("status") or (p.get("statusModel") or {}).get("name", "")
        if status_filter and status != status_filter:
            continue
        last = p.get("lastTestResult") or {}
        out.append({
            "testPointId": p.get("id"),
            "workItemName": p.get("workItemName"),
            "workItemId": p.get("workItemId"),
            "testerId": p.get("testerId"),
            "status": status,
            "lastTestResultId": last.get("id"),
            "testRunId": last.get("testRunId"),
        })
    return json.dumps(out, ensure_ascii=False, indent=2)


@mcp.tool()
def get_run_results(
    run_id: str,
    outcome_filter: str = None
) -> str:
    """Get all test point results for a standalone test run.
    outcome_filter: Passed, Failed, Blocked, Skipped, InProgress, NoResults (optional)
    Returns: testPointId, workItemGlobalId, workItemName, configurationName, aggregatedOutcome, lastTestResultId
    """
    results = api("GET", f"/testRuns/{run_id}/testPoints/results")
    points = results if isinstance(results, list) else results.get("items", results)
    out = []
    for p in points:
        outcome = p.get("aggregatedOutcome") or (p.get("aggregatedStatus") or {}).get("outcome", "")
        if outcome_filter and outcome != outcome_filter:
            continue
        last_result = p.get("testResults", [{}])
        last_id = last_result[-1].get("id") if last_result else None
        out.append({
            "testPointId": p.get("testPointId"),
            "workItemGlobalId": p.get("workItemGlobalId"),
            "workItemName": p.get("workItemName"),
            "configurationName": p.get("configurationName"),
            "outcome": outcome,
            "lastTestResultId": last_id,
        })
    return json.dumps(out, ensure_ascii=False, indent=2)


@mcp.tool()
def get_test_result(result_id: str) -> str:
    """Get full details of a single test result (outcome, comment, step results, linked work item)"""
    result = api("GET", f"/testResults/{result_id}")
    return json.dumps(result, ensure_ascii=False, indent=2)


@mcp.tool()
def update_test_result(
    result_id: str,
    outcome: str,
    comment: str = None,
    duration_ms: int = None,
) -> str:
    """Update outcome of a test result.
    outcome: Passed, Failed, Blocked, Skipped, InProgress
    comment: optional text comment
    duration_ms: optional duration in milliseconds
    """
    body = {"outcome": outcome}
    if comment is not None:
        body["comment"] = comment
    if duration_ms is not None:
        body["durationInMs"] = duration_ms
    result = api("PUT", f"/testResults/{result_id}", json=body)
    return json.dumps(result or {"status": "ok"}, ensure_ascii=False, indent=2)


@mcp.tool()
def search_test_results(
    test_run_ids: list[str] = None,
    outcomes: list[str] = None,
    skip: int = 0,
    take: int = 50
) -> str:
    """Search test results across runs with filters.
    outcomes: Passed, Failed, Blocked, Skipped, InProgress, NoResults
    """
    body = {}
    if test_run_ids:
        body["testRunIds"] = test_run_ids
    if outcomes:
        body["outcomes"] = outcomes
    result = api("POST", f"/testResults/search?skip={skip}&take={take}", json=body)
    return json.dumps(result, ensure_ascii=False, indent=2)


@mcp.tool()
def assign_tester(
    plan_id: str,
    user_id: str,
    test_point_ids: list[str] = None,
    work_item_global_ids: list[int] = None,
) -> str:
    """Assign a tester to test points in a test plan.
    plan_id: test plan UUID
    user_id: UUID of the user to assign
    test_point_ids: list of specific testPoint UUIDs (use get_plan_results to get them)
    work_item_global_ids: list of work item globalIds (e.g. [12345, 12346]) — alternative to test_point_ids
    At least one of test_point_ids or work_item_global_ids must be provided.
    """
    body = {}
    if test_point_ids:
        body["extractionModel"] = {"ids": {"includes": test_point_ids}}
    if work_item_global_ids:
        body["filter"] = {"workItemGlobalIds": work_item_global_ids}
    result = api("POST", f"/testPlans/{plan_id}/testPoints/tester/{user_id}", json=body)
    return json.dumps(result or {"status": "ok"}, ensure_ascii=False, indent=2)


@mcp.tool()
def get_users(project_id: str) -> str:
    """Get users (testers) available in a project.
    Note: may return 400 depending on instance permissions — use tester IDs from get_plan_results as an alternative.
    """
    result = api("GET", f"/projects/{project_id}/users")
    users = result if isinstance(result, list) else result.get("items", result)
    out = [{"id": u.get("id"), "name": u.get("userName") or u.get("displayName"), "email": u.get("email")} for u in users]
    return json.dumps(out, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    mcp.run()
