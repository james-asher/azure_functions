import azure.functions as func
from shared.storage import log_event

def main(req: func.HttpRequest) -> func.HttpResponse:
    counter = req.params.get("counter") or req.headers.get("Referer") or "unknown"
    user = req.params.get("usr") or "anonymous"

    try:
        log_event(counter, user)
    except Exception:
        pass  # never fail caller

    js = "var sitecounter = 0; var sitevisitors = 0;"
    return func.HttpResponse(js, mimetype="application/javascript")
