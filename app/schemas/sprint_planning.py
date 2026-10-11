"""Request and response shapes of sprint planning (see app/services/sprint_planning.py)."""
from __future__ import annotations

from pydantic import BaseModel, Field


class PlanSprint(BaseModel):
    id: str
    name: str
    path: str
    start: str | None = None
    finish: str | None = None
    time_frame: str = ""  # past | current | future


class TeamMemberChoice(BaseModel):
    name: str
    unique_name: str = ""


class SprintPlanningSetup(BaseModel):
    """What the page needs to start: the sprints (and the two it proposes), the team's members and the choices for areas and story types."""
    team: str
    sprints: list[PlanSprint] = Field(default_factory=list)
    default_from_id: str | None = None
    default_to_id: str | None = None
    members: list[TeamMemberChoice] = Field(default_factory=list)
    areas: list[str] = Field(default_factory=list)
    work_item_types: list[str] = Field(default_factory=list)
    default_types: list[str] = Field(default_factory=list)
    per_person: int
    active_days: int
    notes: list[str] = Field(default_factory=list)


class PlanPerson(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    unique_name: str = Field(default="", max_length=320)
    areas: list[str] = Field(default_factory=list, max_length=60)  # area paths of choice; "*" means any area
    capacity_points: float | None = Field(default=None, ge=0, le=200)
    working_days: float | None = Field(default=10, ge=0, le=30)
    pto_days: float | None = Field(default=0, ge=0, le=30)
    focus_factor: float | None = Field(default=0.8, ge=0.1, le=1.0)


class SprintPlanRequest(BaseModel):
    organization: str = Field(min_length=1, max_length=256)
    project: str = Field(min_length=1, max_length=256)
    team: str = Field(min_length=1, max_length=256)
    pat: str | None = Field(default=None, max_length=512)
    from_iteration_id: str | None = Field(default=None, min_length=1, max_length=64)  # the sprint stories are carried from (optional: auto-derived from to_iteration_id if omitted)
    to_iteration_id: str = Field(min_length=1, max_length=64)  # the sprint being planned
    people: list[PlanPerson] = Field(min_length=1, max_length=40)
    per_person: int = Field(default=6, ge=1, le=30)
    active_days: int = Field(default=10, ge=1, le=90)
    work_item_types: list[str] | None = Field(default=None, max_length=8)
    sprint_goal: str | None = Field(default=None, max_length=500)
    capacity_mode: str = Field(default="stories", max_length=20)  # "stories" | "points"
    focus_factor: float = Field(default=0.8, ge=0.1, le=1.0)
    tags: list[str] | None = Field(default=None, max_length=20)
    area_filter: str | None = Field(default=None, max_length=256)


class StoryFlag(BaseModel):
    code: str  # blocked | active_too_long
    reason: str


class StoryComment(BaseModel):
    author: str
    date: str = ""
    text: str


class PlanStory(BaseModel):
    id: int
    title: str
    type: str = ""
    state: str = ""
    state_category: str = ""
    area_path: str = ""
    iteration_path: str = ""
    assigned_to: str = ""
    assigned_unique: str = ""
    tags: list[str] = Field(default_factory=list)
    points: float | None = None
    days_in_state: int | None = None
    state_since: str | None = None
    state_since_exact: bool = True
    flags: list[StoryFlag] = Field(default_factory=list)
    url: str = ""
    comments: list[StoryComment] | None = None  # only for a flagged story; None when they could not be read
    matched_area: str | None = None  # for a story newly given to a person: the area of choice that matched


class PlannedPerson(BaseModel):
    name: str
    unique_name: str = ""
    areas: list[str] = Field(default_factory=list)
    capacity: int
    capacity_points: float | None = None
    working_days: float = 10
    pto_days: float = 0
    focus_factor: float = 0.8
    points_planned: float = 0.0
    points_carried: float = 0.0
    points_already_planned: float = 0.0
    points_new: float = 0.0
    points_capacity: float | None = None
    points_over_by: float = 0.0
    points_open: float = 0.0
    carried: list[PlanStory] = Field(default_factory=list)
    already_planned: list[PlanStory] = Field(default_factory=list)
    new: list[PlanStory] = Field(default_factory=list)
    total: int = 0
    open_places: int = 0
    over_by: int = 0
    warnings: list[str] = Field(default_factory=list)


class UnplacedStory(BaseModel):
    story: PlanStory
    reason: str


class PlanSummary(BaseModel):
    people: int = 0
    stories_planned: int = 0
    carried: int = 0
    new: int = 0
    already_planned: int = 0
    flagged: int = 0
    blocked: int = 0
    long_active: int = 0
    unplaced: int = 0
    open_places: int = 0
    total_points_planned: float = 0.0
    total_points_capacity: float = 0.0
    points_carried: float = 0.0
    points_new: float = 0.0
    unpointed_stories: int = 0
    risk_score: str = "Low"  # Low | Medium | High
    risk_reasons: list[str] = Field(default_factory=list)
    sprint_confidence_pct: int = 85


class SprintPlan(BaseModel):
    team: str
    project: str
    from_sprint: PlanSprint
    to_sprint: PlanSprint
    per_person: int
    active_days: int
    work_item_types: list[str] = Field(default_factory=list)
    sprint_goal: str = ""
    capacity_mode: str = "stories"
    people: list[PlannedPerson] = Field(default_factory=list)
    flagged: list[PlanStory] = Field(default_factory=list)
    unplaced: list[UnplacedStory] = Field(default_factory=list)
    unplaced_total: int = 0
    outside_plan: list[PlanStory] = Field(default_factory=list)  # open stories of people who are not in this plan
    backlog_left: int = 0
    summary: PlanSummary
    notes: list[str] = Field(default_factory=list)
    ai_recommendations: list[str] = Field(default_factory=list)
    generated_at: str
    posted_to_ado: bool = False  # the plan is shown only: nothing is written to Azure DevOps


class StoryAssignment(BaseModel):
    story_id: int
    assigned_to: str | None = None  # display name or unique email


class SprintCommitRequest(BaseModel):
    organization: str = Field(min_length=1, max_length=256)
    project: str = Field(min_length=1, max_length=256)
    team: str = Field(min_length=1, max_length=256)
    pat: str | None = Field(default=None, max_length=512)
    to_iteration_id: str = Field(min_length=1, max_length=64)
    to_iteration_path: str = Field(min_length=1, max_length=256)
    assignments: list[StoryAssignment] = Field(default_factory=list)
    sprint_goal: str | None = Field(default=None, max_length=500)


class SprintCommitResponse(BaseModel):
    success: bool = True
    updated_count: int = 0
    message: str = ""
    errors: list[str] = Field(default_factory=list)

