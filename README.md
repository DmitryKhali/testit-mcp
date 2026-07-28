# testit-mcp

MCP server for [Test IT](https://testit.ru) — connects Claude to your Test IT instance so you can read test cases, manage test plans, assign testers, and update results without leaving the chat.

## What it does

- Browse projects, sections, and test cases
- Create test cases, checklists, and shared steps
- Search and read test cases (work items) by name or globalId
- View test plans with progress analytics
- Get test point results per plan or run
- Update test case content (steps, preconditions, postconditions, state, priority)
- Change test result outcomes (In Progress / Passed / Failed / Blocked / Skipped) on any test point, started or not
- Assign testers to test points in a plan

## Requirements

- Python 3.11+
- Test IT instance (self-hosted or cloud)
- Test IT API token (PrivateToken)
- Claude Desktop with MCP support

## Installation

```bash
git clone https://github.com/your-username/testit-mcp.git
cd testit-mcp

python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

## Configuration

### 1. Store your API token

The server reads the token from macOS Keychain. Add it once:

```bash
security add-generic-password \
  -a "$USER" \
  -s "testit-mcp" \
  -w "YOUR_PRIVATE_TOKEN"
```

To get your token: Test IT → Profile → API Tokens → Generate.

### 2. Add to Claude Desktop

Edit `~/Library/Application Support/Claude/claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "testit": {
      "command": "/path/to/testit-mcp/venv/bin/python",
      "args": ["/path/to/testit-mcp/server.py"],
      "env": {
        "TESTIT_BASE_URL": "https://your-testit-instance.example.com"
      }
    }
  }
}
```

Restart Claude Desktop. The `testit` tools will appear automatically.

## Available tools

| Tool | Description |
|---|---|
| `get_projects` | List all projects |
| `get_sections` | Get sections (folders) for a project |
| `create_work_item` | Create a test case, checklist, or shared step |
| `get_work_item` | Get a test case by UUID or globalId |
| `search_work_items` | Search test cases by name, state, type |
| `update_work_item` | Update steps, preconditions, state, priority |
| `get_test_plans` | List test plans for a project (with analytics) |
| `get_test_plan` | Get plan details + summary stats |
| `get_test_runs` | List runs for a test plan |
| `get_plan_results` | Test point results for a plan (filterable by status) |
| `get_run_results` | Test point results for a standalone run |
| `get_test_result` | Full details of a single result |
| `set_test_point_status` | Set status of any test point in a plan, even ones with no result yet |
| `update_test_result` | Set outcome and comment on an existing result |
| `search_test_results` | Search results by run and outcome |
| `assign_tester` | Assign a tester to test points in a plan |
| `get_users` | List project users (may require elevated permissions) |
| `move_work_items` | Move work items between sections |
| `rename_section` | Rename a section (folder) |
| `add_attachment` | Upload a local file and link it to a work item |

## Usage examples

**Create a checklist:**
> "Create a checklist 'Login flow' in the Authentication section with steps: open login page, enter credentials, verify success"

**Read a test case:**
> "Show me test case 12345"

**Check plan progress:**
> "What's the progress on the 2.0.0 Regression plan?"

**Update a result:**
> "Mark this test case as Passed, add comment 'verified on device'"

**Start working a case in a plan:**
> "Set test case 12345 to In Progress in the regression plan"

**Assign a tester:**
> "Assign John to test cases 12345 and 12346 in the regression plan"

**Team progress report:**
> "Build a progress report for the team this week"

## Token security

The API token is stored in macOS Keychain and never written to disk or passed as a command-line argument. The server retrieves it at runtime via `security find-generic-password`.

If you're running this on a non-macOS system, replace `get_token()` in `server.py` with your preferred secret management approach (e.g. environment variable, secrets manager).

## License

MIT
