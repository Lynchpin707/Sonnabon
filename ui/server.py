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
import threading
import time
from dataclasses import asdict
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

from src import (bureau, config, forensics, memory,  # noqa: E402
                 pipeline, provider, router, settings)

USER = "demo"
PORT = 8756
TRANSCRIPT = HERE / ".cases.json"
DAY, MONTH = 86400, 2592000


def transcript():
    """What was said, per case. The ledger holds what it cost; this holds what
    it was. Keeping them apart is why no figure here can come from the text."""
    try:
        return json.loads(TRANSCRIPT.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def remember(case_id, turn):
    saved = transcript()
    saved.setdefault(case_id, []).append(turn)
    TRANSCRIPT.write_text(json.dumps(saved), encoding="utf-8")


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
    said = transcript()
    rated = {f.request_id: f.rating for f in memory.ratings(USER)}
    now = time.time()
    spent = {DAY: 0.0, MONTH: 0.0}
    baseline = {DAY: 0.0, MONTH: 0.0}

    for record in memory.history(USER):
        age = now - record.at
        for window in (DAY, MONTH):
            if age < window:
                spent[window] += record.total_cost
                baseline[window] += record.baseline_cost

    history = []
    for case in memory.cases(USER):
        turns = said.get(case["case_id"], [])
        opening = next((t["text"] for t in turns if t["role"] == "you"), None)
        last = next((t for t in reversed(turns) if t["role"] == "tbi"), {})
        history.append({
            "id": case["case_id"],
            "day": day_of(case["at"]),
            "title": opening or case["domain"].replace("_", " "),
            "tier": case["tier"],
            "turns": case["turns"],
            "cost": case["cost"],
            "baseline": case["baseline"],
            "saved": max(case["baseline"] - case["cost"], 0.0),
            "calls": case["calls"],
            "domain": case["domain"],
            "rating": rated.get(last.get("id")),
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


def ask(text, approved, forced=None, watch=None, case_id=None):
    """Run one request. Returns the payload the browser gets.

    Nobody is asked to choose between the agent team and one agent. The team
    costs about six model calls and a solo agent costs one, so that is a
    latency decision as much as a cost one, and the system owns it. The answer
    says which ran, because a choice made for you should still be visible.

    Classification happens once, inside pipeline.run. Asking here as well
    would spend a second classifier call that the cache would hide and the
    ledger would never see.
    """
    result = pipeline.run(text, user=USER, tier=forced, watch=watch,
                          case_id=case_id,
                          approve=(lambda _: True) if approved else None)

    if not result.approved:
        if approved:
            return {"declined": True, "case_id": result.case_id}
        return {"case_id": result.case_id, "needs_approval": {
            "tier": result.decision.tier,
            "risk": result.decision.risk,
            "domain": result.decision.domain,
            "model": config.PRICED[result.decision.tier].id,
            "ceiling": config.CEILING,
        }}

    return _payload(text, result, [asdict(c) for c in result.calls],
                    [asdict(b) for b in result.blocks])


def _payload(text, result, calls, blocks):
    record, decision = result.record, result.decision
    remember(result.case_id, {"role": "you", "text": text, "id": record.request_id})
    remember(result.case_id, {
        "role": "tbi", "text": result.text, "id": record.request_id,
        "tier": record.ran_tier, "cost": record.total_cost,
        "baseline": record.baseline_cost, "path": result.path,
        "calls": calls, "blocks": blocks,
    })
    return {
        "id": record.request_id,
        "case_id": result.case_id,
        "turns": len(transcript().get(result.case_id, [])),
        "text": result.text,
        "path": result.path,
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
        "ask_rating": result.ask_rating,
    }


def credentials(fresh=False):
    """Whether a backend is reachable, said plainly, with what to do about it.

    This never asks for a key. AWS credentials come from the standard chain,
    and a web form is the wrong place to type a secret.
    """
    ready, message = provider.health(fresh=fresh)
    return {"ready": ready, "message": message,
            "how": "Credentials come from the AWS chain: environment "
                   "variables, ~/.aws/credentials, or an IAM role. Run "
                   "'aws configure'. TBI never stores them."}


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def _stream(self, body, text):
        """One line of JSON per step, then one carrying the answer.

        The hooks fire on the agent loop's own threads, so the write is behind
        a lock. Two agents finishing at once would otherwise interleave halfway
        through a line and the browser would see torn JSON.
        """
        self.send_response(200)
        self.send_header("Content-Type", "application/x-ndjson")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()

        lock = threading.Lock()
        alive = [True]

        def send(line):
            if not alive[0]:
                return
            with lock:
                try:
                    self.wfile.write((json.dumps(line) + "\n").encode())
                    self.wfile.flush()
                except (BrokenPipeError, ConnectionResetError, ValueError):
                    # They closed the tab. Let the work finish and be recorded;
                    # it was already paid for.
                    alive[0] = False

        try:
            payload = ask(text, bool(body.get("approved")), body.get("tier"),
                          watch=lambda event: send({"step": event}),
                          case_id=body.get("case_id"))
        except provider.BackendUnavailable as exc:
            payload = {"error": str(exc)}
        except Exception as exc:
            payload = {"error": f"{type(exc).__name__}: {exc}"}
        send({"done": payload})

    def _send(self, code, body, ctype="application/json"):
        payload = body if isinstance(body, bytes) else json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(payload)))
        # Nothing here is worth caching, and a stale index.html looks exactly
        # like a change that did not work.
        self.send_header("Cache-Control", "no-store, must-revalidate")
        self.end_headers()
        self.wfile.write(payload)

    def do_GET(self):
        path = self.path.split("?")[0]
        if path == "/api/state":
            return self._send(200, state())
        if path == "/api/usage":
            flagged = [{"user": who, "latest": latest, "median": median}
                       for who, latest, median in memory.anomalies()]
            return self._send(200, {
                **memory.usage(USER),
                "quality": memory.quality(USER),
                "measured": memory.measured(USER),
                "anomalies": flagged,
                "habit_model": config.PRICED[config.HABIT_TIER].id,
                "models": {tier: model.id for tier, model in config.MODELS.items()},
            })
        if path == "/api/case":
            wanted = self.path.split("id=")[-1] if "id=" in self.path else ""
            return self._send(200, {"case_id": wanted,
                                    "turns": transcript().get(wanted, [])})
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
            return self._send(200, {**saved,
                                    "backend_status": credentials(fresh=True)})

        if self.path == "/api/rate":
            memory.rate(body["id"], USER, body["tier"], body["rating"],
                        body.get("comment", ""))
            return self._send(200, {"ok": True})

        if self.path != "/api/ask":
            return self._send(404, {"error": "not found"})

        text = (body.get("text") or "").strip()
        if not text:
            return self._send(400, {"error": "empty request"})

        if body.get("stream"):
            return self._stream(body, text)

        try:
            payload = ask(text, bool(body.get("approved")), body.get("tier"),
                          case_id=body.get("case_id"))
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
    if ready and not config.USE_AWS:
        for tier, name in config.MODELS.items():
            pinned = " (pinned)" if config.PINNED.get(tier) else ""
            print(f"    {tier:<7} {name.id}{pinned}")
    print(f"  ceiling  {config.CEILING}   habit {config.HABIT_TIER}   "
          f"case budget ${bureau.CASE_BUDGET:.2f}")
    ThreadingHTTPServer(("127.0.0.1", PORT), Handler).serve_forever()
