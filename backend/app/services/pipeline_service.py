from backend.app.repositories.pipeline_repository import PipelineRepository

class PipelineService:
    def __init__(self, repository: PipelineRepository | None = None):
        self.repository = repository or PipelineRepository()

    def options(self):
        return self.repository.list_options()

    def summary(self, pipeline_id: int | None, days: int):
        return self.repository.summary(pipeline_id, days)

    def trends(self, pipeline_id: int | None, days: int):
        return self.repository.trends(pipeline_id, days)

    def runs(self, pipeline_id, page, page_size, status):
        return self.repository.runs(pipeline_id, page, page_size, status)
