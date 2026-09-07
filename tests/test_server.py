"""Does the site actually work.

The other suite checks the maths. This one checks the thing a person touches: a
real server on a real port, every endpoint answering, the checkbox writing to
disk and surviving a reload, and the agent failing in a way somebody can read
rather than a stack trace in the browser.

It starts the actual server rather than calling handlers directly, because half
the ways a demo dies are in the wiring: a route that was never registered, JSON
that will not serialise, a stream that closes early.
"""

import json
import os
import socket
import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

import pytest


@pytest.fixture(scope="module")
def site(tmp_path_factory):
    """The real server, on a free port, with its own ticket store."""
    root = tmp_path_factory.mktemp("t")
    os.environ["TICKETS_FILE"] = str(root / "tickets.json")
    # The agent test runs a real run, and a real run writes a journal entry.
    # Left pointing at the repo, the suite would quietly append to the diary the
    # demo shows.
    os.environ["JOURNAL_FILE"] = str(root / "journal.jsonl")
    # Confirming a cost persists it. Left pointing at the repo the suite writes
    # into the demo shop, and the run after it skips because the question it
    # meant to ask has already been answered.
    os.environ["COSTS_FILE"] = str(root / "costs.json")
    import importlib
    from src.bakery import team as tickets, journal, paths
    importlib.reload(paths)
    importlib.reload(tickets)
    importlib.reload(journal)

    from ui import app
    importlib.reload(app)

    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()

    server = ThreadingHTTPServer(("127.0.0.1", port), app.Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{port}"
    server.shutdown()


def get(site, path):
    with urllib.request.urlopen(site + path, timeout=180) as response:
        return response.status, response.read(), response.headers


def post(site, path, payload):
    request = urllib.request.Request(
        site + path, data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=180) as response:
            return response.status, json.loads(response.read())
    except urllib.error.HTTPError as error:
        return error.code, json.loads(error.read())


# ── it serves ───────────────────────────────────────────────────────────────

def test_the_page_loads(site):
    status, body, headers = get(site, "/")
    assert status == 200
    assert "text/html" in headers["Content-Type"]
    page = body.decode("utf-8")
    assert "<canvas id=\"shader\"" in page, "the background never made it"
    assert page.count('role="tab"') == 5, "a page went missing from the nav"


@pytest.mark.parametrize("path", [
    "/api/overview", "/api/today", "/api/plan", "/api/team", "/api/source",
    "/api/trends", "/api/sellers", "/api/lost", "/api/calendar", "/api/outbox",
    "/api/day", "/api/occasion?name=Halloween",
])
def test_every_endpoint_answers_with_json(site, path):
    status, body, headers = get(site, path)
    assert status == 200, path
    assert "application/json" in headers["Content-Type"], path
    json.loads(body)                       # raises if a date leaked through


def test_the_report_is_a_printable_page(site):
    status, body, headers = get(site, "/api/report")
    assert status == 200
    assert "text/html" in headers["Content-Type"]
    assert b"@media print" in body, "it would print badly"


def test_an_unknown_route_says_so(site):
    with pytest.raises(urllib.error.HTTPError) as raised:
        get(site, "/api/nothing-here")
    assert raised.value.code == 404


# ── the numbers on the page are real ───────────────────────────────────────

def test_today_carries_what_the_page_shows(site):
    _, body, _ = get(site, "/api/today")
    day = json.loads(body)
    assert day["customers"] > 0 and day["units"] > 0
    assert day["rows"], "no products at all"
    for row in day["rows"]:
        assert row["sold"] > 0
        if row["ran_out"]:
            assert row["ran_out_at"], "flagged as out with no time"


def test_the_page_agrees_with_itself(site):
    """Every product the day reports has to be on the menu the page was given.

    These come from different endpoints and different code paths, and they
    disagreed once already: the menu was built from baked goods only, so coffee
    sold all day and appeared nowhere in the list of what the shop sells.
    """
    _, body, _ = get(site, "/api/overview")
    menu = {row["name"] for row in json.loads(body)["menu"]}
    _, body, _ = get(site, "/api/today")
    sold = {row["item"] for row in json.loads(body)["rows"]}
    _, body, _ = get(site, "/api/plan")
    planned = {row["item"] for row in json.loads(body)["rows"]}

    assert sold <= menu, f"sold but not on the menu: {sorted(sold - menu)}"
    assert planned <= menu, f"planned but not on the menu: {sorted(planned - menu)}"
    assert "Coffee" not in planned, "coffee is not a production decision"


def test_overview_is_one_call_with_everything_the_page_needs(site):
    _, body, _ = get(site, "/api/overview")
    data = json.loads(body)
    for key in ("shop", "today", "currency", "nightly", "weekly"):
        assert key in data, key
    assert data["nightly"]["plan"]["rows"], "no plan to show"


# ── the checkbox has a backend ─────────────────────────────────────────────

def test_ticking_a_job_persists(site):
    _, body, _ = get(site, "/api/team")
    board = json.loads(body)
    job = next(j for person in board["board"] for j in person["jobs"])
    assert job["done"] is False

    status, result = post(site, "/api/tickets", {"id": job["id"], "done": True})
    assert status == 200 and result["ok"]

    _, body, _ = get(site, "/api/team")
    again = json.loads(body)
    same = next(j for person in again["board"] for j in person["jobs"]
                if j["id"] == job["id"])
    assert same["done"] is True, "the tick did not survive a reload"
    assert again["progress"]["done"] >= 1


def test_unticking_puts_it_back(site):
    _, body, _ = get(site, "/api/team")
    job = next(j for person in json.loads(body)["board"] for j in person["jobs"])
    post(site, "/api/tickets", {"id": job["id"], "done": True})
    post(site, "/api/tickets", {"id": job["id"], "done": False})
    _, body, _ = get(site, "/api/team")
    same = next(j for person in json.loads(body)["board"] for j in person["jobs"]
                if j["id"] == job["id"])
    assert same["done"] is False


def test_a_bad_tick_is_refused_with_something_readable(site):
    status, result = post(site, "/api/tickets", {"done": True})
    assert status == 400
    assert "id" in result["error"]
    assert "example" in result, "an error should show what right looks like"


def test_the_confirm_checklist_reaches_the_counter(site):
    """Whoever closes up gets the sell-outs to confirm, each individually
    tickable, because the agent inferred them and only a person can settle it."""
    _, body, _ = get(site, "/api/team")
    board = json.loads(body)
    checks = [j for person in board["board"] for j in person["jobs"]
              if j["kind"] == "check"]
    assert checks, "nobody was asked to confirm what ran out"
    for row in checks[0].get("detail", []):
        assert row["id"] and row["item"] and row["at"]
        status, _ = post(site, "/api/tickets", {"id": row["id"], "done": True})
        assert status == 200


# ── the agent endpoint ─────────────────────────────────────────────────────

def test_agent_streams_and_fails_readably_without_a_model(site):
    """Until a provider is configured this is the expected path, and the demo
    must degrade into a sentence rather than a stack trace."""
    request = urllib.request.Request(
        site + "/api/agent", data=json.dumps({"kind": "nightly"}).encode(),
        headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(request, timeout=300) as response:
        assert response.status == 200
        assert "ndjson" in response.headers["Content-Type"]
        events = [json.loads(line) for line in response.read().splitlines() if line]

    assert events[0]["kind"] == "started"
    last = events[-1]
    assert last["kind"] in ("done", "failed")
    if last["kind"] == "failed":
        assert last["error"] and last["hint"], "a failure with nothing to do next"
    else:
        assert last["ledger"]["tool_calls"] >= 0


# ── the diary, which is where the autonomy claim is evidenced ──────────────

def test_journal_endpoint_carries_what_the_header_counts(site):
    _, body, _ = get(site, "/api/journal")
    data = json.loads(body)
    for key in ("runs", "spoke", "cost_usd", "entries"):
        assert key in data, key
    assert data["spoke"] <= data["runs"], "spoke more often than it woke"
    for entry in data["entries"]:
        assert entry["at"] and entry["did"] and entry["why"]
        assert isinstance(entry["spoke"], bool)


def test_the_diary_list_matches_the_count_above_it(site):
    """The heading says how many wakings there were in seven days and the list
    beneath it shows them. Letting the list run past that window puts a visible
    contradiction on the page."""
    _, body, _ = get(site, "/api/journal")
    data = json.loads(body)
    assert len(data["entries"]) == data["runs"], (
        f"heading says {data['runs']} wakings, list shows "
        f"{len(data['entries'])}")


def test_looking_at_the_page_is_not_a_run(site):
    """The header counts how often the agent woke. Rendering a dashboard is not
    waking, and letting a page load bump that number would fabricate the one
    figure the whole product is judged on.
    """
    _, body, _ = get(site, "/api/journal")
    before = json.loads(body)["runs"]
    for _ in range(3):
        get(site, "/api/overview")
    _, body, _ = get(site, "/api/journal")
    assert json.loads(body)["runs"] == before, "a page load counted as a run"


def test_no_two_functions_share_a_name():
    """A redefined function silently wins, and the caller of the first one gets
    the second one's argument shape. That is how the diary page started
    rendering the journal renderer with a list of occasions and threw on load.
    """
    import re
    from collections import Counter

    page = open("ui/index.html", encoding="utf-8").read()
    names = re.findall(r'^\s*function\s+([A-Za-z_$][\w$]*)\s*\(', page, re.M)
    clashes = [name for name, count in Counter(names).items() if count > 1]
    assert not clashes, f"defined twice in the page: {clashes}"


def test_every_read_only_agent_tool_actually_runs(site):
    """The tools are the agent's only contact with the shop, and nothing
    exercises them until a model is configured. ``shop_status``, the one the
    prompt tells it to call first, raised AttributeError for a helper that was
    never written, and no test or page touched it.

    Anything with a side effect or a network call is left out on purpose.
    """
    import inspect
    from src.bakery import agent

    skip = set(agent.ACTIONS) | {"run_python", "find_local_events"}
    ran, failed = [], []
    for handle in agent.TOOLS:
        name = getattr(handle, "tool_name", getattr(handle, "__name__", "?"))
        if name in skip:
            continue
        function = (getattr(handle, "_tool_func", None)
                    or getattr(handle, "__wrapped__", None) or handle)
        try:
            needed = [p for p in inspect.signature(function).parameters.values()
                      if p.default is p.empty]
        except (TypeError, ValueError):
            continue
        if needed:
            continue
        try:
            function()
            ran.append(name)
        except Exception as error:
            failed.append(f"{name}: {type(error).__name__}: {error}")

    assert not failed, "agent tools that raise: " + "; ".join(failed)
    assert len(ran) >= 6, f"only exercised {ran}, which is not coverage"


def test_the_way_in_is_on_the_page(site):
    """A first visit lands on the welcome, not on five tabs of numbers. It has
    to be in the served HTML rather than added later by a script that might not
    run."""
    _, body, _ = get(site, "/")
    page = body.decode("utf-8")
    assert 'id="welcome"' in page, "no way in at all"
    assert 'id="wFill"' in page, "the loading bar went missing"
    assert page.count('id="welcome"') == 1


def test_a_confirmed_cost_changes_what_the_setup_page_asks_for(site):
    """The first conversation has to shrink as it is answered, or the owner is
    being asked the same thing every time they open it."""
    _, body, _ = get(site, "/api/setup")
    before = json.loads(body)
    if not before["needs_you"]:
        pytest.skip("every cost is already confirmed")

    item = before["needs_you"][0]
    status, result = post(site, "/api/costs",
                          {"item": item["item"], "cost": item["assumed_cost"]})
    assert status == 200 and result["ok"]

    _, body, _ = get(site, "/api/setup")
    after = json.loads(body)
    assert len(after["needs_you"]) == len(before["needs_you"]) - 1
    assert after["answered"] == before["answered"] + 1
    assert item["item"] not in [row["item"] for row in after["needs_you"]]


def test_a_cost_above_the_price_is_refused_with_a_reason(site):
    status, result = post(site, "/api/costs", {"item": "Croissant", "cost": 99})
    assert status == 400
    assert "not below" in result["error"]


def test_the_board_does_not_pile_work_on_the_owner(site):
    """The product exists to take work off the owner. Three run-up tasks on
    their board is the opposite, and it is what happened when the board pulled
    forty-five days of calendar instead of today's work."""
    _, body, _ = get(site, "/api/team")
    board = json.loads(body)["board"]

    owner = [p for p in board if p["role"] == "owner"]
    assert owner, "no owner on the board at all"
    assert len(owner[0]["jobs"]) <= 1, (
        f"the owner has {len(owner[0]['jobs'])} jobs, which is not relief")

    seen = {}
    for person in board:
        for job in person["jobs"]:
            if job["kind"] != "prep":
                continue
            assert job["what"] not in seen, (
                f"{job['what']!r} is on both {seen[job['what']]} and "
                f"{person['name']}")
            seen[job["what"]] = person["name"]
