from pydantic import BaseModel, Field, field_validator

from core.validation import validate_organization, validate_pat, validate_project


class _Validated(BaseModel):
    @field_validator("organization", check_fields=False)
    @classmethod
    def _organization(cls, value: str) -> str:
        return validate_organization(value)

    @field_validator("project", check_fields=False)
    @classmethod
    def _project(cls, value: str) -> str:
        return validate_project(value)

    @field_validator("pat", check_fields=False)
    @classmethod
    def _pat(cls, value: str | None) -> str | None:
        return None if value is None else validate_pat(value.strip())


class AdoConnectRequest(_Validated):
    organization: str = Field(min_length=1, max_length=256)
    pat: str | None = Field(default=None, min_length=1, max_length=512)

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

class AdoIngestRequest(_Validated):
    organization: str = Field(min_length=1, max_length=256)
    pat: str | None = Field(default=None, min_length=1, max_length=512)
    project: str = Field(min_length=1, max_length=256)
    pipeline_id: int = Field(ge=1, le=2**31 - 1)
    days: int = Field(default=90, ge=1, le=730)
    max_runs: int | None = Field(default=300, ge=1, le=5000)
