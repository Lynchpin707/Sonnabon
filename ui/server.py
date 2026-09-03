"""Serves the interface and runs real requests through the bureau.

Standard library only, so there is nothing new to install. Every number this
returns comes from src/, not from the browser: the tier is the routing
decision, the cost is the provider's own token counts read by the Strands
hooks, and the history is the ledger.

    python ui/server.py            # local Ollama, costs nothing
    USE_AWS=true python ui/server.py

Then open http://localhost:8756
"""

import json
import mimetypes
import sys
import time
from dataclasses import asdict
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

from src import (agents, bureau, config, forensics, memory,  # noqa: E402
                 pipeline, provider, router, settings)

USER = "demo"
PORT = 8756
TITLES = HERE / ".titles.json"
DAY, MONTH = 86400, 2592000


def titles():
    try:
        return json.loads(TITLES.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def remember_title(request_id, text):
    index = titles()
    index[request_id] = text[:160]
    TITLES.write_text(json.dumps(index), encoding="utf-8")


def day_of(at):
    """Today and Yesterday read better than a date on a short list."""
    days = int(time.time() // DAY) - int(at // DAY)
    return {0: "Today", 1: "Yesterday"}.get(
        days, time.strftime("%d %b", time.localtime(at)))


def state():
    """Everything the console shows, and nothing it could have made up.

    The saving compares one window against itself: what these requests cost,
    against what the same tokens would have cost on the model the person would
    otherwise have opened. Comparing spend in one window against a baseline
    drawn from all of history would report a number that means nothing.
    """
    index = titles()
    rated = {f.request_id: f.rating for f in memory.ratings(USER)}
    history = []
    now = time.time()
    spent = {DAY: 0.0, MONTH: 0.0}
    baseline = {DAY: 0.0, MONTH: 0.0}

    for record in sorted(memory.history(USER), key=lambda r: r.at, reverse=True):
        age = now - record.at
        for window in (DAY, MONTH):
            if age < window:
                spent[window] += record.total_cost
                baseline[window] += record.baseline_cost
        history.append({
            "id": record.request_id,
            "day": day_of(record.at),
            "title": index.get(record.request_id, record.domain.replace("_", " ")),
            "tier": record.ran_tier,
            "asked": record.tier,
            "cost": record.total_cost,
            "decided": record.decided_cost,
            "baseline": record.baseline_cost,
            "saved": record.saved,
            "calls": record.calls,
            "domain": record.domain,
            "rating": rated.get(record.request_id),
        })

    ready, detail = provider.health()
    # Short enough for the sidebar; the full sentence, with what to do about
    # it, stays available on backend_detail.
    where = "bedrock" if config.USE_AWS else "ollama"
    month, month_baseline = spent[MONTH], baseline[MONTH]
    return {
        "history": history,
        "today": spent[DAY],
        "month": month,
        "baseline": month_baseline,
        "saved": round(100 * (1 - month / month_baseline), 1)
        if month_baseline > 0 else None,
        "ceiling": config.CEILING,
        "habit": config.HABIT_TIER,
        "habit_model": config.PRICED[config.HABIT_TIER].id,
        "ready": ready,
        "backend": f"{where} · {'ready' if ready else 'offline'}",
        "backend_detail": detail,
        "models": {tier: model.id for tier, model in config.MODELS.items()},
    }


def ask(text, approved, forced=None):
    """Run one request. Returns the payload the browser gets.

    Nobody is asked to choose between the agent team and the fast path. The
    team costs about six model calls and the fast path costs one, so that is a
    latency decision as much as a cost one, and the system owns it. The answer
    says which ran, because a choice made for you should still be visible.

    When the request needs the owner's say-so this returns the question rather
    than the answer, and runs nothing. A gate the server can answer on the
    user's behalf is not a gate.
    """
    if forced:
        # An override is the person's own decision, so skip classification and
        # run the tier they asked for. It is still recorded the same way.
        decision = router.Decision(forced, "override", "low", text)
    else:
        decision, _ = router.decide(text)

    if bureau.needs_approval(decision) and not approved:
        return {"needs_approval": {
            "tier": decision.tier,
            "risk": decision.risk,
            "domain": decision.domain,
            "model": config.PRICED[decision.tier].id,
            "ceiling": config.CEILING,
        }}

    approve = (lambda _: True) if approved else None

    if not forced and router.needs_team(decision):
        case = agents.handle(text, user=USER, approve=approve)
        if not case.approved:
            return {"declined": True}
        return _payload(text, case.record, case.answer, case.decision, "team",
                        [asdict(call) for call in case.calls],
                        [asdict(block) for block in case.blocks])

    result = pipeline.run(text, user=USER, approve=approve, tier=forced)
    if not result.approved:
        return {"declined": True}
    return _payload(text, result.record, result.text, result.decision, "fast",
                    [], [], ask_rating=result.ask_rating)


def _payload(text, record, answer, decision, path, calls, blocks, ask_rating=False):
    remember_title(record.request_id, text)
    return {
        "id": record.request_id,
        "text": answer,
        "path": path,
        "tier": record.ran_tier,
        "asked": decision.tier,
        "domain": decision.domain,
        "risk": decision.risk,
        "cost": record.total_cost,
        "decided": record.decided_cost,
        "baseline": record.baseline_cost,
        "saved": record.saved,
        "input_tokens": record.input_tokens,
        "output_tokens": record.output_tokens,
        "calls": calls,
        "blocks": blocks,
        "ask_rating": ask_rating,
    }


def credentials():
    """Whether a backend is reachable, said plainly, with what to do about it.

    This never asks for a key. AWS credentials come from the standard chain,
    and a web form is the wrong place to type a secret.
    """
    ready, message = provider.health()
    return {"ready": ready, "message": message,
            "how": "Credentials come from the AWS chain: environment "
                   "variables, ~/.aws/credentials, or an IAM role. Run "
                   "'aws configure'. TBI never stores them."}


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def _send(self, code, body, ctype="application/json"):
        payload = body if isinstance(body, bytes) else json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def do_GET(self):
        path = self.path.split("?")[0]
        if path == "/api/state":
            return self._send(200, state())
        if path == "/api/usage":
            return self._send(200, memory.usage(USER))
        if path == "/api/settings":
            return self._send(200, {**settings.load(), "backend_status": credentials()})
        if path == "/api/forensics":
            try:
                return self._send(200, {"note": forensics.review(USER) or None})
            except Exception as exc:
                return self._send(200, {"error": f"{type(exc).__name__}: {exc}"})

        name = "index.html" if path == "/" else path.lstrip("/")
        target = (HERE / name).resolve()
        if not str(target).startswith(str(HERE)) or not target.is_file():
            return self._send(404, {"error": "not found"})
        ctype = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
        self._send(200, target.read_bytes(), ctype)

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        try:
            body = json.loads(self.rfile.read(length) or "{}")
        except json.JSONDecodeError:
            return self._send(400, {"error": "bad json"})

        if self.path == "/api/settings":
            try:
                saved = settings.save(body)
            except (ValueError, KeyError, TypeError) as exc:
                return self._send(400, {"error": str(exc)})
            return self._send(200, {**saved, "backend_status": credentials()})

        if self.path == "/api/rate":
            memory.rate(body["id"], USER, body["tier"], body["rating"],
                        body.get("comment", ""))
            return self._send(200, {"ok": True})

        if self.path != "/api/ask":
            return self._send(404, {"error": "not found"})

        text = (body.get("text") or "").strip()
        if not text:
            return self._send(400, {"error": "empty request"})

        try:
            payload = ask(text, bool(body.get("approved")), body.get("tier"))
        except provider.BackendUnavailable as exc:
            return self._send(200, {"error": str(exc)})
        except Exception as exc:  # the browser needs to say what broke
            return self._send(200, {"error": f"{type(exc).__name__}: {exc}"})
        return self._send(200, payload)


if __name__ == "__main__":
    settings.apply()
    ready, where = provider.health()
    print(f"TBI on http://localhost:{PORT}")
    print(f"  backend  {where}{'' if ready else '   [not ready]'}")
    print(f"  ceiling  {config.CEILING}   habit {config.HABIT_TIER}   "
          f"case budget ${bureau.CASE_BUDGET:.2f}")
    ThreadingHTTPServer(("127.0.0.1", PORT), Handler).serve_forever()
