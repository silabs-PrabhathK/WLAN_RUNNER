"""Create the harness of one setup inside a milestone, for NCP and SoC.

Usage: python harness_updater.py <milestone> <workspace> <NCP|SoC> [<setup>]

Both products work the same way. Only the default harness name differs
(PRODUCT_DEFAULT_FILES in sanity_config.py) and the Resources folder:

  default harness : <milestone>\\utf_wifi\\config\\harnesses\\<default harness>
  source harness  : the previous milestone's harness for the setup, else
                    Resources\\<product>
  result          : keys the default has and the source lacks are added, the
                    preconditions from sanity_config.py are applied (they win),
                    and the file is written to the milestone and Resources.
"""

import io
import os
import re
import sys

from ruamel.yaml import YAML

from product_common import (
    DEFAULT_WORKSPACE,
    console_utf8,
    milestone_folder,
    parse_args,
    read_text,
    resources_folder,
    write_text,
)
from sanity_config import EXECUTION_CONFIG, HARNESS_PRECONDITIONS, HARNESS_SKIP_KEYS, PRODUCT_DEFAULT_FILES


class YAMLNull:
    """YAML token ``null``. Empty scalars stay None and dump as blank."""

    def __eq__(self, other):
        return isinstance(other, YAMLNull)

    def __hash__(self):
        return hash("YAMLNull")

    def __repr__(self):
        return "null"


def _construct_explicit_null(loader, node):
    if node.value == "null":
        return YAMLNull()
    return None


def _represent_explicit_null(representer, data):
    return representer.represent_scalar(
        "tag:yaml.org,2002:null",
        "null",
    )


yaml = YAML()
yaml.preserve_quotes = True
yaml.width = 4096
yaml.indent(mapping=4, sequence=6, offset=4)
yaml.boolean_representation = ["False", "True"]
yaml.constructor.add_constructor(
    "tag:yaml.org,2002:null",
    _construct_explicit_null,
)
yaml.representer.add_representer(
    YAMLNull,
    _represent_explicit_null,
)

# Names the previous harness and the current default use for one setting.
# The previous name stays in the setup harness. The default name is not added
# beside it, and a precondition may use either name.
KEY_ALIASES = {
    "devices.aws_s3_boto3.interfaces.s3.region_name":
        "devices.aws_s3_boto3.interfaces.s3.region",
}

KEY_LINE = re.compile(
    r"^(?:-\s+)?([A-Za-z_][\w]*)\s*:"
)


def harness_file_name(setup):
    """Harness file name of a setup, as set in EXECUTION_CONFIG."""
    return os.path.basename(
        str((EXECUTION_CONFIG.get(setup) or {}).get("harness") or "").strip()
    )


def get_previous_milestone(current_milestone):
    """Return the previous folder name, keeping the same prefix.

    M99 becomes M98. Milestone100 becomes Milestone99.
    """
    text = str(current_milestone or "")
    match = re.search(r"(\d+)", text)
    if not match:
        return None
    number = int(match.group(1))
    if number <= 0:
        return None
    return text[: match.start(1)] + str(number - 1) + text[match.end(1) :]


def load_yaml_text(text):

    return yaml.load(io.StringIO(text))


def flatten_yaml(data, parent_key=""):

    result = {}

    if isinstance(data, dict):

        for key, value in data.items():

            new_key = (
                f"{parent_key}.{key}"
                if parent_key
                else key
            )

            result.update(
                flatten_yaml(
                    value,
                    new_key
                )
            )

    elif isinstance(data, list):

        result[parent_key] = data

    else:

        result[parent_key] = data

    return result


def _structural_parts(line):
    """Return (disabled, indent, key) for a mapping line.

    Column-0 ``#`` lines are disabled configuration. Indented
    documentation comments and prose are ignored.
    """

    if not line.strip():
        return None

    disabled = False
    body = line

    if line.startswith("#") and not line.startswith("##"):
        body = line[1:]
        stripped = body.strip()
        if not KEY_LINE.match(stripped) and not stripped.startswith("- "):
            return None
        disabled = True
    elif line.lstrip().startswith("#"):
        return None
    else:
        stripped = line.strip()
        if not KEY_LINE.match(stripped) and not stripped.startswith("- "):
            return None

    if stripped.startswith("- "):
        return None

    match = KEY_LINE.match(stripped)
    if not match:
        return None

    indent = len(body) - len(body.lstrip(" "))
    return disabled, indent, match.group(1)


def _walk_key_lines(text):

    stack = []
    active = {}
    disabled = []

    for index, line in enumerate(text.splitlines()):
        parts = _structural_parts(line)
        if parts is None:
            continue

        is_disabled, indent, key = parts

        while stack and stack[-1][0] >= indent:
            stack.pop()

        path = ".".join(
            [item[1] for item in stack] + [key]
        )

        if is_disabled:
            disabled.append((index, path))
        else:
            active[path] = index

        stack.append((indent, key))

    return active, disabled


def _block_indent(line):

    if not line.strip():
        return None

    if line.lstrip().startswith("#"):
        spaces_before = len(line) - len(line.lstrip(" "))
        body = line.lstrip()
        while body.startswith("#"):
            body = body[1:]
        spaces_after = len(body) - len(body.lstrip(" "))
        return spaces_before + spaces_after

    return len(line) - len(line.lstrip(" "))


def _newline(text):

    return "\r\n" if "\r\n" in text else "\n"


def _join_like(original, lines):

    newline = _newline(original)
    text = newline.join(lines)
    if original.endswith(("\n", "\r\n")):
        text += newline
    return text


def _disabled_path_set(text):

    _, disabled = _walk_key_lines(text)
    return {path for _, path in disabled}


def _path_is_disabled(path, disabled):

    current = ""
    for part in path.split("."):
        current = part if not current else current + "." + part
        if current in disabled:
            return True
    return False


def _alias_partner(path):

    for old, new in KEY_ALIASES.items():
        if path == old:
            return new
        if path == new:
            return old
    return None


def _iter_missing_paths(source, dest, prefix=""):

    if not isinstance(source, dict) or not isinstance(dest, dict):
        return

    for key, value in source.items():
        path = f"{prefix}.{key}" if prefix else str(key)

        if key not in dest:
            yield path
            continue

        if isinstance(value, dict) and isinstance(dest[key], dict):
            yield from _iter_missing_paths(
                value,
                dest[key],
                path,
            )


def _new_default_paths(default_yaml, source_yaml, source_text):

    source_paths = set(flatten_yaml(source_yaml))
    disabled = _disabled_path_set(source_text)
    paths = []

    for path in _iter_missing_paths(default_yaml, source_yaml):
        partner = _alias_partner(path)
        if partner and partner in source_paths:
            continue
        if _path_is_disabled(path, disabled):
            continue
        paths.append(path)

    return paths


def _block_end(lines, start):

    key_indent = _block_indent(lines[start])
    end = start + 1
    index = start + 1

    while index < len(lines):
        if not lines[index].strip():
            look = index + 1
            while look < len(lines) and not lines[look].strip():
                look += 1
            if look >= len(lines):
                break
            indent = _block_indent(lines[look])
            if indent is None or indent <= key_indent:
                break
            end = look
            index = look
            continue

        indent = _block_indent(lines[index])
        if indent is None or indent <= key_indent:
            break
        end = index + 1
        index += 1

    return end


def _extract_block(lines, start):

    begin = start
    while begin > 0:
        previous = lines[begin - 1]
        if not previous.strip():
            break
        if previous.lstrip().startswith("#"):
            begin -= 1
            continue
        break

    return lines[begin:_block_end(lines, start)]


def _shift_block(block_lines, delta):

    if delta == 0:
        return list(block_lines)

    shifted = []
    for line in block_lines:
        if not line.strip():
            shifted.append(line)
            continue
        if delta > 0:
            shifted.append((" " * delta) + line)
            continue
        width = -delta
        if line.startswith(" " * width):
            shifted.append(line[width:])
        else:
            shifted.append(line.lstrip(" "))

    return shifted


def _mapping_at(tree, path):

    current = tree
    if path:
        for part in path.split("."):
            if not isinstance(current, dict) or part not in current:
                return None
            current = current[part]
    return current if isinstance(current, dict) else None


def _insert_block(lines, path, block, default_yaml):

    parent, key = path.rsplit(".", 1) if "." in path else ("", path)
    active, _ = _walk_key_lines(_join_like("\n", lines))
    parent_map = _mapping_at(default_yaml, parent)
    sibling_order = list(parent_map) if isinstance(parent_map, dict) else []

    def is_direct_child(candidate):
        if parent:
            prefix = parent + "."
            if not candidate.startswith(prefix):
                return False
            rest = candidate[len(prefix):]
        else:
            rest = candidate
        return "." not in rest

    child_names = {
        candidate.rsplit(".", 1)[-1]: candidate
        for candidate in active
        if is_direct_child(candidate)
    }

    insert_at = None
    if key in sibling_order:
        index = sibling_order.index(key)
        for previous in reversed(sibling_order[:index]):
            if previous in child_names:
                insert_at = _block_end(
                    lines,
                    active[child_names[previous]],
                )
                break
        if insert_at is None:
            for following in sibling_order[index + 1:]:
                if following in child_names:
                    insert_at = active[child_names[following]]
                    break

    if insert_at is None:
        if parent and parent in active:
            insert_at = active[parent] + 1
        else:
            insert_at = len(lines)

    parent_indent = 0
    if parent and parent in active:
        parent_indent = _block_indent(lines[active[parent]]) or 0
    wanted = parent_indent + 4 if parent else 0

    content_index = 0
    while (
        content_index < len(block)
        and block[content_index].lstrip().startswith("#")
    ):
        content_index += 1
    if content_index < len(block):
        current_indent = _block_indent(block[content_index]) or 0
        block = _shift_block(block, wanted - current_indent)

    if (
        insert_at > 0
        and lines[insert_at - 1].strip()
        and block
        and block[0].strip()
    ):
        block = [""] + list(block)

    return lines[:insert_at] + list(block) + lines[insert_at:]


def insert_missing_default_keys(
    source_text,
    source_yaml,
    default_text,
    default_yaml,
    skip=(),
):

    paths = [
        path
        for path in _new_default_paths(default_yaml, source_yaml, source_text)
        if path not in skip
    ]
    if not paths:
        return source_text, 0

    lines = source_text.splitlines()
    default_lines = default_text.splitlines()
    default_active, _ = _walk_key_lines(default_text)
    added = 0

    for path in paths:
        start = default_active.get(path)
        if start is None:
            continue
        block = _extract_block(default_lines, start)
        lines = _insert_block(lines, path, block, default_yaml)
        added += 1
        print(f"Added: {path}")

    return _join_like(source_text, lines), added


def _split_value_and_tail(rest):

    if not rest:
        return "", ""

    if rest[0] in ("'", '"'):
        quote = rest[0]
        index = 1
        while index < len(rest):
            if rest[index] == quote:
                if (
                    quote == "'"
                    and index + 1 < len(rest)
                    and rest[index + 1] == "'"
                ):
                    index += 2
                    continue
                if quote == '"' and rest[index - 1] == "\\":
                    index += 1
                    continue
                index += 1
                break
            index += 1
        return rest[:index], rest[index:]

    comment = rest.find(" #")
    if comment != -1:
        return rest[:comment], rest[comment:]

    stripped = rest.rstrip()
    return stripped, rest[len(stripped):]


def _format_scalar(old_token, new_value):

    token = old_token.strip()

    if isinstance(new_value, bool):
        if token in ("true", "false"):
            return "true" if new_value else "false"
        return "True" if new_value else "False"

    if new_value is None or isinstance(new_value, YAMLNull):
        if token == "":
            return ""
        return "null"

    text = str(new_value)
    if len(token) >= 2 and token[0] == token[-1] and token[0] in ("'", '"'):
        quote = token[0]
        if quote == "'":
            return "'" + text.replace("'", "''") + "'"
        escaped = text.replace("\\", "\\\\").replace('"', '\\"')
        return '"' + escaped + '"'

    if re.fullmatch(r"[A-Za-z0-9_./:+-]*", text):
        return text

    return "'" + text.replace("'", "''") + "'"


def _values_equal(old_token, new_value):

    token = old_token.strip()
    if token == "":
        return new_value is None

    try:
        parsed = yaml.load(token)
    except Exception:
        return False

    if isinstance(new_value, YAMLNull):
        return isinstance(parsed, YAMLNull) or parsed is None

    return parsed == new_value


_LINE_VALUE = re.compile(
    r"^(\s*)([A-Za-z_][\w]*)(\s*:\s*)(.*)$"
)


def _replace_line_value(line, new_value):

    match = _LINE_VALUE.match(line)
    if not match:
        return line, False

    indent, key, colon, rest = match.groups()
    token, tail = _split_value_and_tail(rest)
    if _values_equal(token, new_value):
        return line, False

    rendered = _format_scalar(token, new_value)
    return f"{indent}{key}{colon}{rendered}{tail}", True


def resolve_override_path(paths, configured):

    """Point a sanity_config path at the harness key it should override."""

    path_set = set(paths)
    if configured in path_set:
        return configured

    partner = _alias_partner(configured)
    if partner and partner in path_set:
        return partner

    parts = configured.split(".")
    for length in range(len(parts) - 1, 0, -1):
        suffix = ".".join(parts[-length:])
        matches = [
            key
            for key in path_set
            if key == suffix or key.endswith("." + suffix)
        ]
        if not matches:
            continue
        if len(matches) == 1:
            return matches[0]

        def shared_prefix(match):
            count = 0
            for left, right in zip(parts, match.split(".")):
                if left != right:
                    break
                count += 1
            return count

        ranked = sorted(matches, key=shared_prefix, reverse=True)
        if shared_prefix(ranked[0]) > shared_prefix(ranked[1]):
            return ranked[0]
        return None

    return None


def _format_new_scalar(value):

    if isinstance(value, bool):
        return "True" if value else "False"
    if isinstance(value, int) and not isinstance(value, bool):
        return str(value)
    if isinstance(value, float):
        return str(value)
    if value is None or isinstance(value, YAMLNull):
        return "null"
    return "'" + str(value).replace("'", "''") + "'"


def _insert_new_override(lines, path, value):

    parts = path.split(".")
    active, _ = _walk_key_lines(_join_like("\n", lines))
    existing = ""

    for part in parts[:-1]:
        candidate = part if not existing else existing + "." + part
        if candidate not in active:
            break
        existing = candidate

    depth = len(existing.split(".")) if existing else 0
    missing = parts[depth:]
    if not missing:
        return lines, False

    if existing:
        indent = (_block_indent(lines[active[existing]]) or 0) + 4
        insert_at = _block_end(lines, active[existing])
    else:
        indent = 0
        insert_at = len(lines)

    block = []
    for offset, part in enumerate(missing):
        pad = " " * (indent + (offset * 4))
        if offset == len(missing) - 1:
            block.append(f"{pad}{part}: {_format_new_scalar(value)}")
        else:
            block.append(f"{pad}{part}:")

    if insert_at > 0 and lines[insert_at - 1].strip():
        block = [""] + block

    return lines[:insert_at] + block + lines[insert_at:], True


def apply_preconditions_to_text(text, setup):

    """Apply sanity_config preconditions. Those values win."""

    updates = HARNESS_PRECONDITIONS.get(setup, {})
    if not updates:
        return text, 0

    lines = text.splitlines()
    applied = 0
    flat = flatten_yaml(load_yaml_text(text))
    active, _ = _walk_key_lines(text)

    for configured, value in updates.items():
        target = resolve_override_path(flat, configured)

        if target is None or target not in active:
            lines, added = _insert_new_override(lines, configured, value)
            if not added:
                print(f"Override skipped: {configured}")
                continue
            applied += 1
            print(f"Override: {configured}")
            text = _join_like(text, lines)
            lines = text.splitlines()
            flat = flatten_yaml(load_yaml_text(text))
            active, _ = _walk_key_lines(text)
            continue

        new_line, changed = _replace_line_value(
            lines[active[target]],
            value,
        )
        if not changed:
            continue

        lines[active[target]] = new_line
        applied += 1
        if target == configured:
            print(f"Override: {configured}")
        else:
            print(f"Override: {configured} -> {target}")

    return _join_like(text, lines), applied

def create_setup_harness(milestone, setup, product="NCP", workspace=None):
    """Build one setup harness. Returns True when the file was written."""
    workspace = workspace or DEFAULT_WORKSPACE
    resources = resources_folder(product)
    default_name = PRODUCT_DEFAULT_FILES[product]["harness"]
    harness_name = harness_file_name(setup)
    if not harness_name:
        harness_name = f"{os.path.splitext(default_name)[0]}_{setup}.yaml"

    print("\n====================================")
    print(f"Processing Setup : {setup} ({product})")
    print("====================================")

    if "need_to_update" in harness_name.lower():
        print(f"\n{setup} has no real harness file name in sanity_config.py.")
        return False

    current_folder = milestone_folder(workspace, milestone, "config", "harnesses")
    default_harness = os.path.join(current_folder, default_name)
    if not os.path.isdir(current_folder):
        print(f"\nHarness folder missing: {current_folder}")
        return False

    # Older milestones may still use <default stem>_<setup>.yaml.
    legacy_name = f"{os.path.splitext(default_name)[0]}_{setup}.yaml"
    names = [harness_name] + ([legacy_name] if legacy_name != harness_name else [])

    candidates = []
    previous_milestone = get_previous_milestone(milestone)
    if previous_milestone:
        previous_folder = milestone_folder(workspace, previous_milestone, "config", "harnesses")
        candidates += [(os.path.join(previous_folder, name), previous_milestone) for name in names]
    candidates += [(os.path.join(resources, name), f"Resources\\{product}") for name in names]

    source_harness = None
    source_label = ""
    for path, label in candidates:
        if os.path.isfile(path):
            source_harness = path
            source_label = label
            break

    if not source_harness:
        print("\nNo previous harness or resource harness was found.")
        print(f"Looked for {harness_name}")
        return False

    print(f"\nSource harness: {os.path.basename(source_harness)} ({source_label})")
    source_text = read_text(source_harness)

    default_text = read_text(default_harness)
    if default_text is not None:
        output_text, missing_keys_added = insert_missing_default_keys(
            source_text,
            load_yaml_text(source_text),
            default_text,
            load_yaml_text(default_text),
            skip=HARNESS_SKIP_KEYS.get(setup, []),
        )
        print(f"Default harness : {default_name}")
    else:
        print(f"Default harness not found. Copying the source harness: {default_harness}")
        output_text = source_text
        missing_keys_added = 0

    if setup not in HARNESS_PRECONDITIONS:
        print(f"{setup} has no preconditions in sanity_config.py.")
    output_text, override_count = apply_preconditions_to_text(
        output_text,
        setup,
    )

    output_file = os.path.join(current_folder, harness_name)
    write_text(output_file, output_text)

    os.makedirs(resources, exist_ok=True)
    resource_output = os.path.join(resources, harness_name)
    write_text(resource_output, output_text)

    print(f"\nCreated : {os.path.basename(output_file)}")
    print(f"Resource updated : {os.path.basename(resource_output)}")
    print(f"New keys added : {missing_keys_added}")
    print(f"Config overrides applied : {override_count}")
    return True


def main():
    console_utf8()
    milestone, workspace, product, setup = parse_args(sys.argv)
    if product not in PRODUCT_DEFAULT_FILES:
        print(f"Unknown product: {product}")
        sys.exit(1)
    setups = [setup] if setup else list(HARNESS_PRECONDITIONS.keys())
    failed = []
    for name in setups:
        if not create_setup_harness(milestone, name, product, workspace):
            failed.append(name)
    if failed:
        print("\nHarness update failed for: " + ", ".join(failed))
        sys.exit(1)
    print("\nHarness update completed.")


if __name__ == "__main__":
    main()
