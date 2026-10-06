"""Reads an Azure Monitor alert's ARM template (JSON) and its KQL query into plain facts for the IRP writer.

Everything here is deterministic and never raises on bad input: what cannot be read is reported in `warnings`, so the page can say so
and the writer can fall back to the text as given. Supported: log alerts (Microsoft.Insights/scheduledQueryRules, kinds LogAlert,
SimpleLogAlert and LogToMetric) and metric alerts (Microsoft.Insights/metricAlerts), as Microsoft documents them for API versions
2021-08-01 and later. ARM expressions such as parameters(), variables(), concat(), format() and resourceId() are resolved where the
template gives the values; a value it does not give becomes a <placeholder> instead of an invented name.
"""
from __future__ import annotations

import json
import re
from typing import Any

LOG_ALERT_TYPE = "microsoft.insights/scheduledqueryrules"
METRIC_ALERT_TYPE = "microsoft.insights/metricalerts"
DEPLOYMENT_TYPE = "microsoft.resources/deployments"
SEVERITY_NAMES = {0: "Critical", 1: "Error", 2: "Warning", 3: "Informational", 4: "Verbose"}
MAX_DEPTH = 12
MAX_RESOURCE_JSON = 15_000


# ---------------------------------------------------------------------------------------------------------------------
# JSON with comments (ARM templates may contain // and /* */)
# ---------------------------------------------------------------------------------------------------------------------

def strip_json_comments(text: str) -> str:
    out: list[str] = []
    i, n, in_string = 0, len(text), False
    while i < n:
        c = text[i]
        if in_string:
            out.append(c)
            if c == "\\" and i + 1 < n:
                out.append(text[i + 1])
                i += 2
                continue
            in_string = c != '"'
            i += 1
        elif c == '"':
            in_string = True
            out.append(c)
            i += 1
        elif text.startswith("//", i):
            end = text.find("\n", i)
            i = n if end == -1 else end
        elif text.startswith("/*", i):
            end = text.find("*/", i + 2)
            i = n if end == -1 else end + 2
        else:
            out.append(c)
            i += 1
    return "".join(out)


# ---------------------------------------------------------------------------------------------------------------------
# ARM expressions: "[concat(parameters('name'), '-alert')]"
# ---------------------------------------------------------------------------------------------------------------------

class Unresolved(Exception):
    """An ARM expression that the template does not give enough information to evaluate."""


class _Placeholder(str):
    """A value the template does not provide, shown as <name>."""


class _Parser:
    def __init__(self, text: str):
        self.s, self.i = text, 0

    def _space(self) -> None:
        while self.i < len(self.s) and self.s[self.i].isspace():
            self.i += 1

    def _peek(self) -> str:
        self._space()
        return self.s[self.i] if self.i < len(self.s) else ""

    def _expect(self, char: str) -> None:
        if self._peek() != char:
            raise Unresolved(f"expected '{char}'")
        self.i += 1

    def parse(self) -> tuple:
        node = self._expr()
        if self._peek():
            raise Unresolved("unexpected text after the expression")
        return node

    def _expr(self) -> tuple:
        node = self._primary()
        while True:
            c = self._peek()
            if c == ".":
                self.i += 1
                self._space()
                match = re.compile(r"[A-Za-z_]\w*").match(self.s, self.i)
                if not match:
                    raise Unresolved("bad property name")
                self.i = match.end()
                node = ("prop", node, match.group(0))
            elif c == "[":
                self.i += 1
                index = self._expr()
                self._expect("]")
                node = ("index", node, index)
            else:
                return node

    def _primary(self) -> tuple:
        c = self._peek()
        if c == "'":
            self.i += 1
            chars: list[str] = []
            while self.i < len(self.s):
                if self.s[self.i] == "'":
                    if self.s[self.i + 1:self.i + 2] == "'":
                        chars.append("'")
                        self.i += 2
                        continue
                    self.i += 1
                    return ("str", "".join(chars))
                chars.append(self.s[self.i])
                self.i += 1
            raise Unresolved("unterminated string")
        number = re.compile(r"-?\d+(\.\d+)?").match(self.s, self.i)
        if number and c and (c.isdigit() or c == "-"):
            self.i = number.end()
            text = number.group(0)
            return ("num", float(text) if "." in text else int(text))
        name = re.compile(r"[A-Za-z_]\w*").match(self.s, self.i)
        if not name:
            raise Unresolved("unexpected character")
        self.i = name.end()
        if self._peek() == "(":
            self.i += 1
            args: list[tuple] = []
            if self._peek() != ")":
                while True:
                    args.append(self._expr())
                    if self._peek() == ",":
                        self.i += 1
                        continue
                    break
            self._expect(")")
            return ("call", name.group(0).lower(), args)
        return ("name", name.group(0))


class _Context:
    def __init__(self, template: dict[str, Any], params: dict[str, Any] | None = None):
        self.template = template if isinstance(template, dict) else {}
        self.params = params or {}
        self.unresolved: list[str] = []

    def note(self, text: str) -> None:
        if text not in self.unresolved:
            self.unresolved.append(text)

    def parameter(self, name: str, depth: int) -> Any:
        if name in self.params:
            return self.params[name]
        declared = (self.template.get("parameters") or {}).get(name)
        if isinstance(declared, dict) and "defaultValue" in declared:
            return _resolve(declared["defaultValue"], self, depth + 1)
        self.note(f"parameter '{name}' has no value in the template")
        return _Placeholder(f"<{name}>")

    def variable(self, name: str, depth: int) -> Any:
        variables = self.template.get("variables") or {}
        if name in variables:
            return _resolve(variables[name], self, depth + 1)
        raise Unresolved(f"variable '{name}' is not defined")


def _text(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    return value if isinstance(value, str) else json.dumps(value) if isinstance(value, (dict, list)) else str(value)


def _eval(node: tuple, ctx: _Context, depth: int) -> Any:
    kind = node[0]
    if kind in ("str", "num"):
        return node[1]
    if kind == "prop":
        base = _eval(node[1], ctx, depth)
        if isinstance(base, dict):
            for key, value in base.items():
                if str(key).lower() == node[2].lower():
                    return value
        raise Unresolved(f"no property '{node[2]}'")
    if kind == "index":
        base, index = _eval(node[1], ctx, depth), _eval(node[2], ctx, depth)
        try:
            return base[index]
        except (KeyError, IndexError, TypeError):
            raise Unresolved("bad index") from None
    if kind == "name":
        raise Unresolved(f"unknown name '{node[1]}'")
    name, args = node[1], [_eval(a, ctx, depth) for a in node[2]]
    if name == "parameters" and len(args) == 1:
        return ctx.parameter(str(args[0]), depth)
    if name == "variables" and len(args) == 1:
        return ctx.variable(str(args[0]), depth)
    if name == "concat":
        if args and all(isinstance(a, list) for a in args):
            return [item for a in args for item in a]
        return "".join(_text(a) for a in args)
    if name == "format" and args:
        return re.sub(r"\{(\d+)\}", lambda m: _text(args[int(m.group(1)) + 1]) if int(m.group(1)) + 1 < len(args) else m.group(0), _text(args[0]))
    if name == "tolower" and len(args) == 1:
        return _text(args[0]).lower()
    if name == "toupper" and len(args) == 1:
        return _text(args[0]).upper()
    if name == "string" and len(args) == 1:
        return _text(args[0])
    if name == "replace" and len(args) == 3:
        return _text(args[0]).replace(_text(args[1]), _text(args[2]))
    if name == "resourcegroup" and not args:
        return {"name": _Placeholder("<resourceGroup>"), "location": _Placeholder("<location>"), "id": "/subscriptions/<subscriptionId>/resourceGroups/<resourceGroup>"}
    if name == "subscription" and not args:
        return {"subscriptionId": _Placeholder("<subscriptionId>"), "tenantId": _Placeholder("<tenantId>"), "id": "/subscriptions/<subscriptionId>"}
    if name == "resourceid" and len(args) >= 2 and "/" in _text(args[0]) and not _text(args[0]).startswith("/"):
        names = "/".join(_text(a) for a in args[1:])
        return f"/subscriptions/<subscriptionId>/resourceGroups/<resourceGroup>/providers/{_text(args[0])}/{names}"
    raise Unresolved(f"'{name}' cannot be evaluated here")


def _resolve(value: Any, ctx: _Context, depth: int = 0) -> Any:
    """The value with every ARM expression in it evaluated (or replaced by a <placeholder>)."""
    if depth > MAX_DEPTH:
        return value
    if isinstance(value, dict):
        return {k: _resolve(v, ctx, depth + 1) for k, v in value.items()}
    if isinstance(value, list):
        return [_resolve(v, ctx, depth + 1) for v in value]
    if not isinstance(value, str):
        return value
    if value.startswith("[["):
        return value[1:]
    if value.startswith("[") and value.endswith("]"):
        inner = value[1:-1]
        try:
            return _eval(_Parser(inner).parse(), ctx, depth)
        except Unresolved as exc:
            ctx.note(f"{inner[:80]} ({exc})")
            return f"<unresolved: {inner[:60]}>"
    return value


# ---------------------------------------------------------------------------------------------------------------------
# Finding the alert in the template
# ---------------------------------------------------------------------------------------------------------------------

def load_arm(text: str) -> Any:
    return json.loads(strip_json_comments(text))


def _resources(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, list):
        return [r for r in value if isinstance(r, dict)]
    if isinstance(value, dict):  # languageVersion 2.0 templates name their resources
        return [r for r in value.values() if isinstance(r, dict)]
    return []


def find_alerts(document: Any) -> list[tuple[dict[str, Any], _Context]]:
    """Every log or metric alert in the document with the context needed to resolve its expressions (nested deployments included)."""
    found: list[tuple[dict[str, Any], _Context]] = []

    def visit_resource(resource: dict[str, Any], ctx: _Context, depth: int) -> None:
        if depth > MAX_DEPTH:
            return
        rtype = str(_resolve(resource.get("type"), ctx)).lower()
        if rtype in (LOG_ALERT_TYPE, METRIC_ALERT_TYPE):
            found.append((resource, ctx))
        elif rtype == DEPLOYMENT_TYPE:
            properties = resource.get("properties") or {}
            inner = properties.get("template")
            if isinstance(inner, dict):
                values = {k: _resolve(v.get("value"), ctx) for k, v in (properties.get("parameters") or {}).items() if isinstance(v, dict) and "value" in v}
                inner_ctx = _Context(inner, values)
                for child in _resources(inner.get("resources")):
                    visit_resource(child, inner_ctx, depth + 1)
        for child in _resources(resource.get("resources")):
            visit_resource(child, ctx, depth + 1)

    if isinstance(document, list):
        ctx = _Context({})
        for resource in _resources(document):
            visit_resource(resource, ctx, 0)
    elif isinstance(document, dict):
        if "resources" in document:
            ctx = _Context(document)
            for resource in _resources(document["resources"]):
                visit_resource(resource, ctx, 0)
        elif "type" in document:
            visit_resource(document, _Context({}), 0)
    return found


# ---------------------------------------------------------------------------------------------------------------------
# Human wording
# ---------------------------------------------------------------------------------------------------------------------

_DURATION = re.compile(r"^P(?:(\d+)D)?(?:T(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?)?$", re.IGNORECASE)


def human_duration(iso: Any) -> str:
    """'PT5M' -> '5 minutes'; anything that is not an ISO 8601 duration is returned as text."""
    match = _DURATION.match(str(iso or "").strip())
    if not match or not any(match.groups()):
        return str(iso or "")
    parts = [(match.group(1), "day"), (match.group(2), "hour"), (match.group(3), "minute"), (match.group(4), "second")]
    return " ".join(f"{int(n)} {unit}{'' if int(n) == 1 else 's'}" for n, unit in parts if n)


_OPERATORS = {
    "greaterthan": "greater than", "greaterthanorequal": "at least", "lessthan": "less than", "lessthanorequal": "at most",
    "equals": "equal to", "equal": "equal to", "greaterorlessthan": "outside the learned range",
}
_AGGREGATIONS = {"average": "average", "count": "count", "maximum": "maximum", "minimum": "minimum", "total": "total"}


def _operator(value: Any) -> str:
    return _OPERATORS.get(str(value or "").lower(), str(value or ""))


def _names(ids: Any) -> list[str]:
    return [str(i).rstrip("/").split("/")[-1] for i in ids] if isinstance(ids, list) else []


def _product_of(resource_types: list[str], scopes: list[str]) -> str | None:
    if resource_types:
        return resource_types[0]
    for scope in scopes:
        found = re.findall(r"/providers/([^/]+/[^/]+)/", scope + "/")
        if found:
            return found[-1]
    return None


def _int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _flag(value: Any) -> Any:
    """True or False for a flag written as a boolean or as the text "true" / "false" (the 2018-04-16 format writes text); anything else as it is."""
    if isinstance(value, str) and value.strip().lower() in ("true", "false"):
        return value.strip().lower() == "true"
    return value


def _minutes(value: Any) -> str | None:
    minutes = _int(value)
    return f"PT{minutes}M" if minutes else None


# ---------------------------------------------------------------------------------------------------------------------
# One alert resource -> facts
# ---------------------------------------------------------------------------------------------------------------------

def _legacy_log_alert(resource: dict[str, Any], props: dict[str, Any]) -> dict[str, Any]:
    """A log alert in the older 2018-04-16 format, as Microsoft documents it: the query and its data source in `source`, the timing in
    `schedule`, and the severity, action group, threshold and throttling in `action`."""
    source = props.get("source") if isinstance(props.get("source"), dict) else {}
    schedule = props.get("schedule") if isinstance(props.get("schedule"), dict) else {}
    action = props.get("action") if isinstance(props.get("action"), dict) else {}
    trigger = action.get("trigger") if isinstance(action.get("trigger"), dict) else {}
    metric = trigger.get("metricTrigger") if isinstance(trigger.get("metricTrigger"), dict) else {}
    azns = action.get("aznsAction") if isinstance(action.get("aznsAction"), dict) else {}
    scopes = [str(s) for s in [source.get("dataSourceId"), *(source.get("authorizedResources") or [])] if s]
    op, threshold = _operator(trigger.get("thresholdOperator")), trigger.get("threshold")
    sentence = f"the number of rows returned by the alert query is {op} {threshold}" if threshold is not None and op else "the number of rows returned by the alert query meets the alert condition"
    if metric:
        kind = str(metric.get("metricTriggerType") or "").lower()
        sentence += f", with a metric trigger on column {metric.get('metricColumn') or 'the metric column'} ({kind + ': ' if kind else ''}{_operator(metric.get('thresholdOperator'))} {metric.get('threshold')})"
    return {
        "type": "log", "source": "Log", "arm_type": "Microsoft.Insights/scheduledQueryRules", "kind": "LogAlert", "legacy": True,
        "api_version": resource.get("apiVersion"), "resource_name": resource.get("name"),
        "name": props.get("displayName") or resource.get("name"), "description": props.get("description"),
        "severity": _int(action.get("severity")), "enabled": _flag(props.get("enabled")),
        "evaluation_frequency": _minutes(schedule.get("frequencyInMinutes")), "window_size": _minutes(schedule.get("timeWindowInMinutes")),
        "scopes": scopes, "target_resource_types": [], "product": _product_of([], scopes),
        "query": source.get("query"), "condition_sentence": sentence,
        "condition": {
            "time_aggregation": "Count", "operator": trigger.get("thresholdOperator"), "threshold": threshold,
            "metric_measure_column": metric.get("metricColumn"), "resource_id_column": None, "dimensions": [], "failing_periods": None,
            "criterion_type": None, "alert_sensitivity": None, "extra_conditions": 0,
        },
        "action_groups": _names(azns.get("actionGroup")),
        "auto_mitigate": _flag(props.get("autoMitigate")), "mute_actions_duration": None, "override_query_time_range": None,
        "throttle_minutes": _int(action.get("throttlingInMin")),
    }


def _log_alert(resource: dict[str, Any], props: dict[str, Any]) -> dict[str, Any]:
    if "criteria" not in props and (isinstance(props.get("source"), dict) or isinstance(props.get("schedule"), dict)):
        return _legacy_log_alert(resource, props)
    criteria = [c for c in ((props.get("criteria") or {}).get("allOf") or []) if isinstance(c, dict)]
    cond = criteria[0] if criteria else {}
    scopes = [str(s) for s in props.get("scopes") or []]
    types = [str(t) for t in props.get("targetResourceTypes") or []]
    failing = cond.get("failingPeriods") or {}
    dimensions = [{"name": d.get("name"), "operator": d.get("operator"), "values": d.get("values")} for d in cond.get("dimensions") or [] if isinstance(d, dict)]
    aggregation = str(cond.get("timeAggregation") or "")
    measure = cond.get("metricMeasureColumn")
    op, threshold = _operator(cond.get("operator")), cond.get("threshold")
    if aggregation.lower() == "count" or not aggregation:
        what = "the number of rows returned by the alert query"
    else:
        what = f"the {_AGGREGATIONS.get(aggregation.lower(), aggregation.lower())} of column {measure or 'the measure column'} returned by the alert query"
    sentence = f"{what} is {op} {threshold}" if threshold is not None and op else f"{what} meets the alert condition"
    n_periods, n_min = _int(failing.get("numberOfEvaluationPeriods")), _int(failing.get("minFailingPeriodsToAlert"))
    if n_periods and n_periods > 1 and n_min:
        sentence += f" in at least {n_min} of {n_periods} evaluation periods"
    if dimensions:
        sentence += f", split by {', '.join(str(d['name']) for d in dimensions if d.get('name'))}"
    return {
        "type": "log", "source": "Log", "arm_type": "Microsoft.Insights/scheduledQueryRules", "kind": resource.get("kind") or "LogAlert",
        "api_version": resource.get("apiVersion"), "resource_name": resource.get("name"),
        "name": props.get("displayName") or resource.get("name"), "description": props.get("description"),
        "severity": _int(props.get("severity")), "enabled": _flag(props.get("enabled")),
        "evaluation_frequency": props.get("evaluationFrequency"), "window_size": props.get("windowSize"),
        "scopes": scopes, "target_resource_types": types, "product": _product_of(types, scopes),
        "query": cond.get("query"), "condition_sentence": sentence,
        "condition": {
            "time_aggregation": aggregation or None, "operator": cond.get("operator"), "threshold": threshold,
            "metric_measure_column": measure, "resource_id_column": cond.get("resourceIdColumn"),
            "dimensions": dimensions, "failing_periods": {"evaluation_periods": n_periods, "min_failing": n_min} if n_periods or n_min else None,
            "criterion_type": cond.get("criterionType"), "alert_sensitivity": cond.get("alertSensitivity"), "extra_conditions": max(0, len(criteria) - 1),
        },
        "action_groups": _names((props.get("actions") or {}).get("actionGroups")),
        "auto_mitigate": _flag(props.get("autoMitigate")), "mute_actions_duration": props.get("muteActionsDuration"),
        "override_query_time_range": props.get("overrideQueryTimeRange"),
    }


def _metric_criterion(item: dict[str, Any]) -> dict[str, Any]:
    dimensions = [{"name": d.get("name"), "operator": d.get("operator"), "values": d.get("values")} for d in item.get("dimensions") or [] if isinstance(d, dict)]
    dynamic = str(item.get("criterionType") or "").lower().startswith("dynamic")
    aggregation = _AGGREGATIONS.get(str(item.get("timeAggregation") or "").lower(), str(item.get("timeAggregation") or ""))
    metric = item.get("metricName") or item.get("name")
    namespace = item.get("metricNamespace")
    label = f"the {aggregation} of metric {metric}" + (f" ({namespace})" if namespace else "")
    if dynamic:
        text = f"{label} is {_operator(item.get('operator'))} (dynamic threshold, sensitivity {item.get('alertSensitivity') or 'default'})"
    else:
        text = f"{label} is {_operator(item.get('operator'))} {item.get('threshold')}"
    if dimensions:
        text += f", split by {', '.join(str(d['name']) for d in dimensions if d.get('name'))}"
    return {
        "metric": metric, "namespace": namespace, "aggregation": aggregation, "operator": item.get("operator"), "threshold": item.get("threshold"),
        "criterion_type": item.get("criterionType"), "alert_sensitivity": item.get("alertSensitivity"), "dimensions": dimensions, "text": text,
    }


def _metric_alert(resource: dict[str, Any], props: dict[str, Any]) -> dict[str, Any]:
    criteria = props.get("criteria") if isinstance(props.get("criteria"), dict) else {}
    odata = str(criteria.get("odata.type") or "")
    items = [_metric_criterion(i) for i in criteria.get("allOf") or [] if isinstance(i, dict)]
    scopes = [str(s) for s in props.get("scopes") or []]
    target = props.get("targetResourceType")
    types = [str(target)] if target else []
    if odata.endswith("WebtestLocationAvailabilityCriteria"):
        sentence = f"the web test fails from at least {criteria.get('failedLocationCount')} locations"
    elif items:
        sentence = " and ".join(i["text"] for i in items)
    else:
        sentence = "the metric condition in the alert rule is met"
    return {
        "type": "metric", "source": "Metric", "arm_type": "Microsoft.Insights/metricAlerts", "kind": odata.rsplit(".", 1)[-1] or None,
        "api_version": resource.get("apiVersion"), "resource_name": resource.get("name"), "name": resource.get("name"),
        "description": props.get("description"), "severity": _int(props.get("severity")), "enabled": _flag(props.get("enabled")),
        "evaluation_frequency": props.get("evaluationFrequency"), "window_size": props.get("windowSize"),
        "scopes": scopes, "target_resource_types": types, "product": _product_of(types, scopes), "query": None,
        "condition_sentence": sentence, "condition": {"criteria": items, "odata_type": odata or None},
        "action_groups": _names([a.get("actionGroupId") for a in props.get("actions") or [] if isinstance(a, dict)]),
        "auto_mitigate": _flag(props.get("autoMitigate")), "mute_actions_duration": None, "override_query_time_range": None,
        "target_resource_region": props.get("targetResourceRegion"),
    }


def _normal(text: Any) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(text or "").lower())


def _alert_description(alert: dict[str, Any]) -> str:
    """The wording for a Description row: what makes the alert fire, from the template and not from the model."""
    freq, window = human_duration(alert.get("evaluation_frequency")), human_duration(alert.get("window_size"))
    when = alert["condition_sentence"]
    if window and freq:
        when += f", measured over {window} and evaluated every {freq}"
    elif freq:
        when += f", evaluated every {freq}"
    return when


# ---------------------------------------------------------------------------------------------------------------------
# KQL: a light, forgiving analysis. The full query is what the writer reads; these are hints and checks.
# ---------------------------------------------------------------------------------------------------------------------

def strip_kql_comments(query: str) -> str:
    out: list[str] = []
    i, n, quote = 0, len(query), ""
    while i < n:
        c = query[i]
        if quote:
            out.append(c)
            if c == "\\" and i + 1 < n:
                out.append(query[i + 1])
                i += 2
                continue
            if c == quote:
                quote = ""
        elif c in "\"'":
            quote = c
            out.append(c)
        elif query.startswith("//", i):
            end = query.find("\n", i)
            i = n if end == -1 else end
            continue
        else:
            out.append(c)
        i += 1
    return "".join(out)


def _split_top(text: str, separator: str) -> list[str]:
    """Split at a separator that is outside quotes and brackets."""
    parts, current, depth, quote = [], [], 0, ""
    for c in text:
        if quote:
            current.append(c)
            quote = "" if c == quote else quote
            continue
        if c in "\"'":
            quote = c
        elif c in "([{":
            depth += 1
        elif c in ")]}":
            depth -= 1
        elif c == separator and depth == 0:
            parts.append("".join(current).strip())
            current = []
            continue
        current.append(c)
    parts.append("".join(current).strip())
    return [p for p in parts if p]


_KQL_KEYWORDS = {"let", "set", "print", "datatable", "range", "externaldata", "declare", "restrict", "pattern", "alias", "materialize", "union", "find", "search", "evaluate", "where", "project", "summarize", "extend", "take", "limit", "sort", "order", "top"}
_FILTER_COLUMNS = r"Category|OperationName|ResourceType|ResourceProvider|ResultType|Level|ProviderName|SeverityLevel|EventID|Resource|ResourceId|_ResourceId"
_FILTER = re.compile(rf"\b({_FILTER_COLUMNS})\s*(==|=~|!=|has|contains|startswith|in~?)\s*(\([^)]*\)|\"[^\"]*\"|'[^']*'|\d+)", re.IGNORECASE)


def analyze_kql(query: str | None) -> dict[str, Any]:
    text = strip_kql_comments(query or "")
    result: dict[str, Any] = {"tables": [], "filters": [], "aggregations": [], "group_by": [], "output_columns": [], "time_windows": [], "warnings": []}
    if not text.strip():
        return result
    if text.count('"') % 2 or text.count("(") != text.count(")") or text.count("[") != text.count("]"):
        result["warnings"].append("The query has unbalanced quotes or brackets.")
    if re.search(r"<unresolved|\[parameters\(|\[variables\(", text):
        result["warnings"].append("The query still contains an ARM expression that could not be resolved.")

    let_names = set(re.findall(r"\blet\s+(\w+)\s*=", text))
    tables: list[str] = []

    def add(name: str) -> None:
        if name and name.lower() not in _KQL_KEYWORDS and name not in let_names and name not in tables:
            tables.append(name)

    for statement in _split_top(text, ";"):
        body = re.sub(r"^\s*let\s+\w+\s*=\s*", "", statement)
        head = re.match(r"\s*\(?\s*([A-Za-z_]\w*)\s*(?=[|\n\r]|$)", body)
        if head:
            add(head.group(1))
    for match in re.finditer(r"\bjoin\b[^(]*\(\s*([A-Za-z_]\w*)", text, re.IGNORECASE):
        add(match.group(1))
    for match in re.finditer(r"\bunion\b\s+(?:(?:kind|withsource|isfuzzy)\s*=\s*\w+\s+)*([A-Za-z_]\w*(?:\s*,\s*[A-Za-z_]\w*)*)", text, re.IGNORECASE):
        for name in re.split(r"\s*,\s*", match.group(1)):
            add(name)
    result["tables"] = tables

    seen: set[tuple[str, str]] = set()
    for match in _FILTER.finditer(text):
        column, operator, raw = match.group(1), match.group(2), match.group(3)
        values = re.findall(r"\"([^\"]*)\"|'([^']*)'|(\d+)", raw)
        flat = [a or b or c for a, b, c in values]
        key = (column.lower(), "|".join(flat))
        if flat and key not in seen:
            seen.add(key)
            result["filters"].append({"column": column, "operator": operator, "values": flat})

    result["time_windows"] = [w.strip() for w in re.findall(r"\bago\(([^)]+)\)", text, re.IGNORECASE)]
    summarize = re.search(r"\bsummarize\b(.*?)(?=\n\s*\||$)", text, re.IGNORECASE | re.DOTALL)
    if summarize:
        pieces = re.split(r"\bby\b", summarize.group(1), maxsplit=1, flags=re.IGNORECASE)
        result["aggregations"] = _split_top(pieces[0], ",")
        result["group_by"] = _split_top(pieces[1], ",") if len(pieces) > 1 else []
    projects = re.findall(r"\|\s*project(?:-keep)?\b(.*?)(?=\n\s*\||$)", text, re.IGNORECASE | re.DOTALL)
    if projects:
        result["output_columns"] = [re.split(r"\s*=\s*", c, maxsplit=1)[0].strip() for c in _split_top(projects[-1], ",")]
    elif summarize:
        named = [re.split(r"\s*=\s*", a, maxsplit=1)[0].strip() for a in result["aggregations"] if "=" in a]
        result["output_columns"] = [g.split("=")[0].strip() for g in result["group_by"]] + named
    return result


# ---------------------------------------------------------------------------------------------------------------------
# The entry point
# ---------------------------------------------------------------------------------------------------------------------

def read_alert(arm_text: str | None, kql_text: str | None = None, alert_name: str | None = None) -> dict[str, Any]:
    """Everything the writer needs to know about the alert, from its ARM template and/or its KQL, plus plain-language warnings."""
    warnings: list[str] = []
    arm = {"given": bool((arm_text or "").strip()), "parsed": False, "alerts_found": [], "unresolved": []}
    alert: dict[str, Any] | None = None
    resolved_resource: dict[str, Any] | None = None

    if arm["given"]:
        try:
            document = load_arm(arm_text or "")
        except ValueError as exc:
            warnings.append(f"The ARM template is not valid JSON ({exc}), so its text was given to the writer as it is.")
            document = None
        if document is not None:
            candidates = find_alerts(document)
            arm["parsed"] = True
            if not candidates:
                warnings.append("No log alert (scheduledQueryRules) or metric alert (metricAlerts) was found in the ARM template, so its text was given to the writer as it is.")
            else:
                built = []
                for resource, ctx in candidates:
                    props = _resolve(resource.get("properties") or {}, ctx)
                    resolved = {**{k: _resolve(v, ctx) for k, v in resource.items() if k not in ("properties", "resources")}, "properties": props}
                    facts = (_log_alert if str(resolved.get("type")).lower() == LOG_ALERT_TYPE else _metric_alert)(resolved, props if isinstance(props, dict) else {})
                    built.append((facts, resolved, ctx))
                    for item in ctx.unresolved:
                        if item not in arm["unresolved"]:
                            arm["unresolved"].append(item)
                arm["alerts_found"] = [b[0]["name"] for b in built]
                wanted = _normal(alert_name)
                pick = next((b for b in built if wanted and wanted in (_normal(b[0]["name"]), _normal(b[0]["resource_name"]))), built[0])
                alert, resolved_resource = pick[0], pick[1]
                if len(built) > 1:
                    warnings.append(f"The template defines {len(built)} alerts; the IRP is written for '{alert['name']}'. The others: {', '.join(str(b[0]['name']) for b in built if b[0] is not alert)}.")
                if arm["unresolved"]:
                    warnings.append("Some ARM expressions could not be resolved from the template: " + "; ".join(arm["unresolved"][:4]) + ". They are shown as <placeholders>.")
                if alert["type"] == "log" and alert["condition"].get("extra_conditions"):
                    warnings.append("The log alert has more than one condition; only the first is used.")
                if alert.get("enabled") is False:
                    warnings.append("The alert rule is disabled in the template.")

    query = (kql_text or "").strip() or ((alert or {}).get("query") or "").strip()
    kql = analyze_kql(query)
    kql["query"], kql["source"] = query, ("input" if (kql_text or "").strip() else "arm" if query else None)
    if alert and alert["type"] == "log" and (kql_text or "").strip() and (alert.get("query") or "").strip() and _normal(kql_text) != _normal(alert["query"]):
        warnings.append("The query you gave differs from the query in the ARM template; the one you gave is used.")
    if alert and alert["type"] == "log" and not query:
        warnings.append("The log alert has no query, so the steps cannot be tied to what the alert measures.")
    warnings.extend(kql["warnings"])

    severity = alert.get("severity") if alert else None
    return {
        "has_definition": bool(alert or query),
        "arm": arm,
        "alert": alert,
        "kql": kql,
        "severity_name": SEVERITY_NAMES.get(severity) if severity is not None else None,
        "description_sentence": _alert_description(alert) if alert else None,
        "resolved_resource_json": json.dumps(resolved_resource, indent=1, default=str)[:MAX_RESOURCE_JSON] if resolved_resource else None,
        "warnings": warnings,
    }


def alerts_in(arm_text: str | None) -> tuple[list[dict[str, Any]], str | None]:
    """The facts of every alert (log and metric) in an ARM template: (alerts, why the template could not be read, or None).

    Used to describe an alert that a pull request changes. It never raises: a template that is not valid JSON is reported, and an
    alert that cannot be read is left out.
    """
    try:
        document = load_arm(arm_text or "")
    except ValueError as exc:
        return [], f"not valid JSON ({exc})"
    alerts: list[dict[str, Any]] = []
    try:
        for resource, ctx in find_alerts(document):
            props = _resolve(resource.get("properties") or {}, ctx)
            resolved = {**{k: _resolve(v, ctx) for k, v in resource.items() if k not in ("properties", "resources")}, "properties": props}
            build = _log_alert if str(resolved.get("type")).lower() == LOG_ALERT_TYPE else _metric_alert
            alerts.append(build(resolved, props if isinstance(props, dict) else {}))
    except Exception:  # an expression this reader does not understand must never stop a review
        return alerts, None
    return alerts, None


def facts_for_prompt(facts: dict[str, Any]) -> str:
    """The facts as the writer reads them."""
    lines: list[str] = []
    alert = facts.get("alert")
    if alert:
        lines += [
            f"- Alert rule name: {alert['name']}",
            f"- Alert type: {'log alert (scheduledQueryRules)' if alert['type'] == 'log' else 'metric alert (metricAlerts)'}; the IRP's Source is {alert['source']}",
            f"- The alert fires when {facts['description_sentence']}",
        ]
        if facts.get("severity_name"):
            lines.append(f"- Severity (from the ARM template): {facts['severity_name']}")
        if alert.get("product"):
            lines.append(f"- Target resource type: {alert['product']}")
        if alert.get("scopes"):
            lines.append("- Scope (where the alert's data is queried; it is NOT necessarily the resource being monitored, so never reuse its names for another resource): "
                         + "; ".join(alert["scopes"][:3]))
        if alert.get("action_groups"):
            lines.append("- Action group(s): " + ", ".join(alert["action_groups"]))
        if alert.get("description"):
            lines.append(f"- Description in the template: {alert['description']}")
    kql = facts.get("kql") or {}
    if kql.get("query"):
        lines.append("\nALERT QUERY (KQL):\n<alert_query>\n" + kql["query"] + "\n</alert_query>")
        hints = []
        if kql.get("tables"):
            hints.append("tables: " + ", ".join(kql["tables"]))
        for f in kql.get("filters", [])[:6]:
            hints.append(f"filter {f['column']} {f['operator']} {', '.join(f['values'])}")
        if kql.get("aggregations"):
            hints.append("aggregates: " + "; ".join(kql["aggregations"][:4]))
        if kql.get("group_by"):
            hints.append("grouped by: " + ", ".join(kql["group_by"][:6]))
        if kql.get("output_columns"):
            hints.append("output columns: " + ", ".join(kql["output_columns"][:12]))
        if hints:
            lines.append("Read from the query: " + " | ".join(hints))
    if facts.get("resolved_resource_json"):
        lines.append("\nALERT RULE FROM THE ARM TEMPLATE (expressions resolved; <name> means the template gives no value):\n<arm_alert>\n" + facts["resolved_resource_json"] + "\n</arm_alert>")
    return "\n".join(lines)


def public_facts(facts: dict[str, Any]) -> dict[str, Any]:
    """The facts as the page shows them: everything except the resolved ARM text, which is only for the writer."""
    return {k: v for k, v in facts.items() if k != "resolved_resource_json"}


def arm_severity(facts: dict[str, Any]) -> str | None:
    """The severity the ARM template gives, written the way the page's list writes it: 'Sev1 (Error)'."""
    alert = facts.get("alert") or {}
    level = alert.get("severity")
    return f"Sev{level} ({SEVERITY_NAMES[level]})" if level in SEVERITY_NAMES else None


def scope_names(facts: dict[str, Any]) -> list[dict[str, str]]:
    """The resource groups and resource names the alert's scopes spell out (values that are <placeholders> are left out)."""
    found: list[dict[str, str]] = []
    for scope in (facts.get("alert") or {}).get("scopes") or []:
        group = re.search(r"/resourceGroups/([^/]+)", scope, re.IGNORECASE)
        kind = re.search(r"/providers/([^/]+/[^/]+)/([^/]+)", scope, re.IGNORECASE)
        group_name, resource_name = (group.group(1) if group else ""), (kind.group(2) if kind else "")
        entry = {"resource_group": "" if "<" in group_name else group_name, "type": kind.group(1) if kind else "", "name": "" if "<" in resource_name else resource_name}
        if entry["resource_group"] or entry["name"]:
            found.append(entry)
    return found


def workspace_name(facts: dict[str, Any]) -> str:
    """The Log Analytics workspace the alert's scope names, or ''."""
    return next((s["name"] for s in scope_names(facts) if s["type"].lower() == "microsoft.operationalinsights/workspaces"), "")


def is_government_cloud(facts: dict[str, Any], *extra: str) -> bool:
    """True when the alert's name, scope or location points at Azure Government (usgov*, usdod*)."""
    alert = facts.get("alert") or {}
    haystack = " ".join([str(alert.get("name") or ""), " ".join(alert.get("scopes") or []), str(facts.get("resolved_resource_json") or ""), *extra])
    return bool(re.search(r"us(?:gov|dod)", haystack, re.IGNORECASE))


def evaluation_note(facts: dict[str, Any]) -> str:
    """When the alert can be expected to resolve after a fix, from how the template evaluates it."""
    alert = facts.get("alert") or {}
    if alert.get("auto_mitigate") is False:
        return "This alert does not resolve by itself: resolve it in Azure Monitor once the fix is verified."
    frequency = human_duration(alert.get("evaluation_frequency"))
    return f"The alert is re-evaluated every {frequency}, so it can take up to that long to resolve after the fix." if frequency else ""
