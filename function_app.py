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
  <style>
    body {{
      background: #121212;
      color: #e0e0e0;
      font-family: 'Segoe UI', sans-serif;
      padding: 40px;
    }}
    .container {{
      max-width: 1000px;
      margin: auto;
    }}
    .card {{
      background: #1e1e1e;
      padding: 20px;
      border-radius: 10px;
      margin-top: 20px;
      border: 1px solid #333;
    }}
    pre {{
      white-space: pre-wrap;
    }}
  </style>
</head>
<body>
  <div class="container">
    <h1>StatsGoBoom</h1>
    <h3>10‑Day Activity Audit</h3>
    <div class="card">
      <pre id="content"></pre>
    </div>
  </div>

  <script>
    const data = {history_json};
    const el = document.getElementById("content");

    if (Object.keys(data).length === 0) {{
      el.textContent = "No activity recorded yet.";
    }} else {{
      el.textContent = JSON.stringify(data, null, 2);
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
