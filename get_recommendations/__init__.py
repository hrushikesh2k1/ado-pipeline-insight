import azure.functions as func

from function_app import get_recommendations as get_recommendations_handler


def main(req: func.HttpRequest) -> func.HttpResponse:
    return get_recommendations_handler(req)