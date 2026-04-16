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
# /inspect  (raw JSON history)
# ==============================
@app.function_name(name="inspect")
@app.route(route="inspect", methods=["GET"])
def inspect(req: func.HttpRequest) -> func.HttpResponse:
    days = int(req.params.get("days", RETENTION_DAYS))
    history = _get_history(days=min(days, 30))

    return func.HttpResponse(
        json.dumps(history, indent=2),
        mimetype="application/json"
    )


# ==============================
# /dashboard  (HTML UI)
# ==============================
@app.function_name(name="dashboard")
@app.route(route="dashboard", methods=["GET"])
def dashboard(req: func.HttpRequest) -> func.HttpResponse:
    history = _get_history()
    history_json = json.dumps(history)

    html = f"""
<!DOCTYPE html>
<html>
<head>
  <title>StatsGoBoom Dashboard</title>
  <meta http-equiv="refresh" content="300">
  <style>
    body {{ background: #121212; color: #e0e0e0; font-family: 'Segoe UI', sans-serif; padding: 40px; }}
    .container {{ max-width: 1000px; margin: auto; }}
    .header {{ display: flex; justify-content: space-between; align-items: center; border-bottom: 1px solid #333; padding-bottom: 20px; }}
    .card {{ background: #1e1e1e; padding: 20px; border-radius: 10px; margin-top: 20px; border: 1px solid #333; }}
    table {{ width: 100%; border-collapse: collapse; margin-top: 10px; }}
    th {{ text-align: left; color: #888; text-transform: uppercase; font-size: 11px; padding: 10px; border-bottom: 1px solid #333; }}
    td {{ padding: 12px 10px; border-bottom: 1px solid #252525; font-size: 14px; }}
    .highlight {{ color: #00ffcc; font-weight: bold; width: 80px; text-align: right; }}
    .tag {{ background: #333; padding: 4px 10px; border-radius: 4px; font-family: monospace; font-size: 13px; color: #00ffcc; text-decoration: none; border: 1px solid transparent; transition: 0.2s; }}
    .tag:hover {{ background: #444; border-color: #00ffcc; cursor: pointer; }}
  </style>
</head>
<body>
  <div class="container">
    <div class="header">
        <h1>StatsGoBoom <span style="color:#555;">| 10-Day Audit</span></h1>
        <div><a href="/api/inspect" target="_blank" style="color:#888; text-decoration:none; font-size: 14px;">View Raw JSON &raquo;</a></div>
    </div>
    <div id="content"></div>
  </div>

  <script>
    const data = {history_json};
    const content = document.getElementById('content');

    if (Object.keys(data).length === 0) {{
      content.innerHTML = '<div class="card">No activity recorded yet.</div>';
    }} else {{
      // Sort dates descending (Newest date card at top)
      Object.keys(data).sort().reverse().forEach(date => {{
        let tableRows = "";

        // Sort counters alphabetically within each day
        const counters = data[date];
        
        // Note: The Azure version stores a list of events. 
        // We aggregate them here for the table view.
        const stats = {{}};
        counters.forEach(e => {{
            stats[e.cnt] = (stats[e.cnt] || 0) + 1;
        }});

        const sortedCounterNames = Object.keys(stats).sort((a, b) => 
            a.toLowerCase().localeCompare(b.toLowerCase())
        );

        sortedCounterNames.forEach(counterName => {{
          tableRows += `<tr>
            <td><span class="tag">${{counterName}}</span></td>
            <td class="highlight">${{stats[counterName]}}</td>
          </tr>`;
        }});

        content.innerHTML += `
          <div class="card">
            <h3 style="margin-top:0; color:#888;">${{date}}</h3>
            <table>
              <thead>
                <tr><th>Counter Name (Alphabetical)</th><th style="text-align:right;">Hits</th></tr>
              </thead>
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
