"""Read per-test outcomes from pytest reports and map them to case ids.

Each test node keeps only its final outcome. pytest-rerunfailures attempts
(result "rerun") are ignored, so a case that passed on retry counts as passed.
Anything other than "passed" is non-pass and is rerun through the custom marker.
"""

import html
import json
import os
import re

from marker_updater import DEF_RE, MAP_RE, decorator_block, override_case_ids

LONG_NAME_ID_RE = re.compile(r"(?:_|^)(?:tc|TC|Tc|c|C)?(\d{4,})(?=_|$)")
NODE_RE = re.compile(r"([\w./\\+-]+::test_\w+(?:\[[^\]]*\])?)")
JSON_BLOB_RE = re.compile(r"data-jsonblob=(['\"])(.*?)\1", re.DOTALL)
COL_RESULT_RE = re.compile(r"col-result[^>]*>\s*([A-Za-z]+)", re.IGNORECASE)
COL_NAME_RE = re.compile(r"col-name[^>]*>(.*?)</td>", re.IGNORECASE | re.DOTALL)
VERBOSE_RE = re.compile(
    r"^(\S+::test_\w+(?:\[[^\]]*\])?)\s+"
    r"(PASSED|FAILED|ERROR|SKIPPED|XFAIL|XPASS)\b",
    re.IGNORECASE | re.MULTILINE,
)
SUMMARY_RE = re.compile(
    r"^(FAILED|ERROR|SKIPPED|XFAIL|XPASS)\s+(\S+::test_\w+(?:\[[^\]]*\])?)",
    re.IGNORECASE | re.MULTILINE,
)
IGNORED_RESULTS = {"rerun", "retry", ""}


def outcomes_from_reports(report_files):
    """Return {test node: final result} for the given reports.

    Reports are read oldest first, so a newer report overrides an older one.
    """
    ordered = sorted(
        (path for path in report_files or [] if path and os.path.isfile(path)),
        key=os.path.getmtime,
    )
    outcomes = {}
    for path in ordered:
        try:
            with open(path, "r", encoding="utf-8", errors="ignore") as handle:
                content = handle.read()
        except OSError:
            continue
        for node, result in parse_report_text(content):
            outcomes[node] = result
    return outcomes


def parse_report_text(content):
    """Return [(node, result)] in file order. Final attempt per node wins."""
    rows = _parse_json_blob(content)
    if not rows:
        rows = _parse_html_rows(content)
    if not rows:
        rows = _parse_terminal(content)
    final = {}
    for node, result in rows:
        if result in IGNORED_RESULTS:
            continue
        final[node] = result
    return list(final.items())


def case_ids_for_nodes(nodes, tests_directory):
    """Return {node: ["C12345", ...]} using the test sources under tests_directory."""
    index = load_test_index(tests_directory)
    mapped = {}
    for node in nodes:
        mapped[node] = _ids_for_node(node, index)
    return mapped


def load_test_index(directory):
    """Map test function name to the case ids declared on each matching function."""
    index = {}
    if not directory or not os.path.isdir(directory):
        return index
    for root, dirs, files in os.walk(directory):
        dirs[:] = [name for name in dirs if name != "__pycache__"]
        for file_name in files:
            if not file_name.endswith(".py"):
                continue
            path = os.path.join(root, file_name)
            try:
                with open(path, "r", encoding="utf-8", errors="surrogateescape") as handle:
                    lines = handle.readlines()
            except OSError:
                continue
            for line_number, line in enumerate(lines):
                match = DEF_RE.match(line.replace("\r\n", "\n").replace("\r", "\n"))
                if not match:
                    continue
                test_name = match.group(2)
                start = decorator_block(lines, line_number)
                block = "".join(lines[start:line_number]) + test_name
                index.setdefault(test_name, []).append({
                    "file": file_name.lower(),
                    "ids": _ids_for_function(path, test_name, block),
                })
    return index


def _ids_for_node(node, index):
    path_part, function_name = _split_node(node)
    entries = index.get(function_name) or []
    file_name = os.path.basename(path_part).lower()
    chosen = [entry for entry in entries if file_name and entry["file"] == file_name]
    if not chosen:
        chosen = entries
    ids = []
    for entry in chosen:
        for case_id in entry["ids"]:
            if case_id not in ids:
                ids.append(case_id)
    return [f"C{case_id}" for case_id in ids]


def _ids_for_function(path, test_name, block):
    overrides = sorted(override_case_ids(path, test_name), key=int)
    name_ids = LONG_NAME_ID_RE.findall(test_name)
    if overrides:
        return list(dict.fromkeys(name_ids + overrides))
    map_ids = MAP_RE.findall(block)
    if map_ids:
        return list(dict.fromkeys(map_ids))
    return list(dict.fromkeys(name_ids))


def _parse_json_blob(content):
    match = JSON_BLOB_RE.search(content)
    if not match:
        return []
    try:
        payload = json.loads(html.unescape(match.group(2)))
    except json.JSONDecodeError:
        return []
    tests = payload.get("tests") if isinstance(payload, dict) else None
    if not isinstance(tests, dict):
        return []
    rows = []
    for node, attempts in tests.items():
        if isinstance(attempts, dict):
            attempts = [attempts]
        if not isinstance(attempts, list) or not attempts:
            continue
        last = attempts[-1] if isinstance(attempts[-1], dict) else {}
        node_id = _clean_node(last.get("testId") or node)
        result = _normalize_result(last.get("result"))
        if node_id and result:
            rows.append((node_id, result))
    return rows


def _parse_html_rows(content):
    if "results-table-row" not in content.lower():
        return []
    rows = []
    for part in re.split(r"results-table-row", content, flags=re.IGNORECASE)[1:]:
        result_match = COL_RESULT_RE.search(part)
        name_match = COL_NAME_RE.search(part)
        if not result_match or not name_match:
            continue
        node = _clean_node(re.sub(r"<[^>]+>", "", name_match.group(1)))
        result = _normalize_result(result_match.group(1))
        if node and result:
            rows.append((node, result))
    return rows


def _parse_terminal(content):
    rows = [
        (_clean_node(match.group(1)), _normalize_result(match.group(2)))
        for match in VERBOSE_RE.finditer(content)
    ]
    if not rows:
        rows = [
            (_clean_node(match.group(2)), _normalize_result(match.group(1)))
            for match in SUMMARY_RE.finditer(content)
        ]
    return [(node, result) for node, result in rows if node and result]


def _normalize_result(value):
    text = str(value or "").strip().lower()
    if text in {"errors", "error"}:
        return "error"
    if text in {"xfail", "xfailed"}:
        return "xfailed"
    if text in {"xpass", "xpassed"}:
        return "xpassed"
    if text == "passed":
        return "passed"
    if text == "failed":
        return "failed"
    if text == "skipped":
        return "skipped"
    return text


def _clean_node(node):
    text = html.unescape(str(node or "")).strip()
    match = NODE_RE.search(text.replace("\\", "/"))
    return match.group(1) if match else ""


def _split_node(node):
    base = node.split("[", 1)[0]
    if "::" not in base:
        return "", base
    path_part, function_name = base.rsplit("::", 1)
    return path_part, function_name
