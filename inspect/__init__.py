import azure.functions as func
import json
from shared.storage import get_history

def main(req: func.HttpRequest) -> func.HttpResponse:
    history = get_history(days=10)
    return func.HttpResponse(
        json.dumps(history, indent=2),
        mimetype="application/json"
    )
