from pydantic import BaseModel, Field

class AdoConnectRequest(BaseModel):
    organization: str = Field(min_length=1, max_length=256)

class AdoProject(BaseModel):
    id: str
    name: str

class AdoPipeline(BaseModel):
    id: int
    name: str
    project_id: str | None = None
    project_name: str | None = None

class AdoConnectResponse(BaseModel):
    organization: str
    projects: list[AdoProject]
    pipelines: list[AdoPipeline]

class AdoIngestRequest(BaseModel):
    organization: str = Field(min_length=1, max_length=256)
    project: str = Field(min_length=1, max_length=256)
    pipeline_id: int
    days: int = Field(default=90, ge=1, le=730)
