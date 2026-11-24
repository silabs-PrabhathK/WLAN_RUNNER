"""Create the SoC manifests of one setup inside a milestone.

Usage: python soc_manifest_updater.py <milestone> <workspace> SoC <setup>

NCP uses manifest_updater.py. This script is only for SoC: the firmware and
test agents are the secure_*_<id>.rps files made by soc_secure.py, and every
setup has its own manifests, built from the milestone's defaults:

  manifest_917_soc.yaml         -> manifest_917_soc_<setup>.yaml
                                   manifest_917_soc_<setup>_PAHO.yaml
                                   manifest_917_soc_<setup>_MEM2.yaml
  manifest_917_soc_secure.yaml  -> manifest_917_soc_secure_<setup>.yaml

The secure files come from Output\\<milestone>\\SoC_<setup>\\secure_files (made
by soc_secure.py). The .rps / .hex / .slcp files of that folder and of
Resources\\SoC are copied beside the manifests, and the finished manifests are
also copied to Output\\<milestone>\\SoC_<setup>\\manifests.
"""

import os
import re
import sys

from product_common import (
    DEFAULT_WORKSPACE,
    console_utf8,
    copy_resource_files,
    export_file,
    list_files,
    milestone_folder,
    output_folder,
    read_text,
    replace_marker_filename,
    resources_folder,
    write_text,
)
from sanity_config import (
    PRODUCT_DEFAULT_FILES,
    SOC_SECURE,
    file_stem,
    firmware_names,
    soc_manifest_names,
)

RESOURCES_FOLDER = resources_folder("SoC")
SECURE_FOLDER = None  # Output\<milestone>\SoC_<setup>\secure_files, set per setup

SOC_DEFAULT_MANIFEST = PRODUCT_DEFAULT_FILES["SoC"]["manifest"]
SOC_DEFAULT_SECURE_MANIFEST = PRODUCT_DEFAULT_FILES["SoC"]["secure_manifest"]

# NCP takes the "default" test agents. SoC takes the "mem_config_3" ones, so
# every lookup below needs that word (the MEM2 manifest is the one exception
# and uses mem_config_2). Names change from build to build, so a file is found
# by the words it must (not) contain, never by its full name.
CFG3 = "mem_config_3"

# AWS test agent: the 4k one, or any aws mem_config_3 agent when there is no 4k.
AWS_AGENT = [["aws", CFG3, "4k"], ["aws", CFG3]]

# marker(s) -> (include word lists tried in order, words that must be absent)
AGENT_MARKERS = [
    (("test_wlan_aws_enable", "test_wlan_rts", "test_352K_M4SS_320K"), AWS_AGENT, []),
    (("test_aws_4k",), [["aws", CFG3, "4k"]], []),
    (("test_twt_sta",), [["twt", CFG3]], []),
    (("test_ipv6",), [["ipv6", CFG3]], ["dual"]),
    (("test_azure",), [["azure", CFG3]], []),
    (("test_dual_stack_ipv4",), [["dual_stack", CFG3]], ["ipv6"]),
    (("test_dual_stack_ipv6",), [["dual_stack_ipv6", CFG3]], []),
    (("test_lwip_stack",), [["host_lwip_mqtt", CFG3]], []),
    (("test_lwip_default_timer",), [["lwip_mqtt_default", CFG3]], ["host"]),
    (("test_lwip_optimized_timer",), [["lwip_mqtt_optimized", CFG3]], ["host"]),
    (("test_lwip_default_timer_ipv6",), [["p_stack_lwip_opt_timer"]], []),
]

# PAHO and MEM2 manifests: only the test agent of the standard manifest changes.
VARIANTS = (
    ("PAHO", [["paho_mqtt", CFG3]]),
    ("MEM2", [["aws", "mem_config_2"]]),
)

FIRMWARE_ANCHOR = re.compile(r"(&firmware_file_anchor\s+)'[^']*'")
WRITE_FIRMWARE = re.compile(r"(write_firmware:\s*\n\s*file_name:\s*)'[^']*'")
SECURE_NAME = re.compile(r"secure_[\w.\-]+?\.rps")


def _modified(name):
    for folder in (SECURE_FOLDER, RESOURCES_FOLDER):
        if folder and os.path.isfile(os.path.join(folder, name)):
            return os.path.getmtime(os.path.join(folder, name))
    return 0


def newest_match(files, include, exclude=()):
    """Name that has every word of include and none of exclude.

    When several names fit (an old build is still in the folder), the newest
    file wins."""
    include = [word.lower() for word in include]
    exclude = [word.lower() for word in exclude]
    matches = [
        name for name in files
        if all(word in name.lower() for word in include)
        and not any(word in name.lower() for word in exclude)
    ]
    if not matches:
        return None
    return max(matches, key=lambda name: (_modified(name), name))


def pick_file(files, options, exclude=()):
    """First option (a list of words) that finds a file."""
    for include in options:
        found = newest_match(files, include, exclude)
        if found:
            return found
    return None


def secure_files(secure_id):
    suffix = f"_{secure_id}.rps".lower()
    return [
        name for name in list_files(SECURE_FOLDER)
        if name.lower().startswith("secure_") and name.lower().endswith(suffix)
    ]


def plain_files():
    return [
        name for name in list_files(RESOURCES_FOLDER)
        if name.lower().endswith(".rps") and not name.lower().startswith(("secure_", "encrypted_"))
    ]


def unmatched_markers(files):
    """First marker of every AGENT_MARKERS entry that has no test agent in files."""
    return [
        markers[0] for markers, options, exclude in AGENT_MARKERS
        if not pick_file(files, options, exclude)
    ]


def update_standard_text(text, secure_id, files):
    """Default manifest -> setup manifest. Returns (text, notes)."""
    notes = []
    latest = firmware_names("SoC")[0]
    if latest:
        secure_latest = f"secure_{file_stem(latest)}_{secure_id}.rps"
        text = FIRMWARE_ANCHOR.sub(rf"\g<1>'{secure_latest}'", text, count=1)
        notes.append(f"Firmware -> {secure_latest}")

    agent = pick_file(files, AWS_AGENT)
    if agent:
        text = WRITE_FIRMWARE.sub(rf"\g<1>'{agent}'", text, count=1)
        notes.append(f"Test agent -> {agent}")
    else:
        notes.append("WARNING test agent keeps the default (no secure aws mem_config_3 file)")

    for markers, options, exclude in AGENT_MARKERS:
        found = pick_file(files, options, exclude)
        for marker in markers:
            if f"{marker}:" not in text:
                continue
            if not found:
                wanted = "/".join(options[0])
                notes.append(f"WARNING {marker} keeps the default (no secure {wanted} file)")
                continue
            text = replace_marker_filename(text, marker, found)
            notes.append(f"{marker} -> {found}")
    if not text.endswith("\n"):
        text += "\n"
    return text, notes


def with_write_firmware(text, options, files):
    """Standard manifest with only the test agent swapped (PAHO, MEM2)."""
    found = pick_file(files, options)
    if not found:
        return None, None
    return WRITE_FIRMWARE.sub(rf"\g<1>'{found}'", text, count=1), found


def update_secure_text(text, secure_id):
    """Default secure manifest -> setup secure manifest. Returns (text, notes)."""
    notes = []
    latest = firmware_names("SoC")[0]
    agent = pick_file(plain_files(), AWS_AGENT)
    if latest:
        text = re.sub(r"(&secure_firmware_file_anchor\s+)\S+", rf"\g<1>encrypted_1_{latest}", text)
        text = re.sub(r"(&firmware_file_anchor\s+)\S+", rf"\g<1>{latest}", text)
        notes.append(f"Firmware -> {latest}")
    if agent:
        text = re.sub(r"(&secure_test_agent_file_anchor\s+)\S+", rf"\g<1>encrypted_1_{agent}", text)
        text = re.sub(r"(&test_agent_file_anchor\s+)\S+", rf"\g<1>{agent}", text)
        notes.append(f"Test agent -> {agent}")
    else:
        notes.append("WARNING test agent keeps the default (aws mem_config_3 file is not in Resources\\SoC)")
    text, count = re.subn(
        r"\b((?:m4_)?(?:ota_key|ta_private_key|m4_private_key))_1(\.(?:txt|pem))",
        rf"\g<1>_{secure_id}\g<2>",
        text,
    )
    notes.append(f"Key names -> id {secure_id} ({count} places)")
    if not text.endswith("\n"):
        text += "\n"
    return text, notes


def missing_references(text, manifest_folder):
    present = {
        name.lower()
        for folder in (SECURE_FOLDER, RESOURCES_FOLDER, manifest_folder)
        for name in list_files(folder)
    }
    return [name for name in sorted(set(SECURE_NAME.findall(text))) if name.lower() not in present]


def write_manifest(folder, name, text, notes, source):
    write_text(os.path.join(folder, name), text, newline="\n")
    print(f"Created : {name}  (from {source})")
    for note in notes:
        print(f"    {note}")
    for missing in missing_references(text, folder):
        print(f"    Missing file: {missing}")


def create_soc_manifests(workspace, milestone, setup):
    global SECURE_FOLDER
    secure_id = SOC_SECURE["setup_ids"].get(setup)
    if not secure_id:
        print(f"\n{setup} has no id in SOC_SECURE['setup_ids'].")
        return False
    SECURE_FOLDER = output_folder(milestone, "SoC", setup, "secure_files")
    folder = milestone_folder(workspace, milestone, "manifest")
    standard = read_text(os.path.join(folder, SOC_DEFAULT_MANIFEST))
    if standard is None:
        print(f"\nManifest Not Found: {os.path.join(folder, SOC_DEFAULT_MANIFEST)}")
        return False
    files = secure_files(secure_id)
    names = soc_manifest_names(setup)
    print(f"\nProcessing Setup : {setup} (id {secure_id}), {len(files)} secure files")

    created = []
    text, notes = update_standard_text(standard, secure_id, files)
    write_manifest(folder, names[0], text, notes, SOC_DEFAULT_MANIFEST)
    created.append(names[0])

    for name, (label, options) in zip(names[1:3], VARIANTS):
        variant, found = with_write_firmware(text, options, files)
        if variant is None:
            print(f"Skipped : {name} (no secure {label} test agent for id {secure_id})")
            continue
        write_manifest(folder, name, variant, [f"Test agent -> {found}"], names[0])
        created.append(name)

    secure_default = read_text(os.path.join(folder, SOC_DEFAULT_SECURE_MANIFEST))
    if secure_default is None:
        print(f"Skipped : {names[3]} ({SOC_DEFAULT_SECURE_MANIFEST} is not in the milestone)")
    else:
        secure_text, secure_notes = update_secure_text(secure_default, secure_id)
        write_manifest(folder, names[3], secure_text, secure_notes, SOC_DEFAULT_SECURE_MANIFEST)
        created.append(names[3])

    copy_resource_files(RESOURCES_FOLDER, folder)
    copy_resource_files(SECURE_FOLDER, folder)
    for name in created:
        export_file(os.path.join(folder, name), milestone, "SoC", setup, "manifests")
    print(f"\nManifests updated: {', '.join(created)}")
    print(f"Copies in : {output_folder(milestone, 'SoC', setup, 'manifests')}")
    return True


def main():
    console_utf8()
    if len(sys.argv) < 5:
        print("Usage: python soc_manifest_updater.py <milestone> <workspace> SoC <setup>")
        sys.exit(1)
    milestone = sys.argv[1].strip()
    workspace = sys.argv[2].strip() or DEFAULT_WORKSPACE
    setup = sys.argv[4].strip()
    if not create_soc_manifests(workspace, milestone, setup):
        sys.exit(1)
    print("\nSoC manifest update completed.")


if __name__ == "__main__":
    main()
