import os
import uuid
from datetime import datetime, timedelta
from azure.data.tables import TableServiceClient

TABLE_NAME = os.getenv("LOG_TABLE_NAME", "activitylog")

def get_table():
    service = TableServiceClient.from_connection_string(
        os.environ["AzureWebJobsStorage"]
    )
    table = service.get_table_client(TABLE_NAME)
    table.create_table_if_not_exists()
    return table


def log_event(counter, user):
    table = get_table()
    now = datetime.utcnow()

    entity = {
        "PartitionKey": now.strftime("%Y-%m-%d"),
        "RowKey": str(uuid.uuid4()),
        "ts": now.isoformat(),
        "cnt": counter,
        "usr": user
    }

    table.create_entity(entity)


def get_history(days=10):
    table = get_table()
    cutoff = (datetime.utcnow() - timedelta(days=days)).strftime("%Y-%m-%d")

    entities = table.query_entities(
        query_filter=f"PartitionKey ge '{cutoff}'"
    )

    history = {}
    for e in entities:
        date = e["PartitionKey"]
        history.setdefault(date, []).append(e)

    return history


def cleanup_old(days=10):
    table = get_table()
    cutoff = (datetime.utcnow() - timedelta(days=days)).strftime("%Y-%m-%d")

    old_entities = table.query_entities(
        query_filter=f"PartitionKey lt '{cutoff}'"
    )

    for e in old_entities:
        table.delete_entity(e["PartitionKey"], e["RowKey"])
