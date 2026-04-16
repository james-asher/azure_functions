import azure.functions as func
import json
from shared.storage import get_history

def main(req: func.HttpRequest) -> func.HttpResponse:
    history = get_history(days=10)
    data_json = json.dumps(history)

    html = f"""
<!DOCTYPE html>
<html>
<head>
<title>StatsGoBoom</title>
<style>
body {{ background:#121212; color:#e0e0e0; font-family:Segoe UI; }}
.container {{ max-width:1000px; margin:auto; }}
</style>
</head>
<body>
<div class="container">
<h1>StatsGoBoom – 10 Day Audit</h1>
<pre id="content"></pre>
</div>
<script>
const data = {data_json};
document.getElementById('content').textContent =
JSON.stringify(data, null, 2);
</script>
</body>
</html>
"""
    return func.HttpResponse(html, mimetype="text/html")
