"""Create the NCP manifests inside a milestone.

Usage: python manifest_updater.py <milestone> <workspace> NCP

The default manifest of the milestone gets the firmware and the "default" test
agents of Resources\\NCP. Three files are written:

  manifest_917_ncp.yaml              the default manifest, updated
  manifest_917_ncp_paho.yaml         the same with the paho test agent
  manifest_917_ncp_without_fw.yaml   the same without the firmware lines

Copies of the manifests are also put in Output\\<milestone>\\NCP_<setup>\\manifests.

SoC builds its manifests with soc_manifest_updater.py. Paths, file lookups,
file copying and the marker edit are shared in product_common.py.
"""

import os
import re
import shutil
import sys

from product_common import (
    DEFAULT_WORKSPACE,
    console_utf8,
    copy_resource_files,
    export_file,
    find_file,
    list_files,
    milestone_folder,
    output_folder,
    parse_args,
    read_text,
    replace_marker_filename,
    resources_folder,
    write_text,
)
from sanity_config import BUILD_CONFIG, MANIFEST_FILES

REGRESSION_ROOT = DEFAULT_WORKSPACE
RESOURCES_FOLDER = resources_folder("NCP")
SETUP = ""  # only names the Output folder; the NCP manifests are the same for every setup


def find_first_file(include_patterns, exclude_patterns=None):
    return find_file(list_files(RESOURCES_FOLDER), include_patterns, exclude_patterns)


def replace_rs911x_firmware(text, firmware_file):
    return re.sub(
        r"rs911x:\s*&firmware_file_anchor\s*[^\n]+",
        f"rs911x: &firmware_file_anchor '{firmware_file}'",
        text,
        count=1,
    )


def replace_efx32_firmware(text, aws_default):
    return re.sub(r"(efx32:\s*)'[^']*'", rf"\g<1>'{aws_default}'", text, count=1)


def ensure_352k_section(text, aws_default):
    if not aws_default:
        return text
    if "test_352K_M4SS_320K:" in text:
        return replace_marker_filename(text, "test_352K_M4SS_320K", aws_default)
    block = f"""

    test_352K_M4SS_320K:
      - device_type: 'efx32'
        device_subtype: 'efr32'
        filename: '{aws_default}'
"""
    return text.rstrip() + "\n" + block + "\n"


def update_manifest_text(manifest_text):
    firmware_file = BUILD_CONFIG.get("rps_filename", "").replace("\\", "/").split("/")[-1]

    aws_default = find_first_file(["aws", "default"], ["4k"])
    lwip_default = find_first_file(["lwip", "default"])

    if firmware_file:
        manifest_text = replace_rs911x_firmware(manifest_text, firmware_file)
        print(f"Firmware : {firmware_file}")

    if aws_default:
        manifest_text = replace_efx32_firmware(manifest_text, aws_default)
        print(f"AWS Default : {aws_default}")
        manifest_text = ensure_352k_section(manifest_text, aws_default)

    # marker in the manifest -> test agent found in Resources\NCP
    replacements = {
        "test_aws": aws_default,
        "test_aws_4k": find_first_file(["aws", "default", "4k"]),
        "test_ipv6": find_first_file(["ipv6", "default"], ["dual", "stack"]),
        "test_twt_sta": find_first_file(["twt", "default"]),
        "test_azure": find_first_file(["azure", "default"]),
        "test_lwip_stack": lwip_default,
        "test_lwip_default_timer": lwip_default,
        "test_lwip_optimized_timer": find_first_file(["lwip", "optimized"]),
        "test_dual_stack_ipv4": find_first_file(["dual", "stack", "default"], ["ipv6"]),
        "test_dual_stack_ipv6": find_first_file(["dual", "stack", "ipv6", "default"]),
    }
    for marker, file_name in replacements.items():
        if not file_name:
            continue
        manifest_text = replace_marker_filename(manifest_text, marker, file_name)
        print(f"Updated: {marker} -> {file_name}")
    return manifest_text


def create_without_firmware_manifest(source_manifest, target_manifest):
    with open(source_manifest, "r", encoding="utf-8") as file:
        lines = file.readlines()
    output = []
    inside_firmware = False
    for line in lines:
        stripped = line.strip()
        if stripped == "firmware:":
            inside_firmware = True
            output.append(line)
            continue
        if inside_firmware:
            if stripped.startswith("rs911x:"):
                indent = len(line) - len(line.lstrip())
                output.append(" " * indent + "# " + stripped + "\n")
                continue
            if stripped.startswith("efx32:"):
                inside_firmware = False
                output.append(line)
                continue
        if stripped.startswith("firmware_version_file"):
            output.append("#" + stripped + "\n")
            continue
        output.append(line)
    with open(target_manifest, "w", encoding="utf-8", newline="\n") as file:
        file.writelines(output)
    print(f"Created : {os.path.basename(target_manifest)}")


def create_paho_manifest(standard_manifest, paho_manifest):
    content = read_text(standard_manifest)
    paho_file = find_first_file(["paho", "mqtt", "default"])
    if not paho_file:
        print("\nPaho firmware not found.")
        return
    lines = content.splitlines()
    for index, line in enumerate(lines):
        if line.strip().startswith("efx32:"):
            indent = line[: len(line) - len(line.lstrip())]
            lines[index] = f"{indent}efx32: '{paho_file}'"
            break
    write_text(paho_manifest, "\n".join(lines), newline="\n")
    print(f"Created : {os.path.basename(paho_manifest)}")


def create_manifest(milestone):
    manifest_folder = milestone_folder(REGRESSION_ROOT, milestone, "manifest")
    standard_name = MANIFEST_FILES.get("standard", "manifest_917_ncp.yaml")
    manifest_file = os.path.join(manifest_folder, standard_name)
    manifest_text = read_text(manifest_file)
    if manifest_text is None:
        print("\n❌ Manifest Not Found")
        print(manifest_file)
        return False

    write_text(manifest_file, update_manifest_text(manifest_text), newline="\n")
    create_paho_manifest(manifest_file, os.path.join(manifest_folder, MANIFEST_FILES["paho"]))

    without_name = MANIFEST_FILES.get("without_firmware", "manifest_917_ncp_without_fw.yaml")
    without_fw_manifest = os.path.join(manifest_folder, without_name)
    create_without_firmware_manifest(manifest_file, without_fw_manifest)
    alias_name = MANIFEST_FILES.get("without_firmware_alias", "")
    if alias_name and alias_name != without_name:
        shutil.copy2(without_fw_manifest, os.path.join(manifest_folder, alias_name))
        print(f"Alias : {alias_name}")

    copy_resource_files(RESOURCES_FOLDER, manifest_folder)
    for name in (standard_name, MANIFEST_FILES["paho"], without_name, alias_name):
        if name:
            export_file(os.path.join(manifest_folder, name), milestone, "NCP", SETUP, "manifests")
    print(f"Copies in : {output_folder(milestone, 'NCP', SETUP, 'manifests')}")
    print(f"\n✅ Updated : {os.path.basename(manifest_file)}")
    print(f"✅ Created : {os.path.basename(without_fw_manifest)}")
    print("\n✅ Manifest Update Completed")
    return True


def main():
    global REGRESSION_ROOT
    global RESOURCES_FOLDER
    global SETUP

    console_utf8()
    milestone, workspace, product, setup = parse_args(sys.argv)
    REGRESSION_ROOT = workspace
    RESOURCES_FOLDER = resources_folder(product)
    SETUP = setup

    if not create_manifest(milestone):
        sys.exit(1)


if __name__ == "__main__":
    main()
