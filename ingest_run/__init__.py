import azure.functions as func

from function_app import ingest_run as ingest_run_handler


def main(req: func.HttpRequest) -> func.HttpResponse:
    return ingest_run_handler(req)