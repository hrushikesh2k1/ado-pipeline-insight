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


