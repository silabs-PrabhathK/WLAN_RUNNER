"""Helpers shared by the NCP and SoC preparation scripts.

harness_updater.py, manifest_updater.py, soc_manifest_updater.py and
soc_secure.py all start the same way:

    python <script> <milestone> <workspace> <product> [<setup>]

Paths, file lookups, file copying and the marker edit in a manifest live here
once, so the scripts only hold what really differs between NCP and SoC.
"""

import os
import shutil
import sys

PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
# What you place: tests folder, test agents and firmware, per product.
RESOURCES_ROOT = os.path.join(PROJECT_ROOT, "Resources")
# What SoC signing needs and you do not touch: keys\, the secure script and
# Simplicity Commander.
SOC_SECURE_ROOT = os.path.join(PROJECT_ROOT, "SoC_Secure")
# What the script creates for you to pick up: manifests, harness, secure files.
OUTPUT_ROOT = os.path.join(PROJECT_ROOT, "Output")
DEFAULT_WORKSPACE = os.path.dirname(PROJECT_ROOT)


def resources_folder(product):
    return os.path.join(RESOURCES_ROOT, product)


def output_folder(milestone, product, setup="", kind=None):
    """Output\\<milestone>\\<product>_<setup>[\\<kind>], not created here.

    kind is manifests, harness or secure_files."""
    parts = [OUTPUT_ROOT, milestone, f"{product}_{setup}" if setup else product]
    if kind:
        parts.append(kind)
    return os.path.join(*parts)


def export_file(path, milestone, product, setup, kind):
    """Copy a created file into the Output folder. Returns the copy, or None
    when the file does not exist or cannot be copied."""
    if not os.path.isfile(path):
        return None
    folder = output_folder(milestone, product, setup, kind)
    try:
        os.makedirs(folder, exist_ok=True)
        target = os.path.join(folder, os.path.basename(path))
        shutil.copy2(path, target)
    except OSError as error:
        print(f"Could not copy {os.path.basename(path)} to Output: {error}")
        return None
    return target


def milestone_folder(workspace, milestone, *parts):
    """<workspace>\\<milestone>\\utf_wifi\\<parts>."""
    return os.path.join(workspace, milestone, "utf_wifi", *parts)


def console_utf8():
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass


def parse_args(argv, default_product="NCP"):
    """Return (milestone, workspace, product, setup) from the script arguments.

    Missing values are empty strings, except the product which defaults to
    default_product and the workspace which defaults to the parent folder of
    this project. The milestone is asked for when it is not given.
    """
    def arg(index):
        return argv[index].strip() if len(argv) > index and argv[index].strip() else ""

    milestone = arg(1)
    if not milestone:
        milestone = input("\nEnter Current Milestone (Eg: M99): ").strip()
    workspace = arg(2) or DEFAULT_WORKSPACE
    product = arg(3) or default_product
    setup = arg(4)
    return milestone, workspace, product, setup


def list_files(folder):
    if not folder or not os.path.isdir(folder):
        return []
    return sorted(os.listdir(folder))


def find_file(files, include, exclude=()):
    """First name that has every word of include and none of exclude."""
    include = [word.lower() for word in include]
    exclude = [word.lower() for word in (exclude or ())]
    for name in files:
        lower = name.lower()
        if all(word in lower for word in include) and not any(word in lower for word in exclude):
            return name
    return None


def read_text(path):
    if not os.path.isfile(path):
        return None
    with open(path, "r", encoding="utf-8") as handle:
        return handle.read()


def write_text(path, text, newline=""):
    with open(path, "w", encoding="utf-8", newline=newline) as handle:
        handle.write(text)


def copy_resource_files(resources, manifest_folder):
    """Copy the .hex, .rps and .slcp files (and the SoC keys folder) beside
    the manifests. Returns the number of files copied."""
    copied = 0
    if os.path.isdir(resources):
        for name in os.listdir(resources):
            if name.lower().endswith((".hex", ".rps", ".slcp")):
                shutil.copy2(os.path.join(resources, name), os.path.join(manifest_folder, name))
                copied += 1
        keys = os.path.join(resources, "secure_firmware_keys")
        if os.path.isdir(keys):
            shutil.copytree(keys, os.path.join(manifest_folder, "secure_firmware_keys"), dirs_exist_ok=True)
            print("Copied keys folder : secure_firmware_keys")
    print(f"Copied Files : {copied}")
    return copied


def replace_marker_filename(text, marker, filename):
    """Set `filename:` under the `<marker>:` entry of a manifest."""
    lines = text.splitlines()
    inside_marker = False

    for index, line in enumerate(lines):
        stripped = line.strip()

        if stripped.startswith(f"{marker}:"):
            inside_marker = True
            continue

        if inside_marker:
            if (
                stripped.endswith(":")
                and not stripped.startswith("-")
                and "device_type" not in stripped
                and "device_subtype" not in stripped
                and "filename" not in stripped
            ):
                break

            if stripped.startswith("filename:"):
                indent = len(line) - len(line.lstrip())
                lines[index] = " " * indent + f"filename: '{filename}'"
                break

    return "\n".join(lines)
