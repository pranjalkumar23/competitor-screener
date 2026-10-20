#!/usr/bin/env python3
"""Yahoo Finance (unofficial, no API key) data layer + shared HTTP handler for the /api/* routes."""
import http.cookiejar, json, threading, time, urllib.error, urllib.parse, urllib.request
from datetime import datetime, timezone

Q = "https://query1.finance.yahoo.com"
_lock = threading.Lock()
_cache = {}
_opener = None
_crumb = None


def _session():
    global _opener, _crumb
    cj = http.cookiejar.CookieJar()
    _opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))
    _opener.addheaders = [("User-Agent", "Mozilla/5.0")]
    try:
        _opener.open("https://fc.yahoo.com", timeout=10)  # sets cookie; 404 is expected
    except Exception:
        pass
    _crumb = _opener.open(f"{Q}/v1/test/getcrumb", timeout=10).read().decode()


def get(path, retry=True):
    global _opener
    with _lock:
        if _opener is None:
            _session()
        op, crumb = _opener, _crumb
    sep = "&" if "?" in path else "?"
    try:
        return json.load(op.open(f"{Q}{path}{sep}crumb={urllib.parse.quote(crumb)}", timeout=15))
    except urllib.error.HTTPError as e:
        if e.code in (401, 403) and retry:
            with _lock:
                if _opener is op:
                    _opener = None
            return get(path, False)
        raise


def cached(key, fn, ttl=300):
    hit = _cache.get(key)
    if hit and time.time() - hit[0] < ttl:
        return hit[1]
    val = fn()
    _cache[key] = (time.time(), val)
    return val


def raw(d, *keys):
    for k in keys:
        d = (d or {}).get(k)
    return d.get("raw") if isinstance(d, dict) else d


RATING = {"strong_buy": "Strong Buy", "buy": "Buy", "hold": "Hold", "underperform": "Sell", "sell": "Strong Sell"}


def company(sym):
    sym = sym.upper()
    qs = get(f"/v10/finance/quoteSummary/{sym}?modules=price,summaryDetail,financialData,calendarEvents,earningsHistory,assetProfile")
    r = (qs.get("quoteSummary", {}).get("result") or [None])[0]
    if not r:
        raise ValueError(f"No data for {sym}")
    ch = get(f"/v8/finance/chart/{sym}?range=2y&interval=1d&events=div")["chart"]["result"][0]
    ts, closes = ch.get("timestamp") or [], ch["indicators"]["quote"][0].get("close") or []
    year = datetime.now(timezone.utc).year
    ytd = None
    series = [(t, c) for t, c in zip(ts, closes) if c]
    jan = [c for t, c in series if datetime.fromtimestamp(t, timezone.utc).year == year]
    prev = [c for t, c in series if datetime.fromtimestamp(t, timezone.utc).year < year]
    if jan and prev:
        ytd = (series[-1][1] / prev[-1] - 1) * 100
    divs = sorted((ch.get("events") or {}).get("dividends", {}).values(), key=lambda d: d["date"])
    total = sum(d["amount"] for d in divs)

    price, fd, sd = r.get("price", {}), r.get("financialData", {}), r.get("summaryDetail", {})
    cur, tgt = raw(fd, "currentPrice"), raw(fd, "targetMeanPrice")
    hist = (r.get("earningsHistory", {}).get("history") or [])
    last = hist[-1] if hist else {}
    ed = (r.get("calendarEvents", {}).get("earnings", {}).get("earningsDate") or [])
    nxt = datetime.fromtimestamp(ed[0]["raw"], timezone.utc).strftime("%Y-%m-%d") if ed else None
    stale = bool(nxt and nxt < datetime.now(timezone.utc).strftime("%Y-%m-%d"))
    if stale:
        nxt = None
    rate, yld = raw(sd, "dividendRate"), raw(sd, "dividendYield")
    return {
        "sym": sym, "name": price.get("shortName") or sym,
        "role": r.get("assetProfile", {}).get("industry", ""),
        "ytd": ytd, "upside": (tgt / cur - 1) * 100 if tgt and cur else None,
        "fpe": raw(sd, "forwardPE"), "rating": RATING.get(fd.get("recommendationKey")), "conf": None,
        "why": f"Live (Yahoo Finance). Price ${cur:.2f}." if cur else "Live (Yahoo Finance).",
        "earn": {
            "last": datetime.fromtimestamp(raw(last, "quarter"), timezone.utc).strftime("%b %Y quarter") if raw(last, "quarter") else None,
            "revYoy": (raw(fd, "revenueGrowth") or 0) * 100 if raw(fd, "revenueGrowth") is not None else None,
            "rev": None, "eps": raw(last, "epsActual"), "est": raw(last, "epsEstimate"),
            "guide": "Revenue growth is latest quarter YoY. Guidance not available from this source.",
            "next": nxt, "nextNote": "per Yahoo; may be an estimate" if nxt else ("Yahoo date has passed; next not announced" if stale else "no date listed"),
        },
        "div": {
            "now": f"${rate:.2f}/yr" if rate else "None",
            "yld": f"{yld*100:.2f}%" if yld else "0%",
            "total": f"${total:.2f}" if divs else "$0",
            "hist": f"{len(divs)} payments: " + ", ".join(f"{datetime.fromtimestamp(d['date'], timezone.utc):%Y-%m-%d} ${d['amount']:.4g}" for d in divs[-8:]) if divs else "No dividends in the last 2 years",
        },
    }


def similar(sym):
    d = get(f"/v6/finance/recommendationsbysymbol/{sym.upper()}")
    res = (d.get("finance", {}).get("result") or [{}])[0].get("recommendedSymbols") or []
    return [x["symbol"] for x in res]


def analysts(sym):
    sym = sym.upper()
    r = (get(f"/v10/finance/quoteSummary/{sym}?modules=recommendationTrend,upgradeDowngradeHistory,financialData")["quoteSummary"]["result"] or [None])[0]
    if not r:
        raise ValueError(f"No analyst data for {sym}")
    tr = (r.get("recommendationTrend", {}).get("trend") or [{}])[0]
    fd = r.get("financialData", {})
    recent = []
    for h in (r.get("upgradeDowngradeHistory", {}).get("history") or [])[:6]:
        recent.append({"firm": h.get("firm"), "to": h.get("toGrade"), "from": h.get("fromGrade"), "action": h.get("action"),
                       "date": datetime.fromtimestamp(h["epochGradeDate"], timezone.utc).strftime("%Y-%m-%d") if h.get("epochGradeDate") else None})
    cur, tgt = raw(fd, "currentPrice"), raw(fd, "targetMeanPrice")
    return {"counts": {k: tr.get(k, 0) for k in ("strongBuy", "buy", "hold", "sell", "strongSell")},
            "n": raw(fd, "numberOfAnalystOpinions"), "label": RATING.get(fd.get("recommendationKey")), "mean": raw(fd, "recommendationMean"),
            "price": cur, "target": tgt, "targetHigh": raw(fd, "targetHighPrice"), "targetLow": raw(fd, "targetLowPrice"),
            "upside": (tgt / cur - 1) * 100 if tgt and cur else None,
            "revGrowth": (raw(fd, "revenueGrowth") * 100) if raw(fd, "revenueGrowth") is not None else None,
            "earnGrowth": (raw(fd, "earningsGrowth") * 100) if raw(fd, "earningsGrowth") is not None else None,
            "recent": recent}


# ---- Discover: sector strength + screening universe (my curated large-cap lists; not the whole market) ----
SECTORS = [
    ("semis", "Semiconductors", "SMH", ["NVDA","TSM","AVGO","AMD","MU","AMAT","LRCX","KLAC","MRVL","ASML"]),
    ("software", "Software", "IGV", ["MSFT","ORCL","CRM","ADBE","NOW","INTU","PLTR","SNOW"]),
    ("cyber", "Cybersecurity", "CIBR", ["CRWD","PANW","ZS","FTNT","S","CYBR","RBRK","NET"]),
    ("comm", "Communication", "XLC", ["GOOGL","META","NFLX","DIS","T","VZ","TMUS"]),
    ("discretionary", "Consumer Discretionary", "XLY", ["AMZN","TSLA","HD","MCD","NKE","BKNG","LOW","SBUX"]),
    ("staples", "Consumer Staples", "XLP", ["WMT","COST","PG","KO","PEP","PM","MDLZ"]),
    ("energy", "Energy", "XLE", ["XOM","CVX","COP","EOG","SLB","OXY","MPC"]),
    ("health", "Healthcare", "XLV", ["LLY","JNJ","UNH","ABBV","MRK","TMO","ISRG","ABT"]),
    ("financials", "Financials", "XLF", ["JPM","BAC","V","MA","GS","MS","BRK-B","WFC"]),
    ("industrials", "Industrials", "XLI", ["GE","CAT","RTX","HON","UNP","DE","BA","ETN"]),
    ("utilities", "Utilities", "XLU", ["NEE","SO","DUK","CEG","AEP","D"]),
    ("realestate", "Real Estate", "XLRE", ["PLD","AMT","EQIX","WELL","SPG","O"]),
    ("materials", "Materials", "XLB", ["LIN","SHW","FCX","NEM","APD","ECL"]),
    ("ai_dc", "AI data-center build-out (basket)", None, ["VRT","CLS","CRDO","COHR","LITE","GLW","ANET","DELL","APH","FN"]),
]


def sectors():
    def perf(sym):
        ch = get(f"/v8/finance/chart/{sym}?range=1y&interval=1d")["chart"]["result"][0]
        ts = ch.get("timestamp") or []
        px = [(t, c) for t, c in zip(ts, ch["indicators"]["quote"][0].get("close") or []) if c]
        last = px[-1][1]
        back = lambda n: (last / px[-1 - n][1] - 1) * 100 if len(px) > n else None
        year = datetime.now(timezone.utc).year
        prev = [c for t, c in px if datetime.fromtimestamp(t, timezone.utc).year < year]
        return {"r1m": back(21), "r3m": back(63), "ytd": (last / prev[-1] - 1) * 100 if prev else None}
    etfs = sorted({s[2] for s in SECTORS if s[2]} | {"SPY"})
    perfs = {}
    for e in etfs:
        try:
            perfs[e] = perf(e)
        except Exception:
            perfs[e] = None
    spy = perfs.get("SPY") or {}
    out = []
    for sid, name, etf, syms in SECTORS:
        if etf is None:   # theme without an ETF: equal-weight average of its stocks
            ps = []
            for x in syms:
                try:
                    ps.append(perf(x))
                except Exception:
                    pass
            avg = lambda k: (sum(p[k] for p in ps if p[k] is not None) / len([p for p in ps if p[k] is not None])) if any(p[k] is not None for p in ps) else None
            p = {k: avg(k) for k in ("r1m", "r3m", "ytd")} if ps else None
            etf = "basket"
        else:
            p = perfs.get(etf)
        if not p:
            continue
        rel = p["r3m"] - spy["r3m"] if p["r3m"] is not None and spy.get("r3m") is not None else None
        out.append({"id": sid, "name": name, "etf": etf, **p, "rel3m": rel, "symbols": syms})
    return {"spy": spy, "sectors": out}


def universe(symbols):
    out = {}
    for i in range(0, len(symbols), 40):
        chunk = symbols[i:i + 40]
        d = cached(("quote", ",".join(chunk)), lambda c=chunk: get("/v7/finance/quote?symbols=" + urllib.parse.quote(",".join(c))), 600)
        for q in d["quoteResponse"]["result"]:
            et = q.get("earningsTimestamp")
            nxt = datetime.fromtimestamp(et, timezone.utc).strftime("%Y-%m-%d") if et else None
            if nxt and nxt < datetime.now(timezone.utc).strftime("%Y-%m-%d"):
                nxt = None
            ar = q.get("averageAnalystRating") or ""
            try:
                rating = float(ar.split(" - ")[0])
            except ValueError:
                rating = None
            eps_f, eps_t = q.get("epsForward"), q.get("epsTrailingTwelveMonths")
            hi, px = q.get("fiftyTwoWeekHigh"), q.get("regularMarketPrice")
            out[q["symbol"]] = {
                "sym": q["symbol"], "name": q.get("shortName") or q["symbol"], "price": px,
                "fpe": q.get("forwardPE"), "epsGrowth": ((eps_f / eps_t - 1) * 100 if eps_f and eps_t and eps_t > 0 and eps_f / eps_t - 1 <= 2 else None),  # >200% is usually a one-off charge in trailing EPS
                "chg52": q.get("fiftyTwoWeekChangePercent"), "yld": q.get("dividendYield"),
                "next": nxt, "rating": rating, "ratingLabel": ar.split(" - ")[-1] if ar else None,
                "mcap": q.get("marketCap"), "fromHigh": (px / hi - 1) * 100 if px and hi else None,
            }
    return out



def _valid(sym):
    return bool(sym) and sym.replace(".", "").replace("-", "").isalnum()


def route(path, query):
    q = urllib.parse.parse_qs(query)
    sym = (q.get("symbol") or [""])[0].strip()
    if path == "/api/sectors":
        return cached(("sectors",), sectors, 1800)
    if path == "/api/universe":
        syms = [x.strip().upper() for x in (q.get("symbols") or [""])[0].split(",") if x.strip()][:200]
        if not syms or not all(_valid(x) for x in syms):
            raise ValueError("Bad symbols")
        return universe(syms)
    if not _valid(sym):
        raise ValueError("Bad symbol")
    if path == "/api/analysts":
        return cached(("an", sym), lambda: analysts(sym), 1800)
    if path == "/api/company":
        return cached((path, sym), lambda: company(sym))
    if path == "/api/similar":
        return cached((path, sym), lambda: similar(sym))
    raise ValueError("Unknown endpoint")


def respond(h):
    """Answer one GET on a BaseHTTPRequestHandler `h` (shared by Vercel functions and server.py)."""
    u = urllib.parse.urlparse(h.path)
    try:
        code, body = 200, json.dumps(route(u.path, u.query))
    except Exception as e:
        code, body = 502, json.dumps({"error": str(e)})
    h.send_response(code)
    h.send_header("Content-Type", "application/json")
    if code == 200:  # let Vercel's CDN absorb repeat requests so Yahoo sees fewer hits
        h.send_header("Cache-Control", "public, s-maxage=300, stale-while-revalidate=600")
    h.end_headers()
    h.wfile.write(body.encode())
