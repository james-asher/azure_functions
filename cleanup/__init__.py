import azure.functions as func
from shared.storage import cleanup_old

def main(mytimer: func.TimerRequest) -> None:
    cleanup_old(days=10)
