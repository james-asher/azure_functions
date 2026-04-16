import os
import json
import uuid
from datetime import datetime, timedelta

import azure.functions as func
from azure.data.tables import TableServiceClient
import logging

# ==============================
# App setup (Python v2 model)
# ==============================
app = func.FunctionApp(http_auth_level=func.AuthLevel.FUNCTION)

# ==============================
# Configuration
# ==============================
TABLE_NAME = os.getenv("LOG_TABLE_NAME", "activitylog")
RETENTION_DAYS = int(os.getenv("RETENTION_DAYS", "10"))


# ==============================
# Storage helpers
# ==============================
def _get_table():
    service = TableServiceClient.from_connection_string(
        os.environ["AzureWebJobsStorage"]
    )
    service.create_table_if_not_exists(TABLE_NAME)
    return service.get_table_client(TABLE_NAME)


def _log_event(counter: str, user: str):
    logging.info("StatsGoBoom: entering _log_event")

    table = _get_table()
    logging.info("StatsGoBoom: table client acquired")

    now = datetime.utcnow()

    entity = {
        "PartitionKey": now.strftime("%Y-%m-%d"),
        "RowKey": str(uuid.uuid4()),
        "ts": now.isoformat(),
        "cnt": counter,
        "usr": user,
    }

    logging.info("StatsGoBoom: inserting entity %s", entity)
    table.create_entity(entity)
    logging.info("StatsGoBoom: entity inserted successfully")


def _get_history(days: int = RETENTION_DAYS):
    table = _get_table()
    cutoff = (datetime.utcnow() - timedelta(days=days)).strftime("%Y-%m-%d")

    entities = table.query_entities(
        query_filter=f"PartitionKey ge '{cutoff}'"
    )

    history = {}
    for e in entities:
        history.setdefault(e["PartitionKey"], []).append({
            "ts": e.get("ts"),
            "cnt": e.get("cnt"),
            "usr": e.get("usr"),
        })

    return history


def _cleanup_old(days: int = RETENTION_DAYS):
    table = _get_table()
    cutoff = (datetime.utcnow() - timedelta(days=days)).strftime("%Y-%m-%d")

    old_entities = table.query_entities(
        query_filter=f"PartitionKey lt '{cutoff}'"
    )

    for e in old_entities:
        table.delete_entity(e["PartitionKey"], e["RowKey"])


# ==============================
# /track.js  (telemetry endpoint)
# ==============================
@app.function_name(name="track")
@app.route(route="track.js", methods=["GET"])
def track(req: func.HttpRequest) -> func.HttpResponse:
    counter = (
        req.params.get("counter")
        or req.headers.get("Referer")
        or "unknown"
    )
    user = req.params.get("usr") or "anonymous"

    log_error = "none"
    try:
        _log_event(counter, user)
    except Exception as ex:
        
        logging.exception(
            "StatsGoBoom: _log_event failed",
            extra={
                "counter": counter,
                "user": user
            }
        )
        log_error = str(ex)

        # Never break callers (telemetry must be non-blocking)
        pass
    js = "var user = " + json.dumps(user) + "; var counter = " + json.dumps(counter) + "; var logError = " + json.dumps(log_error) + ";"
    # js = "var sitecounter = 0; var sitevisitors = 0;"
    return func.HttpResponse(js, mimetype="application/javascript")


# ==============================
# /inspect  (Formatted Plain Text History)
# ==============================
@app.function_name(name="inspect")
@app.route(route="inspect", methods=["GET"])
def inspect(req: func.HttpRequest) -> func.HttpResponse:
    search_term = req.params.get("counter")
    target_user = req.params.get("usr")
    days = int(req.params.get("days", RETENTION_DAYS))
    
    raw_history = _get_history(days=min(days, 30))
    
    is_wildcard = search_term.endswith('*') if search_term else False
    clean_search = search_term[:-1] if is_wildcard else search_term

    log_lines = []

    # Sort dates descending (newest days first)
    for date_str in sorted(raw_history.keys(), reverse=True):
        entries = raw_history[date_str]
        
        # Sort entries within the day descending by timestamp
        entries.sort(key=lambda x: x.get("ts", ""), reverse=True)

        for e in entries:
            c_name = e.get("cnt", "unknown")
            u_name = e.get("usr", "anonymous")
            ts_raw = e.get("ts", "")

            if clean_search:
                if is_wildcard:
                    if not c_name.startswith(clean_search): continue
                elif c_name != clean_search: continue
            
            if target_user and u_name != target_user:
                continue

            try:
                # Parse UTC and subtract 6 hours for CST
                dt = datetime.fromisoformat(ts_raw)
                cst_dt = dt - timedelta(hours=6) 
                ts_display = cst_dt.strftime("%Y-%m-%d %H:%M:%S")
            except:
                ts_display = ts_raw

            log_lines.append(f"[{ts_display}] {u_name} \"{c_name}\"")

    return func.HttpResponse(
        "\n".join(log_lines),
        mimetype="text/plain"
    )


# ==============================
# /dashboard  (HTML UI)
# ==============================
@app.function_name(name="dashboard")
@app.route(route="dashboard", methods=["GET"])
def dashboard(req: func.HttpRequest) -> func.HttpResponse:
    history = _get_history()
    history_json = json.dumps(history)
    FUNC_KEY = os.getenv("INSPECT_KEY", "")

    html = f"""
<!DOCTYPE html>
<html>
<head>
    <title>StatsGoBoom Dashboard</title>
    <style>
        body {{ background: #121212; color: #e0e0e0; font-family: 'Segoe UI', sans-serif; padding: 40px; }}
        .container {{ max-width: 1000px; margin: auto; }}
        .header {{ display: flex; justify-content: space-between; align-items: center; border-bottom: 1px solid #333; padding-bottom: 20px; }}
        .card {{ background: #1e1e1e; padding: 20px; border-radius: 10px; margin-top: 20px; border: 1px solid #333; }}
        table {{ width: 100%; border-collapse: collapse; margin-top: 10px; }}
        th {{ text-align: left; color: #888; text-transform: uppercase; font-size: 11px; padding: 10px; border-bottom: 1px solid #333; }}
        td {{ padding: 12px 10px; border-bottom: 1px solid #252525; font-size: 14px; }}
        .highlight {{ color: #00ffcc; font-weight: bold; width: 80px; text-align: right; }}
        .tag {{ background: #333; padding: 4px 10px; border-radius: 4px; font-family: monospace; font-size: 13px; color: #00ffcc; text-decoration: none; border: 1px solid transparent; cursor: pointer; transition: 0.2s; }}
        .tag:hover {{ background: #444; border-color: #00ffcc; }}
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>StatsGoBoom <span style="color:#555;">| 10-Day Audit</span></h1>
            <div>
                <a href="/api/inspect?code={FUNC_KEY}" target="_blank" style="color:#888; text-decoration:none; font-size: 14px;">Full Raw Logs &raquo;</a>
            </div>
        </div>
        <div id="content"></div>
    </div>

    <script>
        const data = {history_json};
        const content = document.getElementById('content');
        const auth = "{FUNC_KEY}";

        function inspectCounter(name) {{
            const url = `/api/inspect?code=${{auth}}&counter=${{encodeURIComponent(name)}}`;
            window.open(url, '_blank');
        }}

        if (Object.keys(data).length === 0) {{
            content.innerHTML = '<div class="card">No activity recorded yet.</div>';
        }} else {{
            Object.keys(data).sort().reverse().forEach(date => {{
                let tableRows = "";
                const dayData = data[date];
                const stats = {{}};
                
                dayData.forEach(e => {{
                    stats[e.cnt] = (stats[e.cnt] || 0) + 1;
                }});

                // Alphabetical sort for counters
                Object.keys(stats).sort((a, b) => a.toLowerCase().localeCompare(b.toLowerCase())).forEach(counter => {{
                    tableRows += `<tr>
                        <td><span class="tag" onclick="inspectCounter('${{counter}}')">${{counter}}</span></td>
                        <td class="highlight">${{stats[counter]}}</td>
                    </tr>`;
                }});

                content.innerHTML += `
                    <div class="card">
                        <h3 style="margin-top:0; color:#888;">${{date}}</h3>
                        <table>
                            <thead><tr><th>Counter Name (Alphabetical)</th><th style="text-align:right;">Hits</th></tr></thead>
                            <tbody>${{tableRows}}</tbody>
                        </table>
                    </div>`;
            }});
        }}
    </script>
</body>
</html>
"""
    return func.HttpResponse(html, mimetype="text/html")


# ==============================
# Daily cleanup (timer trigger)
# ==============================
@app.function_name(name="cleanup")
@app.schedule(schedule="0 30 2 * * *", arg_name="timer")
def cleanup(timer: func.TimerRequest) -> None:
    try:
        _cleanup_old()
    except Exception:
        pass
