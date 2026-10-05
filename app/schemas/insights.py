from pydantic import Field, field_validator

from app.schemas.connection import _Validated


class InsightsScope(_Validated):
    """Which work items: a project, optionally narrowed to one team and/or one tag."""

    organization: str = Field(min_length=1, max_length=256)
    project: str = Field(min_length=1, max_length=256)
    team: str = Field(default="", max_length=256)
    tag: str = Field(default="", max_length=256)

    @field_validator("team", "tag")
    @classmethod
    def _stripped(cls, value: str) -> str:
        return (value or "").strip()


class InsightsRefreshRequest(InsightsScope):
    pat: str | None = Field(default=None, min_length=1, max_length=512)
    months: int = Field(default=6, ge=1, le=24)
    regroup: bool = False


class AlertInventoryUpload(InsightsScope):
    """The file is sent as base64 text, so the endpoint needs no multipart support."""

    filename: str = Field(min_length=1, max_length=256)
    content_base64: str = Field(min_length=1, max_length=7_000_000)  # a 5 MB file is about 6.7 million characters
    name_column: str | None = Field(default=None, max_length=200)
    category_column: str | None = Field(default=None, max_length=200)  # "" means: no grouping column
