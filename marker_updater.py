"""Add or remove pytest markers on milestone tests.

A test matches a case id when a decorator contains
@pytest.mark.test_src_map_id('C925838'), or the function name contains
that id (c925838, C925838, TC925838).
"""

import ast
import os
import re

from marker_cases import CASE_PATH_OVERRIDES

DEF_RE = re.compile(r"^(\s*)def (test_\w+)\b")
MAP_RE = re.compile(
    r"test_src_map_id\(\s*['\"][A-Za-z]*(\d+)['\"]\s*\)",
    re.IGNORECASE,
)
NAME_ID_RE = re.compile(r"(?:_|^)(?:tc|TC|Tc|c|C)?(\d+)(?=_|$)")
CASE_RE = re.compile(r"^[A-Za-z]*(\d+)$")
MARKER_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def normalize_case_id(value):
    match = CASE_RE.match(str(value).strip().strip("'\""))
    if not match:
        return None
    return match.group(1)


def parse_case_lists(text):
    """Return {list name: [numeric ids]} from assignments, a bare list, or one id per line."""
    text = text.strip()
    if not text:
        return {}

    try:
        tree = ast.parse(text)
    except SyntaxError:
        if text.lstrip().startswith("["):
            tree = ast.parse("IDS = " + text)
        else:
            return {"IDS": _ids_from_lines(text)}

    groups = {}
    loose = []
    for node in tree.body:
        if isinstance(node, ast.Expr) and isinstance(node.value, (ast.List, ast.Tuple)):
            loose.extend(_ids_from_literals(node.value.elts))
            continue
        if not isinstance(node, ast.Assign) or len(node.targets) != 1:
            continue
        target = node.targets[0]
        if not isinstance(target, ast.Name):
            continue
        if not isinstance(node.value, (ast.List, ast.Tuple)):
            continue
        groups[target.id] = _ids_from_literals(node.value.elts)
    if loose:
        groups["IDS"] = loose
    if groups:
        return groups
    return {"IDS": _ids_from_lines(text)}


def _ids_from_literals(elements):
    ids = []
    for element in elements:
        if isinstance(element, ast.Constant) and isinstance(element.value, str):
            raw = element.value
        elif isinstance(element, ast.Name):
            raw = element.id
        else:
            continue
        case_id = normalize_case_id(raw)
        if case_id:
            ids.append(case_id)
    return ids


def _ids_from_lines(text):
    ids = []
    for line in text.splitlines():
        for piece in line.replace(",", " ").split():
            case_id = normalize_case_id(piece)
            if case_id:
                ids.append(case_id)
    return ids


def case_ids_in_text(text):
    return set(MAP_RE.findall(text)) | set(NAME_ID_RE.findall(text))


def override_case_ids(path, test_name):
    """Ids pinned to this test function in CASE_PATH_OVERRIDES."""
    normalized = path.replace("\\", "/").lower()
    ids = set()
    for case_id, (relative, function_name) in CASE_PATH_OVERRIDES.items():
        if function_name != test_name:
            continue
        if normalized.endswith("/" + relative.lower()):
            ids.add(case_id)
    return ids


def decorator_block(lines, def_index):
    start = def_index
    index = def_index - 1
    while index >= 0:
        stripped = lines[index].strip()
        if not stripped or stripped.startswith("@") or stripped.startswith("#"):
            start = index
            index -= 1
            continue
        break
    return start


def already_marked(block_text, marker):
    return re.search(
        rf"@pytest\.mark\.{re.escape(marker)}(\s|\(|$)",
        block_text,
    ) is not None


def apply_markers(directory, jobs):
    """Stamp markers. jobs is a list of (label, case ids, marker name).

    Sanity and regression markers are left in place. The caller removes a
    custom marker itself after the run.
    """
    wanted = {}
    order = []
    normalized = {}
    for label, raw_ids, marker in jobs:
        if not MARKER_NAME_RE.match(marker):
            raise ValueError(f"Marker is not a valid name: {marker}")
        ids = []
        seen = set()
        for raw in raw_ids:
            case_id = normalize_case_id(raw)
            if not case_id or case_id in seen:
                continue
            seen.add(case_id)
            ids.append(case_id)
            wanted.setdefault(case_id, set()).add(marker)
        normalized[label] = ids
        order.append((label, marker))

    found = {case_id: [] for case_id in wanted}
    added = 0
    already = 0
    files_changed = 0
    added_for = {label: 0 for label, _marker in order}
    already_for = {label: 0 for label, _marker in order}

    for root, dirs, files in os.walk(directory):
        dirs[:] = [name for name in dirs if name != "__pycache__"]
        for file_name in files:
            if not file_name.endswith(".py"):
                continue
            path = os.path.join(root, file_name)
            changed, file_added, file_already, per_label = update_file(
                path, wanted, found, order, normalized,
            )
            added += file_added
            already += file_already
            if changed:
                files_changed += 1
            for label, counts in per_label.items():
                added_for[label] += counts[0]
                already_for[label] += counts[1]

    results = []
    for label, marker in order:
        ids = normalized[label]
        missing = [f"C{case_id}" for case_id in ids if not found.get(case_id)]
        results.append({
            "label": label,
            "marker": marker,
            "total": len(ids),
            "matched": len(ids) - len(missing),
            "missing": missing,
            "added": added_for[label],
            "already": already_for[label],
            "files": files_changed,
        })
    return results


def update_file(path, wanted, found, order, normalized):
    with open(path, "r", encoding="utf-8", errors="surrogateescape") as handle:
        lines = handle.readlines()
    newline = "\r\n" if any(line.endswith("\r\n") for line in lines) else "\n"
    inserts = []
    added = 0
    already = 0
    per_label = {label: [0, 0] for label, _marker in order}

    for index, line in enumerate(lines):
        match = DEF_RE.match(line.replace("\r\n", "\n").replace("\r", "\n"))
        if not match:
            continue
        indent, test_name = match.group(1), match.group(2)
        block_start = decorator_block(lines, index)
        block = "".join(lines[block_start:index]) + test_name
        case_ids = case_ids_in_text(block) | override_case_ids(path, test_name)
        markers_needed = []
        for case_id in case_ids:
            if case_id not in wanted:
                continue
            found[case_id].append(f"{os.path.basename(path)}::{test_name}")
            for marker in sorted(wanted[case_id]):
                if marker not in markers_needed:
                    markers_needed.append(marker)
        if not markers_needed:
            continue
        missing = [
            marker for marker in markers_needed
            if not already_marked(block, marker)
        ]
        for label, marker in order:
            if not (case_ids & set(normalized[label])):
                continue
            if marker in missing:
                per_label[label][0] += 1
            else:
                per_label[label][1] += 1
        already += len(markers_needed) - len(missing)
        if missing:
            inserts.append((
                index,
                [f"{indent}@pytest.mark.{marker}{newline}" for marker in missing],
            ))
            added += len(missing)

    if not inserts:
        return False, 0, already, per_label

    for index, new_lines in reversed(inserts):
        lines[index:index] = new_lines
    with open(path, "w", encoding="utf-8", errors="surrogateescape", newline="") as handle:
        handle.writelines(lines)
    return True, added, already, per_label


def remove_marker(directory, marker):
    """Delete @pytest.mark.<marker> lines. Returns (files, lines removed)."""
    if not MARKER_NAME_RE.match(marker):
        raise ValueError(f"Marker is not a valid name: {marker}")
    pattern = re.compile(
        rf"^[ \t]*@pytest\.mark\.{re.escape(marker)}\s*(#.*)?$"
    )
    files_changed = 0
    removed = 0
    if not os.path.isdir(directory):
        return 0, 0
    for root, dirs, files in os.walk(directory):
        dirs[:] = [name for name in dirs if name != "__pycache__"]
        for file_name in files:
            if not file_name.endswith(".py"):
                continue
            path = os.path.join(root, file_name)
            with open(path, "r", encoding="utf-8", errors="surrogateescape") as handle:
                lines = handle.readlines()
            kept = []
            file_removed = 0
            for line in lines:
                if pattern.match(line.rstrip("\r\n")):
                    file_removed += 1
                    continue
                kept.append(line)
            if not file_removed:
                continue
            with open(path, "w", encoding="utf-8", errors="surrogateescape", newline="") as handle:
                handle.writelines(kept)
            files_changed += 1
            removed += file_removed
    return files_changed, removed
