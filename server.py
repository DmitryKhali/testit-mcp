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

def headers_multipart():
    """No Content-Type here — requests sets the multipart boundary itself."""
    return {"Authorization": f"PrivateToken {get_token()}"}

def _request(url, method, **kwargs):
    resp = requests.request(method, url, headers=headers(), **kwargs)
    if resp.status_code >= 400:
        msg = f"API {method} {url} failed: {resp.status_code}"
        try:
            detail = resp.json()
            msg = f"{msg}\n{json.dumps(detail, ensure_ascii=False, indent=2)}"
        except Exception:
            msg = f"{msg}\n{resp.text}"
        raise Exception(msg)
    if resp.content:
        return resp.json()
    return {}

def _build_step(s: dict) -> dict:
    """Serialize one step for the TestIT API.
    SharedStep reference: {"workItemId": "<uuid>"}
      The server requires a populated "workItem" sibling — call _resolve_shared_steps()
      first so that field is already filled in before reaching here.
    Regular step: {"action": "...", "expected": "..."}
    """
    if s.get("workItemId"):
        step = {"workItemId": s["workItemId"]}
        if s.get("workItem"):
            step["workItem"] = s["workItem"]
        return step
    return {"action": s.get("action", ""), "expected": s.get("expected", "")}


def _resolve_shared_steps(steps: list[dict]) -> list[dict]:
    """Fetch SharedStep details for any step that has workItemId but no workItem.
    The PUT /workItems endpoint ignores workItemId unless workItem is populated.
    """
    out = []
    for s in steps:
        if s.get("workItemId") and not s.get("workItem"):
            try:
                shared = api("GET", f"/workItems/{s['workItemId']}")
                s = dict(s)
                s["workItem"] = {
                    "versionId": shared.get("versionId"),
                    "globalId": shared.get("globalId"),
                    "name": shared.get("name"),
                    "steps": shared.get("steps", []),
                }
            except Exception:
                pass
        out.append(s)
    return out


def api(method, path, **kwargs):
    return _request(f"{BASE_URL}/api/v2{path}", method, **kwargs)

def api_legacy(method, path, **kwargs):
    """Calls the non-versioned /api/* surface — used for the few actions
    (like manual bulk status updates) that the web UI relies on but that
    were never ported to /api/v2."""
    return _request(f"{BASE_URL}/api{path}", method, **kwargs)


# ── Work Items ───────────────────────────────────────────────────────────────

@mcp.tool()
def get_work_item(item_id: str) -> str:
    """Get a test case, checklist or shared step by Id or GlobalId"""
    result = api("GET", f"/workItems/{item_id}")
    return json.dumps(result, ensure_ascii=False, indent=2)


@mcp.tool()
def search_work_items(
    project_id: str = None,
    section_ids: list[str] = None,
    name: str = None,
    states: list[str] = None,
    types: list[str] = None,
    priorities: list[str] = None,
    tags: list[str] = None,
    ids: list[str] = None,
    skip: int = 0,
    take: int = 20
) -> str:
    """Search for work items (test cases) with filters.
    project_id: project UUID (required for correct section filtering)
    states: Ready, Draft, NeedsWork, Invalid
    types: TestCases, CheckLists, SharedSteps
    priorities: Lowest, Low, Medium, High, Highest
    tags: list of tag names to filter by (e.g. ['wave1'])
    ids: list of work item UUIDs to fetch
    Returns fields include: id, globalId, name, priority, sectionId, state, tags
    """
    if not project_id:
        raise ValueError("project_id is required for search")

    filter_obj = {"isDeleted": False}
    if section_ids:
        filter_obj["sectionIds"] = section_ids
    if name:
        filter_obj["name"] = name
    if states:
        filter_obj["states"] = states
    if types:
        filter_obj["entityTypes"] = types
    if priorities:
        filter_obj["priorities"] = priorities
    if tags:
        filter_obj["tags"] = tags
    if ids:
        filter_obj["ids"] = ids

    body = {"filter": filter_obj}
    result = api("POST", f"/projects/{project_id}/workItems/search?skip={skip}&take={take}", json=body)
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
    steps / precondition_steps / postcondition_steps: list of step dicts.
      Regular step:        {"action": "...", "expected": "..."}
      SharedStep reference: {"workItemId": "<SharedStep UUID>"}
        (action/expected are left empty; the content lives in the SharedStep itself)
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
        current["steps"] = [_build_step(s) for s in _resolve_shared_steps(steps)]
    if precondition_steps is not None:
        current["preconditionSteps"] = [_build_step(s) for s in _resolve_shared_steps(precondition_steps)]
    if postcondition_steps is not None:
        current["postconditionSteps"] = [_build_step(s) for s in _resolve_shared_steps(postcondition_steps)]

    result = api("PUT", "/workItems", json=current)
    return json.dumps(result, ensure_ascii=False, indent=2)


def _discover_project_attributes(project_id: str) -> dict:
    items = api("POST", f"/projects/{project_id}/workItems/search?skip=0&take=1", json={"filter": {"isDeleted": False}})
    if isinstance(items, list):
        items = items
    elif isinstance(items, dict):
        items = items.get("items", items.get("data", []))
    for item in items:
        attrs = item.get("attributes")
        if attrs:
            return attrs
    return {}


@mcp.tool()
def create_work_item(
    project_id: str,
    section_id: str,
    name: str,
    entity_type: str,
    steps: list[dict] = None,
    precondition_steps: list[dict] = None,
    postcondition_steps: list[dict] = None,
    state: str = "Ready",
    priority: str = "Medium",
    duration: int = 600000,
    description: str = None,
    attributes: dict = None,
    tag_names: list[str] = None,
) -> str:
    """Create a new work item (test case, checklist, or shared step).

    Args:
        project_id: UUID of the project
        section_id: UUID of the section (folder) to place the item in
        name: Title of the work item
        entity_type: TestCases, CheckLists, or SharedSteps
        steps: list of {action, expected} dicts — main steps
        precondition_steps: list of {action, expected} dicts — preconditions
        postcondition_steps: list of {action, expected} dicts — postconditions
        state: Ready, Draft, NeedsWork, Invalid (default: Ready)
        priority: Lowest, Low, Medium, High, Highest (default: Medium)
        duration: Duration in milliseconds (default: 600000 = 10 min). Applied via PUT after creation.
        description: Optional description text
        attributes: Optional map of project attributes
        tag_names: Optional list of tag names to attach
    """
    if attributes is None:
        attributes = _discover_project_attributes(project_id)

    body = {
        "projectId": project_id,
        "sectionId": section_id,
        "name": name,
        "entityType": entity_type,
        "entityTypeName": entity_type,
        "state": state,
        "priority": priority,
        "duration": 1,
        "attributes": attributes,
        "tags": tag_names or [],
        "links": [],
    }
    if description is not None:
        body["description"] = description
    body["steps"] = [_build_step(s) for s in _resolve_shared_steps(steps or [])]
    body["preconditionSteps"] = [_build_step(s) for s in _resolve_shared_steps(precondition_steps or [])]
    body["postconditionSteps"] = [_build_step(s) for s in _resolve_shared_steps(postcondition_steps or [])]

    result = api("POST", "/workItems", json=body)

    # TestIT ignores duration on create — fix it via PUT immediately
    target_duration = duration if duration and duration > 1 else 600000
    if result.get("duration", 1) != target_duration:
        result["duration"] = target_duration
        api("PUT", "/workItems", json=result)

    return json.dumps(result, ensure_ascii=False, indent=2)


@mcp.tool()
def add_attachment(work_item_id: str, file_path: str) -> str:
    """Upload a local file and link it as an attachment to a work item (test case,
    checklist, or shared step).

    Returns attachment metadata including its `id`. To embed the uploaded file as
    an inline image inside a step, precondition, or description, put an <img> tag
    referencing it directly into that field's HTML via update_work_item, e.g.:
        <img src="/api/v2/attachments/{id}">

    work_item_id: UUID of the work item (globalId does not work here, must be the UUID —
      get it from get_work_item's "id" field)
    file_path: absolute local path to the file to upload
    """
    with open(file_path, "rb") as f:
        filename = os.path.basename(file_path)
        resp = requests.post(
            f"{BASE_URL}/api/v2/workItems/{work_item_id}/attachments",
            headers=headers_multipart(),
            files={"file": (filename, f)},
        )
    if resp.status_code >= 400:
        msg = f"API POST /workItems/{work_item_id}/attachments failed: {resp.status_code}"
        try:
            detail = resp.json()
            msg = f"{msg}\n{json.dumps(detail, ensure_ascii=False, indent=2)}"
        except Exception:
            msg = f"{msg}\n{resp.text}"
        raise Exception(msg)
    return json.dumps(resp.json() if resp.content else {"status": "ok"}, ensure_ascii=False, indent=2)


# ── Projects & Sections ──────────────────────────────────────────────────────

@mcp.tool()
def get_projects() -> str:
    """Get list of all available projects"""
    result = api("GET", "/projects")
    return json.dumps(result, ensure_ascii=False, indent=2)


@mcp.tool()
def get_sections(project_id: str) -> str:
    """Get sections (folders) for a project"""
    result = api("GET", f"/Sections?projectId={project_id}")
    return json.dumps(result, ensure_ascii=False, indent=2)


@mcp.tool()
def create_section(
    project_id: str,
    name: str,
    parent_id: str = None,
) -> str:
    """Create a section (folder) in a project's test case tree.

    Args:
        project_id: UUID of the project
        name: Section name
        parent_id: UUID of the parent section (omit for root level)

    Returns section id, name, projectId.
    """
    body: dict = {"name": name, "projectId": project_id}
    if parent_id:
        body["parentId"] = parent_id
    result = api("POST", "/Sections", json=body)
    return json.dumps(result, ensure_ascii=False, indent=2)


@mcp.tool()
def move_work_items(
    target_section_id: str,
    project_id: str,
    work_item_ids: list[str] = None,
    source_section_ids: list[str] = None,
    exclude_ids: list[str] = None,
) -> str:
    """Move work items into a target section (folder).

    Two modes:
    1. By specific IDs — provide work_item_ids: list of work item UUIDs to move.
    2. By source section — provide source_section_ids: moves all items from those
       sections into the target. Use exclude_ids to skip specific items.

    At least one of work_item_ids or source_section_ids must be provided.

    target_section_id: UUID of the destination section
    project_id: project UUID
    work_item_ids: specific work item UUIDs to move
    source_section_ids: move all items from these source sections
    exclude_ids: item UUIDs to exclude (used with source_section_ids)
    """
    if not work_item_ids and not source_section_ids:
        raise ValueError("Provide work_item_ids or source_section_ids")

    if work_item_ids:
        extraction = {
            "ids": {"include": work_item_ids, "exclude": []},
            "projectIds": {"include": [project_id]},
        }
        filter_body = {"isDeleted": False, "sectionIds": []}
    else:
        extraction = {
            "ids": {"include": [], "exclude": exclude_ids or []},
            "projectIds": {"include": [project_id]},
        }
        filter_body = {"isDeleted": False, "sectionIds": source_section_ids}

    body = {"extractionModel": extraction, "filter": filter_body}
    result = api_legacy("POST", f"/Sections/{target_section_id}/move-workItems", json=body)
    return json.dumps(result or {"status": "ok"}, ensure_ascii=False, indent=2)


@mcp.tool()
def rename_section(section_id: str, name: str) -> str:
    """Rename a section (folder) in TestIT.

    section_id: UUID of the section to rename
    name: new name (max 255 characters)
    """
    result = api("POST", "/sections/rename", json={"id": section_id, "name": name})
    return json.dumps(result or {"status": "ok"}, ensure_ascii=False, indent=2)


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
def set_test_point_status(
    plan_id: str,
    project_id: str,
    status_code: str,
    test_point_ids: list[str] = None,
    work_item_global_ids: list[int] = None,
) -> str:
    """Set the manual status of test points in a test plan run.

    Works for ANY test point regardless of whether it already has a result —
    on first use it transparently creates the test run behind the plan
    (get_test_runs returns [] until then) and a result for each selected
    point; on later calls it updates the existing result. This mirrors what
    the web UI's status dropdown does, since TestIT never exposed this as a
    versioned /api/v2 endpoint.

    plan_id: test plan UUID
    project_id: project UUID (the plan belongs to)
    status_code: INPROGRESS, PASSED, FAILED, BLOCKED, SKIPPED
        (there is no settable code for "Ожидает"/NotStarted — that status
        only exists for points that have never received a result; the
        plan's /testPoints/reset endpoint did not revert a point back to it
        in testing, so treat status changes here as one-directional)
    test_point_ids: list of specific testPoint UUIDs (use get_plan_results to get them)
    work_item_global_ids: list of work item globalIds (e.g. [12345, 12346]) — alternative to test_point_ids
    At least one of test_point_ids or work_item_global_ids must be provided.
    """
    if not test_point_ids and not work_item_global_ids:
        raise ValueError("Provide test_point_ids or work_item_global_ids")

    selector = {"filter": {}, "extractionModel": {}}
    if test_point_ids:
        selector["extractionModel"] = {"ids": {"include": test_point_ids, "exclude": []}}
    if work_item_global_ids:
        selector["filter"] = {"workItemGlobalIds": work_item_global_ids}

    body = {
        "name": None,
        "isAutomated": False,
        "stateName": "NotStarted",
        "entityTypeName": "TestRuns",
        "autoTests": [],
        "runByUserId": None,
        "stoppedByUserId": None,
        "build": "DEFAULT",
        "description": "",
        "launchSource": "Source",
        "autoTestsCount": 0,
        "createdByUserName": "",
        "projectId": project_id,
        "testPlanId": plan_id,
        "testPointIds": [],
        "tags": [],
        "manualTestResult": {"statusCode": status_code},
        "testPointsSelector": selector,
    }
    result = api_legacy("POST", "/TestPoints/results/manual/bulk", json=body)
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
        body["extractionModel"] = {"ids": {"include": test_point_ids}}
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
