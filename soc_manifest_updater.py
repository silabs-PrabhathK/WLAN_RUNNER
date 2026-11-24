"""Create the SoC manifests of one setup inside a milestone.

Usage: python soc_manifest_updater.py <milestone> <workspace> SoC <setup>

NCP uses manifest_updater.py. SoC differs: the firmware and test agents are
the secure_*_<id>.rps files made by soc_secure.py, and every setup has its
own manifests. They are built from the milestone's own defaults:

  manifest_917_soc.yaml         -> manifest_917_soc_<setup>.yaml
                                   manifest_917_soc_<setup>_PAHO.yaml
                                   manifest_917_soc_<setup>_MEM2.yaml
  manifest_917_soc_secure.yaml  -> manifest_917_soc_secure_<setup>.yaml

The firmware files are copied beside the manifests.
"""

import os
import re
import sys

from product_common import (
    DEFAULT_WORKSPACE,
    console_utf8,
    copy_resource_files as copy_files,
    find_file,
    list_files,
    milestone_folder,
    parse_args,
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

REGRESSION_ROOT = DEFAULT_WORKSPACE
RESOURCES_FOLDER = resources_folder("SoC")

SOC_DEFAULT_MANIFEST = PRODUCT_DEFAULT_FILES["SoC"]["manifest"]
SOC_DEFAULT_SECURE_MANIFEST = PRODUCT_DEFAULT_FILES["SoC"]["secure_manifest"]

# marker(s) -> words the secure file name must (not) contain
AGENT_MARKERS = [
    (("test_wlan_aws_enable", "test_wlan_rts", "test_352K_M4SS_320K"),
     ["aws", "mem_config_3"], ["4k"]),
    (("test_aws_4k",), ["aws", "4k"], []),
    (("test_twt_sta",), ["twt"], []),
    (("test_ipv6",), ["ipv6_mem"], []),
    (("test_azure",), ["azure"], []),
    (("test_lwip_stack", "test_lwip_default_timer"), ["lwip_mqtt_default"], []),
    (("test_lwip_optimized_timer",), ["lwip_mqtt_optimized"], []),
    (("test_lwip_default_timer_ipv6",), ["p_stack_lwip_opt_timer"], []),
]

FIRMWARE_ANCHOR = re.compile(r"(&firmware_file_anchor\s+)'[^']*'")
WRITE_FIRMWARE = re.compile(r"(write_firmware:\s*\n\s*file_name:\s*)'[^']*'")
SECURE_NAME = re.compile(r"secure_[\w.\-]+?\.rps")


def secure_files(secure_id):
    suffix = f"_{secure_id}.rps".lower()
    return [
        name for name in list_files(RESOURCES_FOLDER)
        if name.lower().startswith("secure_") and name.lower().endswith(suffix)
    ]


def plain_files():
    return [
        name for name in list_files(RESOURCES_FOLDER)
        if name.lower().endswith(".rps") and not name.lower().startswith(("secure_", "encrypted_"))
    ]


def update_standard_text(text, secure_id, files):
    """Default manifest -> setup manifest. Returns (text, notes)."""
    notes = []
    latest = firmware_names("SoC")[0]
    if latest:
        secure_latest = f"secure_{file_stem(latest)}_{secure_id}.rps"
        text = FIRMWARE_ANCHOR.sub(rf"\g<1>'{secure_latest}'", text, count=1)
        notes.append(f"Firmware -> {secure_latest}")

    agent = find_file(files, ["aws", "mem_config_3"], ["4k"])
    if agent:
        text = WRITE_FIRMWARE.sub(rf"\g<1>'{agent}'", text, count=1)
        notes.append(f"Test agent -> {agent}")
    else:
        notes.append("Test agent kept (no secure aws mem_config_3 file)")

    for markers, include, exclude in AGENT_MARKERS:
        found = find_file(files, include, exclude)
        for marker in markers:
            if f"{marker}:" not in text:
                continue
            if not found:
                notes.append(f"{marker} kept (no matching secure file)")
                continue
            text = replace_marker_filename(text, marker, found)
            notes.append(f"{marker} -> {found}")
    if not text.endswith("\n"):
        text += "\n"
    return text, notes


def with_write_firmware(text, include, exclude, files):
    """Standard manifest with only the test agent swapped (PAHO, MEM2)."""
    found = find_file(files, include, exclude)
    if not found:
        return None, None
    return WRITE_FIRMWARE.sub(rf"\g<1>'{found}'", text, count=1), found


def update_secure_text(text, secure_id):
    """Default secure manifest -> setup secure manifest. Returns (text, notes)."""
    notes = []
    latest = firmware_names("SoC")[0]
    agent = find_file(plain_files(), ["aws", "mem_config_3"], ["4k"])
    if latest:
        text = re.sub(r"(&secure_firmware_file_anchor\s+)\S+", rf"\g<1>encrypted_1_{latest}", text)
        text = re.sub(r"(&firmware_file_anchor\s+)\S+", rf"\g<1>{latest}", text)
        notes.append(f"Firmware -> {latest}")
    if agent:
        text = re.sub(r"(&secure_test_agent_file_anchor\s+)\S+", rf"\g<1>encrypted_1_{agent}", text)
        text = re.sub(r"(&test_agent_file_anchor\s+)\S+", rf"\g<1>{agent}", text)
        notes.append(f"Test agent -> {agent}")
    else:
        notes.append("Test agent kept (aws mem_config_3 file is not in Resources\\SoC)")
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
    present = {name.lower() for folder in (RESOURCES_FOLDER, manifest_folder) for name in list_files(folder)}
    return [name for name in sorted(set(SECURE_NAME.findall(text))) if name.lower() not in present]


def write_manifest(folder, name, text, notes, source):
    write_text(os.path.join(folder, name), text, newline="\n")
    print(f"Created : {name}  (from {source})")
    for note in notes:
        print(f"    {note}")
    for missing in missing_references(text, folder):
        print(f"    Missing file: {missing}")


def create_soc_manifests(milestone, setup):
    secure_id = SOC_SECURE["setup_ids"].get(setup)
    if not secure_id:
        print(f"\n{setup} has no id in SOC_SECURE['setup_ids'].")
        return False
    folder = milestone_folder(REGRESSION_ROOT, milestone, "manifest")
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

    variants = (
        (names[1], ["paho_mqtt"], [], "PAHO"),
        (names[2], ["aws", "mem_config_2"], [], "MEM2"),
    )
    for name, include, exclude, label in variants:
        variant, found = with_write_firmware(text, include, exclude, files)
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

    copy_files(RESOURCES_FOLDER, folder)
    print(f"\nManifests updated: {', '.join(created)}")
    return True


def main():
    global REGRESSION_ROOT
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    if len(sys.argv) < 5:
        print("Usage: python soc_manifest_updater.py <milestone> <workspace> SoC <setup>")
        sys.exit(1)
    milestone = sys.argv[1].strip()
    if sys.argv[2].strip():
        REGRESSION_ROOT = sys.argv[2].strip()
    setup = sys.argv[4].strip()
    if not create_soc_manifests(milestone, setup):
        sys.exit(1)
    print("\nSoC manifest update completed.")


if __name__ == "__main__":
    main()
