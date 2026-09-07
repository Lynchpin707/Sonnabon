"""The demo server.

Standard library only, one file, no build step. It exists to put the agent's
work in front of a person: tonight's plan, what ran out yesterday and what that
cost, what is moving, and what the calendar is about to demand.

Two kinds of endpoint. The read ones answer straight from the tools and are
instant once the shop is cached. The agent one streams, because watching an
agent decide is most of what makes it believable, and a spinner followed by a
paragraph is not.
"""

import json
import os
import sys
import traceback
from datetime import date, datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.bakery import analytics, catalogue, runs, state, team, tickets, tools  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
PORT = int(os.getenv("PORT", "8000"))

# Loopback while developing, everything when deployed. A container that binds to
# 127.0.0.1 accepts nothing from outside itself and looks, from the load
# balancer, exactly like a crashed one.
HOST = os.getenv("HOST", "127.0.0.1")


def _json_safe(value):
    """Dates do not survive json.dumps, and a 500 here reads as a broken demo."""
    if isinstance(value, dict):
        return {key: _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    if isinstance(value, date):
        return value.isoformat()
    return value


def overview():
    """Everything the front page shows, in one call."""
    shop = state.get()
    today = state.today()
    night = runs.nightly(today)
    week = runs.weekly()
    worst = None
    for row in week["lost"]["rows"][:1]:
        worst = analytics.sellout_shape(
            shop.bills, date.fromisoformat(row["day"]), row["item"],
            index=shop.index)

    return {
        "worst": worst,
        "shop": shop.summary(),
        "today": today.isoformat(),
        "currency": catalogue.CURRENCY,
        "menu": [{"name": product.name, "price": product.price,
                  "keeps": product.margin,
                  "service": round(product.critical_ratio, 2)}
                 for product in catalogue.baked()],
        "nightly": night,
        "weekly": week,
    }


def source_status():
    """What the agent is connected to, and how fresh it is.

    The demo needs this visible: a real file, a real row count, a real
    timestamp. An agent that claims to be watching a shop should be able to say
    exactly what it is watching.
    """
    shop = state.get()
    path = shop.source
    stat = os.stat(path)
    bucket = os.getenv("BILLS_BUCKET")
    return {
        "connected": True,
        "kind": ("Till export in S3 (JSON lines)" if bucket
                 else "Till export (JSON lines)"),
        # Never the absolute path. It is somebody's home directory on somebody's
        # laptop, it means nothing to anyone else, and it goes on a screen.
        "where": (f"s3://{bucket}/{os.path.basename(path)}" if bucket
                  else os.path.relpath(path).replace(os.sep, "/")),
        "bytes": stat.st_size,
        "bills": len(shop.bills),
        "trading_days": len(shop.days),
        "first_day": shop.first_day.isoformat(),
        "last_day": shop.last_day.isoformat(),
        "updated": datetime.fromtimestamp(stat.st_mtime).isoformat(timespec="seconds"),
        "products": len(catalogue.PRODUCTS),
        "corrected_days": sum(len(v) for v in shop.corrected.values()),
        "schedule": [
            {"at": "19:00 daily", "does": "read the day's bills, spot what ran out"},
            {"at": "20:00 daily", "does": "decide tomorrow's production, send the lists"},
            {"at": "per supplier cutoff", "does": "raise the ingredient orders"},
            {"at": "Sunday 18:00", "does": "review trends, look four weeks ahead"},
        ],
    }


def weekly_report():
    """A printable week, for the folder by the till.

    Deliberately a plain page rather than a generated PDF: it prints correctly
    from any browser, it needs no dependency, and the owner can keep it or send
    it on without installing anything.
    """
    week = runs.weekly()
    shop = state.get()
    cur = catalogue.CURRENCY
    rows = "".join(
        f"<tr><td>{r['item']}</td><td class=n>{r['day']}</td>"
        f"<td class=n>{r['sold']}</td><td class=n>{r['estimate']}</td>"
        f"<td class=n>{cur}{r['lost_margin']:,.0f}</td></tr>"
        for r in week["lost"]["rows"][:10])
    moves = "".join(
        f"<tr><td>{r['item']}</td><td class=n>{r['verdict']}</td>"
        f"<td class=n>{r['change']}</td>"
        f"<td class=n>{r['start_daily']} to {r['now_daily']} a day</td></tr>"
        for r in week["trends"]["growing"] + week["trends"]["declining"])
    diary = "".join(
        f"<tr><td>{o['occasion']}</td><td class=n>{o['date']}</td>"
        f"<td class=n>{o['days_away']} days</td>"
        f"<td class=n>{o['peak_multiplier']} times on "
        f"{len(o['products'])} lines</td></tr>"
        for o in week["ahead"]["occasions"][:4])
    said = "".join(f"<p>{line}</p>" for line in week["lines"])

    return f"""<!doctype html><html lang=en><head><meta charset=utf-8>
<title>Week to {week['day']}</title>
<link rel=stylesheet href="https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;600&family=IBM+Plex+Sans:wght@400;500&family=Zilla+Slab:wght@600;700&display=swap">
<style>
body{{margin:0;background:#fff;color:#1B1613;font:15px/1.6 "IBM Plex Sans",sans-serif}}
.p{{max-width:760px;margin:0 auto;padding:36px 28px 70px}}
h1{{font-family:"Zilla Slab",serif;font-size:32px;margin:0;letter-spacing:-.02em}}
h2{{font-family:"Zilla Slab",serif;font-size:18px;margin:34px 0 10px}}
.sub{{font-family:"IBM Plex Mono",monospace;font-size:11px;letter-spacing:.14em;
  text-transform:uppercase;color:#9A8D7E;margin:6px 0 0}}
.big{{font-family:"Zilla Slab",serif;font-size:26px;color:#A83A4C;margin:2px 0 0}}
table{{width:100%;border-collapse:collapse;font-size:13.5px;margin-top:6px}}
th{{font-family:"IBM Plex Mono",monospace;font-size:10px;letter-spacing:.12em;
  text-transform:uppercase;color:#9A8D7E;text-align:left;padding-bottom:6px}}
td{{padding:6px 0;border-top:1px solid #E4DACA}}
.n{{text-align:right;font-family:"IBM Plex Mono",monospace;
  font-variant-numeric:tabular-nums}}
p{{margin:0 0 8px;max-width:62ch}}
hr{{border:0;border-top:2px solid #1B1613;margin:14px 0 0}}
@media print{{@page{{margin:16mm}} .p{{padding:0}}}}
</style></head><body><div class=p>
<h1>Week to {week['day']}</h1>
<p class=sub>{shop.summary()['bills']:,} receipts &middot; {shop.summary()['trading_days']} trading days</p>
<hr>
<h2>What I found</h2>{said}
<h2>Running out cost you</h2>
<p class=big>{cur}{week['lost']['lost_margin']:,.0f}</p>
<p class=sub>margin lost in the last four weeks</p>
<table><tr><th>Item</th><th class=n>Day</th><th class=n>Sold</th>
<th class=n>Wanted</th><th class=n>Cost</th></tr>{rows}</table>
<h2>What is moving</h2>
<table><tr><th>Item</th><th class=n>Verdict</th><th class=n>Change</th>
<th class=n>Rate</th></tr>{moves}</table>
<h2>Coming up</h2>
<table><tr><th>Occasion</th><th class=n>Date</th><th class=n>Away</th>
<th class=n>Lift</th></tr>{diary}</table>
</div></body></html>"""


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass                                    # the console is for the agent

    # ------------------------------------------------------------- plumbing

    def _send(self, code, body, ctype="application/json"):
        raw = body if isinstance(body, bytes) else body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(raw)

    def _api(self, payload):
        self._send(200, json.dumps(_json_safe(payload), ensure_ascii=False))

    def _file(self, name, ctype):
        path = os.path.join(HERE, name)
        if not os.path.exists(path):
            return self._send(404, "not found", "text/plain")
        with open(path, "rb") as handle:
            self._send(200, handle.read(), ctype)

    # ----------------------------------------------------------------- read

    def do_GET(self):
        url = urlparse(self.path)
        query = parse_qs(url.query)
        one = lambda key, default=None: (query.get(key) or [default])[0]

        try:
            if url.path in ("/", "/index.html"):
                return self._file("index.html", "text/html; charset=utf-8")
            if url.path.startswith("/assets/"):
                name = os.path.basename(url.path)
                kind = {"otf": "font/otf", "jpg": "image/jpeg",
                        "png": "image/png", "svg": "image/svg+xml"}
                return self._file(os.path.join("assets", name),
                                  kind.get(name.rsplit(".", 1)[-1].lower(),
                                           "application/octet-stream"))

            if url.path == "/api/overview":
                return self._api(overview())
            if url.path == "/api/day":
                return self._api(tools.day_report(one("on")))
            if url.path == "/api/plan":
                return self._api(tools.bake_plan(one("day")))
            if url.path == "/api/trends":
                return self._api(tools.product_trends(int(one("weeks", 40))))
            if url.path == "/api/sellers":
                return self._api(tools.best_sellers(int(one("weeks", 4))))
            if url.path == "/api/lost":
                return self._api(tools.lost_to_sellouts(int(one("weeks", 4))))
            if url.path == "/api/calendar":
                return self._api(tools.whats_coming(int(one("days", 60))))
            if url.path == "/api/occasion":
                return self._api(tools.occasion_plan(one("name", "Halloween")))
            if url.path == "/api/curve":
                shop = state.get()
                day = date.fromisoformat(one("on")) if one("on") else state.today()
                return self._api(analytics.sellout_shape(
                    shop.bills, day, one("item"), index=shop.index))
            if url.path == "/api/today":
                return self._api(tools.todays_sales(one("on")))
            if url.path == "/api/source":
                return self._api(source_status())
            if url.path == "/api/team":
                return self._api(team.today())
            if url.path == "/api/report":
                return self._send(200, weekly_report(),
                                  "text/html; charset=utf-8")
            if url.path == "/api/outbox":
                return self._api(self._outbox())

            return self._send(404, json.dumps({"error": "no such endpoint"}))
        except Exception as error:
            # Say what broke. A demo that fails silently is worse than one that
            # fails loudly, because nobody can fix it in the room.
            traceback.print_exc()
            return self._send(500, json.dumps({"error": str(error)}))

    @staticmethod
    def _outbox():
        path = "data/outbox.jsonl"
        if not os.path.exists(path):
            return {"messages": []}
        with open(path, encoding="utf-8") as handle:
            rows = [json.loads(line) for line in handle if line.strip()]
        return {"messages": rows[-20:][::-1]}

    # ---------------------------------------------------------------- agent

    def do_POST(self):
        url = urlparse(self.path)
        length = int(self.headers.get("Content-Length", 0))
        payload = json.loads(self.rfile.read(length) or b"{}")

        if url.path == "/api/tickets":
            missing = [key for key in ("id", "done") if key not in payload]
            if missing:
                return self._send(400, json.dumps(
                    {"error": "needs " + " and ".join(missing),
                     "example": {"id": "2026-09-06|Sam|Confirm what ran out",
                                 "done": True, "by": "Sam"}}))
            try:
                row = tickets.set_done(state.today(), payload["id"],
                                       bool(payload["done"]), payload.get("by"))
            except ValueError as error:
                return self._send(400, json.dumps({"error": str(error)}))
            return self._send(200, json.dumps(
                {"ok": True, "id": payload["id"], **row}))

        if url.path != "/api/agent":
            return self._send(404, json.dumps({"error": "no such endpoint"}))

        kind = payload.get("kind", "nightly")
        prompt = (payload.get("prompt") or "").strip() or None
        self.send_response(200)
        self.send_header("Content-Type", "application/x-ndjson")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()

        def emit(event):
            try:
                self.wfile.write(
                    (json.dumps(_json_safe(event), ensure_ascii=False) + "\n")
                    .encode("utf-8"))
                self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError):
                raise                            # the viewer left; stop working

        try:
            emit({"kind": "started", "run": kind})
            result = runs.with_agent(kind, watch=emit, prompt=prompt)
            emit({"kind": "done", **result})
        except Exception as error:
            # No model configured is the expected failure until Bedrock is on,
            # so say that plainly rather than dumping a stack at the viewer.
            emit({"kind": "failed", "error": str(error),
                  "hint": ("Set up a model provider. Until then the read-only "
                           "views work and show the same facts.")})


def serve(port=PORT, host=HOST):
    print("warming the shop", flush=True)
    shop = state.get()
    print(f"  {len(shop.bills):,} bills, {len(shop.days)} trading days, "
          f"{shop.first_day} to {shop.last_day}", flush=True)
    print(f"  listening on {host}:{port}", flush=True)
    if host == "127.0.0.1":
        print(f"  open http://localhost:{port}", flush=True)
    ThreadingHTTPServer((host, port), Handler).serve_forever()


if __name__ == "__main__":
    serve()
