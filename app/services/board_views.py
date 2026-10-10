"""Read-only Azure Boards data, preserving configured team scope and native backlog order."""
from datetime import datetime, timezone, timedelta
from urllib.parse import quote
from app.services.deliverables import available_hours, identity, number
from app.services.work_item_scope import parse_when, team_area_paths


def team_get(ado, project, team, path):
    url = f'https://dev.azure.com/{quote(ado.organization,safe="")}/{quote(project,safe="")}/{quote(team,safe="")}/_apis/work/{path}'
    response = ado.session.get(url, params={'api-version': '7.1'}, timeout=30)
    response.raise_for_status()
    return ado._json_response(response)


def iteration_dates(iteration):
    attrs = iteration.get('attributes', {})
    first, last = parse_when(attrs.get('startDate')), parse_when(attrs.get('finishDate'))
    if not first or not last or last.date() < first.date():
        raise ValueError('Configure valid sprint start and finish dates in Azure DevOps.')
    return (datetime.combine(first.date(), datetime.min.time(), timezone.utc),
            datetime.combine(last.date() + timedelta(days=1), datetime.min.time(), timezone.utc))


def capacity_view(ado, project, team, iteration_id):
    iteration = ado.get_team_iteration(project, team, iteration_id)
    start, end = iteration_dates(iteration)
    settings = ado.get_team_settings(project, team)
    names = ['monday','tuesday','wednesday','thursday','friday','saturday','sunday']
    days = settings.get('workingDays')
    if not isinstance(days, list) or any(str(d).lower() not in names for d in days):
        raise ValueError('Team working days are unavailable.')
    working = {names.index(d.lower()) for d in days}
    team_off = ado.get_team_days_off(project, team, iteration_id).get('daysOff', [])
    raw = ado.get_iteration_capacity(project, team, iteration_id)
    people = []
    for cap in raw.get('teamMembers', raw.get('value', [])):
        hours = available_hours(cap, start, end, team_off, working)
        daily_values = [number(a.get('capacityPerDay')) for a in cap.get('activities', [])]
        daily = sum(daily_values) if daily_values and all(v is not None for v in daily_values) else None
        people.append({'person': identity(cap.get('teamMember', {})), 'activities': cap.get('activities', []),
                       'days_off': cap.get('daysOff', []), 'available_hours': hours, 'daily_hours': daily,
                       'available_days': hours / daily if hours is not None and daily else None})
    return {'iteration': iteration, 'working_days': days, 'team_days_off': team_off, 'people': people,
            'source': 'Azure DevOps current iteration capacity configuration'}


def backlog_view(ado, project, team, level=None):
    levels = team_get(ado, project, team, 'backlogs').get('value', [])
    selected = (next((l for l in levels if l['id'] == level), None) if level else
                next((l for l in levels if l.get('type') == 'requirement'), levels[-1] if levels else None))
    if not selected:
        raise ValueError('No matching team backlog level is configured.')
    raw = team_get(ado, project, team, f'backlogs/{quote(selected["id"],safe="")}/workItems')
    ids = list(dict.fromkeys(r['target']['id'] for r in raw.get('workItems', []) if r.get('target')))
    items = ado.get_work_items_batch(project, ids)
    if {item['id'] for item in items} != set(ids):
        raise ValueError('Some backlog items could not be read. No partial backlog is shown.')
    order = {item_id: i for i, item_id in enumerate(ids)}
    items.sort(key=lambda x: order[x['id']])
    for item in items:
        item['web_url'] = f'https://dev.azure.com/{quote(ado.organization,safe="")}/{quote(project,safe="")}/_workitems/edit/{item["id"]}'
    return {'levels': levels, 'selected_level': selected['id'], 'items': items,
            'source': 'Azure DevOps team backlog API, in configured backlog order'}


def analytics_view(ado, project, team, iteration_id):
    iteration = ado.get_team_iteration(project, team, iteration_id)
    start, end = iteration_dates(iteration)
    if (end - start).days > 93:
        raise ValueError('Analytics supports sprint periods up to 93 days.')
    areas = team_area_paths(ado.get_team_field_values(project, team))
    if not areas:
        raise ValueError('Team area scope unavailable.')
    q = lambda text: str(text).replace("'", "''")
    area_query = ' OR '.join(f"[System.AreaPath] {'UNDER' if children else '='} '{q(path)}'" for path, children in areas)
    now = datetime.now(timezone.utc)
    points = []
    day = start
    while day < min(end, now):
        cutoff = min(day + timedelta(days=1) - timedelta(milliseconds=1), now)
        as_of = cutoff.isoformat()
        ids = []
        cursor = 0
        while True:
            wiql = (f"SELECT [System.Id] FROM WorkItems WHERE [System.TeamProject] = '{q(project)}' "
                    f"AND [System.IterationPath] = '{q(iteration['path'])}' AND [System.WorkItemType] = 'Task' "
                    f"AND ({area_query}) AND [System.Id] > {cursor} ORDER BY [System.Id] ASOF '{as_of}'")
            page = ado.query_wiql(project, wiql, top=5000)
            if not page:
                break
            if min(page) <= cursor:
                raise ValueError('Historical task pagination did not advance.')
            ids.extend(page)
            cursor = max(page)
            if len(ids) > 20000:
                raise ValueError('Sprint task scope exceeds 20,000 items.')
            if len(page) < 5000:
                break
        items = ado.get_work_items_batch(project, ids, as_of=as_of)
        if {i['id'] for i in items} != set(ids):
            raise ValueError('Historical task values could not be fully verified.')
        values = [number(i.get('fields', {}).get('Microsoft.VSTS.Scheduling.RemainingWork')) for i in items]
        points.append({'date': day.date().isoformat(), 'remaining_hours': round(sum(v for v in values if v is not None), 2),
                       'tasks': len(items), 'missing_remaining_work': sum(v is None for v in values),
                       'provisional': cutoff == now})
        day += timedelta(days=1)
    return {'iteration': iteration, 'points': points,
            'source': 'Azure DevOps ASOF task snapshots; remaining task hours at each UTC day end',
            'warning': 'This chart shows remaining task hours. Missing values are flagged. Azure DevOps Analytics widgets may use other metrics, filters or time zones.'}
