export type Pipeline={pipeline_id:number;pipeline_name:string;organization_name:string|null;project_name:string|null}
export type Options={organizations:string[];projects:string[];pipelines:Pipeline[]}
export type Summary={pipeline_id:number|null;window_days:number;total_runs:number;successful_runs:number;failed_runs:number;success_rate_pct:number;failure_rate_pct:number;degraded_runs?:number;average_duration_seconds:number|null;p90_duration_seconds:number|null;average_queue_seconds:number|null;stages:Array<{stage_name:string;avg_duration_seconds:number;samples:number;failed_count:number}>}
export type Trends={build_trend:Array<{run_id:number;build_number?:string|null;run_date:string;pipeline_id:number;pipeline_name:string;duration_seconds:number;result:string|null}>;daily_trend:Array<{run_date:string;pipeline_id:number;pipeline_name:string;avg_duration_seconds:number|null;p90_duration_seconds:number|null}>;stage_trend:Array<{run_date:string;stage_name:string;avg_duration_seconds:number}>}
export type Runs={page:number;page_size:number;total_count:number;total_pages:number;items:Array<{run_id:number;pipeline_id:number;pipeline_name:string;organization_name:string;project_name:string;source_branch:string|null;build_number:string|null;start_time:string|null;finish_time:string|null;result:string|null;duration_seconds:number|null;is_degraded:boolean;data_quality:string;stage_name?:string|null}>}
export type Recommendation={id:number|null;pipeline_id:number;category:string;severity:string;stage_name:string;task_name:string|null;recommendation:string;evidence:string;generated_at:string|null}
export type TimelineRecord={id:number;record_id:string;stage_name:string|null;job_name?:string|null;task_name?:string|null;pool_name?:string|null;agent_name:string|null;start_time:string|null;finish_time:string|null;duration_seconds:number|null;result:string|null;retry_count:number;failure_log_excerpt?:string|null}
export type RunAnalysis={run:{run_id:number;pipeline_id:number;pipeline_name:string;organization_name:string;project_name:string;source_branch:string|null;source_version:string|null;requested_by:string|null;queue_time:string|null;start_time:string|null;finish_time:string|null;result:string|null;data_quality:string;duration_seconds:number|null};stages:TimelineRecord[];jobs:TimelineRecord[];tasks:TimelineRecord[];metrics:{run_duration_seconds:number;stage_count:number;job_count:number;task_count:number;failed_records:number;stage_duration_total_seconds:number;job_duration_total_seconds:number;task_duration_total_seconds:number;queue_seconds:number|null;longest_stage:TimelineRecord|null;longest_job:TimelineRecord|null;longest_task:TimelineRecord|null}}

export type AdoProject={id:string;name:string}
export type AdoPipeline={id:number;name:string;project_id:string|null;project_name:string|null}
export type AdoConnection={organization:string;projects:AdoProject[];pipelines:AdoPipeline[]}

export type UserProfile = {
  authenticated: boolean
  loginRequired?: boolean
  userId: string | null
  email: string | null
  name: string | null
  provider: string | null
}

export type AdoRepository = {
  id: string
  name: string
  default_branch: string | null
  web_url: string | null
}

export type AdoReviewer = {
  id: string | null
  display_name: string
  unique_name: string | null
  image_url: string | null
  vote: number
  is_required: boolean
}

export type AdoPullRequest = {
  id: number
  title: string
  description: string | null
  status: string
  created_by_name: string
  created_by_avatar: string | null
  creation_date: string
  source_branch: string
  target_branch: string
  repository_id: string
  repository_name: string
  project_name: string
  is_draft: boolean
  merge_status: string | null
  reviewers: AdoReviewer[]
  web_url: string | null
  comments_count: number | null
}

export type PullRequestReviewComment = {
  id: string
  category: 'correctness' | 'security' | 'performance' | 'maintainability' | 'test_coverage'
  severity: 'critical' | 'warning' | 'suggestion' | 'praise'
  title: string
  comment: string
  file_path: string | null
  line_number: number | null
  suggestion_code: string | null
}

export type PullRequestReviewResponse = {
  pull_request_id: number
  verdict: 'APPROVED' | 'APPROVED_WITH_SUGGESTIONS' | 'CHANGES_REQUESTED'
  summary: string
  scorecard: Record<string, string>
  comments: PullRequestReviewComment[]
  clarifications?: string[]
  posted_to_ado: boolean
}

export type AdoTeam = {
  id: string
  name: string
  description?: string | null
}

export type AdoIteration = {
  id: string
  name: string
  path: string
  start_date?: string | null
  finish_date?: string | null
  time_frame?: string | null
}

export type AdoWorkItem = {
  id: number
  title: string
  work_item_type: string
  state: string
  assigned_to_name?: string | null
  assigned_to_avatar?: string | null
  remaining_work?: number | null
  completed_work?: number | null
  original_estimate?: number | null
  parent_id?: number | null
  state_change_date?: string | null
  changed_date?: string | null
  web_url?: string | null
  business_days_in_review?: number | null
  is_closed_without_hours: boolean
  is_stale_in_review: boolean
  description?: string | null
  acceptance_criteria?: string | null
  area_path?: string | null
  iteration_path?: string | null
  iteration_id?: number | null
}

export type AdoSprintChecksSummary = {
  total_tasks: number
  tasks_closed_count: number
  tasks_closed_without_hours_count: number
  total_user_stories: number
  stories_in_review_count: number
  stories_in_review_stale_count: number
  flagged_item_ids: number[]
}

export type AdoMilestoneItem = {
  id: number
  title: string
  work_item_type: string
  state: string
  assigned_to_name?: string | null
  assigned_to_avatar?: string | null
  completed_date?: string | null
  web_url?: string | null
  category: string
  milestone_stream?: string
  hours_delivered: number
  child_tasks_total: number
  child_tasks_closed: number
  description?: string | null
  acceptance_criteria?: string | null
  issue_summary?: string | null
  achievement_summary?: string | null
}

export type MilestoneStreamMetric = {
  name: string
  total_count: number
  closed_count: number
  delivered_hours: number
  completion_pct: number
  issues_addressed_count: number
  next_sprint_baseline_target: number
  next_sprint_recommendation: string
}

export type MilestoneGraphData = {
  streams: MilestoneStreamMetric[]
  overall_reliability_baseline_pct: number
  bug_resolution_rate_pct: number
  next_sprint_recommended_capacity: string
  next_sprint_focus_areas: string[]
}

export type AdoSprintMilestoneSummary = {
  total_stories: number
  closed_stories_count: number
  open_stories_count: number
  completion_rate_pct: number
  total_delivered_hours: number
  features_delivered_count: number
  bugs_resolved_count: number
  achieved_items: AdoMilestoneItem[]
  key_achievements: string[]
  graph_data?: MilestoneGraphData | null
}

export type MilestoneAiSummaryResponse = {
  summary: string
  highlights: string[]
  business_impact?: string | null
  issues_summary?: Array<{ stream: string; id: string; title: string; issue: string }>
  achievements_summary?: Array<{ stream: string; id: string; title: string; achievement: string }>
  graph_data?: MilestoneGraphData | null
}

export type AdoSprintBoardResponse = {
  team: AdoTeam
  iteration?: AdoIteration | null
  work_items: AdoWorkItem[]
  checks_summary: AdoSprintChecksSummary
  working_days_remaining?: number | null
  milestone?: AdoSprintMilestoneSummary | null
}

export type ReleaseBranchCandidate = {
  branch: string
  last_built: string | null
  run_count: number
  is_default?: boolean
}

export type ReleaseDefinitionCreate = {
  name: string
  organization_name: string
  project_name: string
  repository_id?: string | null
  repository_name?: string | null
  pipeline_id?: number | null
  target_branch: string
  scope_feature_title?: string | null
  target_ship_date?: string | null
}

export type ReleaseDefinition = {
  release_id: string
  name: string
  organization_name: string
  project_name: string
  repository_id?: string | null
  repository_name?: string | null
  pipeline_id?: number | null
  target_branch: string
  scope_feature_title?: string | null
  target_ship_date?: string | null
  created_by?: string | null
  created_at: string
}

export type ReleaseDimensionEvidenceItem = {
  id: string | number
  title: string
  item_type: string
  status_or_result: string
  severity?: string | null
  web_url?: string | null
  details?: string | null
}

export type ReleaseDimension = {
  key: string
  name: string
  status: 'green' | 'yellow' | 'red'
  score_text: string
  summary: string
  evidence_items: ReleaseDimensionEvidenceItem[]
  metrics: Record<string, any>
}

export type ReleaseScorecard = {
  release: ReleaseDefinition
  overall_status: 'green' | 'yellow' | 'red'
  computed_at: string
  dimensions: Record<string, ReleaseDimension>
  ai_narrative: string
  ai_generated: boolean
  recommendations: string[]
}

export type ReleaseScorecardHistoryItem = {
  history_id?: number | null
  release_id: string
  computed_at: string
  overall_status: string
  dimension_statuses: Record<string, string>
}

export type AdoWiki = {
  id: string
  name: string
  type?: string | null
  url?: string | null
  remote_url?: string | null
}

export type AdoWikiPage = {
  id?: number | null
  path: string
  order?: number | null
  is_parent_page?: boolean | null
  git_item_path?: string | null
  sub_pages?: any[]
  content?: string
}

export type IrpCase = { name: string; signal?: string | null }

export type IrpGenerateRequest = {
  alert_name: string
  cvrd?: string | null
  alert_output_columns?: string | null
  /** The alert's ARM template (JSON): its query, threshold, severity and scope are read from it. */
  arm_template_context?: string | null
  /** The alert's KQL query. It wins over the query in the ARM template. */
  alert_kql?: string | null
  alert_details?: string | null
  target_resource?: string | null
  severity?: string
  trigger_condition?: string | null
  owning_team?: string | null
  environment?: string | null
  irp_template?: string | null
  irp_example?: string | null
  additional_notes?: string | null
  /** The root causes to write rows for (edited by the owner); proposed from the alert when absent. */
  cases?: IrpCase[] | null
}

export type IrpFacts = {
  has_definition: boolean
  arm: { given: boolean; parsed: boolean; alerts_found: string[]; unresolved: string[] }
  alert: null | {
    name: string
    type: 'log' | 'metric'
    source: string
    kind?: string | null
    api_version?: string | null
    description?: string | null
    severity: number | null
    enabled?: boolean | null
    evaluation_frequency?: string | null
    window_size?: string | null
    scopes: string[]
    target_resource_types: string[]
    product?: string | null
    condition_sentence: string
    action_groups: string[]
  }
  kql: {
    query: string
    source: 'arm' | 'input' | null
    tables: string[]
    filters: { column: string; operator: string; values: string[] }[]
    aggregations: string[]
    group_by: string[]
    output_columns: string[]
    time_windows: string[]
    warnings: string[]
  }
  severity_name: string | null
  description_sentence: string | null
  warnings: string[]
}

export type IrpScoreCheck = { id: string; title: string; status: 'pass' | 'warn' | 'fail' | 'info'; detail: string; items: string[] }
export type IrpScorecard = { status: 'pass' | 'warn' | 'fail'; passed: number; total: number; checks: IrpScoreCheck[] }
export type IrpCommand = {
  id: string
  row: string
  kind: string
  where: string
  language: 'kql' | 'cli' | 'powershell'
  text: string
  /** Only QA can make a command verified; every generated command starts as unverified. */
  status: 'unverified' | 'verified'
  /** Where the command came from: the alert's own query, that query with operators added, or written by the AI. */
  origin?: 'alert-query' | 'alert-query-plus' | 'ai-written'
  issues: { id: string; severity: 'fail' | 'warn'; message: string; doc: string }[]
}

export type IrpGenerateResponse = {
  alert_name: string
  severity: string
  target_resource: string
  markdown_content: string
  suggested_wiki_path: string
  generated_by?: 'ai' | 'built-in'
  method?: 'case-by-case' | 'single-pass' | 'built-in'
  notice?: string | null
  facts?: IrpFacts | null
  cases?: IrpCase[] | null
  scorecard?: IrpScorecard | null
  commands?: IrpCommand[] | null
}

export type IrpAnalyzeRequest = {
  alert_name: string
  alert_output_columns?: string | null
  arm_template_context?: string | null
  alert_kql?: string | null
  alert_details?: string | null
  severity?: string
  owning_team?: string | null
  environment?: string | null
  irp_template?: string | null
  additional_notes?: string | null
}

export type IrpAnalyzeResponse = { facts: IrpFacts; cases: IrpCase[]; severity?: string | null; notice?: string | null }

export type IrpPublishRequest = {
  organization: string
  project: string
  pat?: string | null
  wiki_id: string
  path: string
  content: string
  comment?: string | null
  update_inventory?: boolean
  inventory_page_path?: string | null
  alert_name?: string | null
  severity?: string | null
  owning_team?: string | null
}

export type IrpPublishResponse = {
  success: boolean
  page_path: string
  wiki_id: string
  inventory_updated: boolean
  page_details?: Record<string, any>
}




// ---- Work Item Insights ----

export type InsightItem = {
  id: number
  type: string
  title: string
  state: string
  /** Azure DevOps state category: proposed (not started), inprogress, resolved, completed (closed). */
  state_category: string
  assigned_to: string
  created: string | null
  closed: string | null
  /** Iteration path below the project root, for example "2026\Sprint 5". */
  sprint: string
  area_path: string
  /** The area the AI (or the Azure DevOps area path) put the item in. */
  area: string
  /** True when the item asks for a new alert to be built; null when not checked (no inventory or no AI). */
  alert_work: boolean | null
}

export type InsightArea = { name: string; description: string }

export type InsightInventory = {
  filename: string | null
  sheet: string | null
  uploaded_at: string | null
  count: number
  duplicates: number
  columns: string[]
  name_column: string | null
  category_column: string | null
  categories: { name: string; count: number }[]
  sample: string[]
}

export type InsightJob = {
  status: 'idle' | 'running' | 'done' | 'error'
  phase: string | null
  done: number
  total: number
  message: string
  error: string | null
  notes?: string[]
}

export type InsightScope = { organization: string; project: string; team: string; tag: string }

export type WorkItemInsights = {
  scope: InsightScope & { months: number }
  has_data: boolean
  refreshed_at: string | null
  area_source: 'ai' | 'area_path' | null
  areas: InsightArea[]
  items: InsightItem[]
  types: { name: string; count: number }[]
  bug_types: string[]
  inventory: InsightInventory | null
  notes: string[]
  ai_configured: boolean
  job: InsightJob
}

export type AlertInventoryUploadRequest = InsightScope & {
  filename: string
  content_base64: string
  name_column?: string | null
  category_column?: string | null
}
