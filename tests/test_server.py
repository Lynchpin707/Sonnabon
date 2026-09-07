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
    os.environ["TICKETS_FILE"] = str(tmp_path_factory.mktemp("t") / "tickets.json")
    import importlib
    from src.bakery import team as tickets
    importlib.reload(tickets)

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
