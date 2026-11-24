"""Create the NCP manifests inside a milestone.

Usage: python manifest_updater.py <milestone> <workspace> NCP

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
    copy_resource_files as copy_files,
    find_file,
    list_files,
    parse_args,
    replace_marker_filename,
    resources_folder,
)
from sanity_config import BUILD_CONFIG, MANIFEST_FILES

REGRESSION_ROOT = DEFAULT_WORKSPACE
RESOURCES_FOLDER = resources_folder("NCP")


def find_first_file(include_patterns, exclude_patterns=None):
    return find_file(list_files(RESOURCES_FOLDER), include_patterns, exclude_patterns)


def find_latest_rps():

    rps_files = [

        file_name

        for file_name in os.listdir(
            RESOURCES_FOLDER
        )

        if file_name.lower().endswith(
            ".rps"
        )
    ]

    if not rps_files:
        return None

    rps_files.sort(

        key=lambda file_name:
        os.path.getmtime(
            os.path.join(
                RESOURCES_FOLDER,
                file_name
            )
        ),

        reverse=True
    )

    return rps_files[0]


def replace_rs911x_firmware(
    text,
    firmware_file
):

    pattern = (
        r"rs911x:\s*&firmware_file_anchor\s*[^\n]+"
    )

    replacement = (
        f"rs911x: &firmware_file_anchor "
        f"'{firmware_file}'"
    )

    return re.sub(
        pattern,
        replacement,
        text,
        count=1
    )


def replace_efx32_firmware(
    text,
    aws_default
):

    pattern = (
        r"(efx32:\s*)'[^']*'"
    )

    return re.sub(
        pattern,
        rf"\g<1>'{aws_default}'",
        text,
        count=1
    )


def ensure_352k_section(
    text,
    aws_default
):

    if not aws_default:
        return text

    if "test_352K_M4SS_320K:" in text:

        return replace_marker_filename(
            text,
            "test_352K_M4SS_320K",
            aws_default
        )

    block = f"""

    test_352K_M4SS_320K:
      - device_type: 'efx32'
        device_subtype: 'efr32'
        filename: '{aws_default}'
"""

    return text.rstrip() + "\n" + block + "\n"

def update_manifest_text(
    manifest_text
):

    firmware_file = (BUILD_CONFIG.get("rps_filename", "").replace("\\", "/").split("/")[-1])

    aws_default = find_first_file(
        ["aws", "default"],
        ["4k"]
    )

    paho_default = find_first_file(
        ["paho", "mqtt", "default"]
    )

    aws_4k = find_first_file(
        ["aws", "default", "4k"]
    )

    azure = find_first_file(
        ["azure", "default"]
    )

    ipv6 = find_first_file(
        ["ipv6", "default"],
        ["dual", "stack"]
    )

    twt = find_first_file(
        ["twt", "default"]
    )

    lwip_stack = find_first_file(
        ["lwip", "default"]
    )

    lwip_default = find_first_file(
        ["lwip", "default"]
    )

    lwip_optimized = find_first_file(
        ["lwip", "optimized"]
    )

    dual_stack_ipv4 = find_first_file(
        ["dual", "stack", "default"],
        ["ipv6"]
    )

    dual_stack_ipv6 = find_first_file(
        ["dual", "stack", "ipv6", "default"]
    )

    if firmware_file:

        manifest_text = (
            replace_rs911x_firmware(
                manifest_text,
                firmware_file
            )
        )

        print(
            f"Firmware : {firmware_file}"
        )

    if aws_default:

        manifest_text = (
            replace_efx32_firmware(
                manifest_text,
                aws_default
            )
        )

        print(
            f"AWS Default : {aws_default}"
        )
        
        manifest_text = ensure_352k_section(manifest_text,aws_default)

    replacements = {

        "test_aws":
            aws_default,

        "test_aws_4k":
            aws_4k,

        "test_ipv6":
            ipv6,

        "test_twt_sta":
            twt,

        "test_azure":
            azure,

        "test_lwip_stack":
            lwip_stack,

        "test_lwip_default_timer":
            lwip_default,

        "test_lwip_optimized_timer":
            lwip_optimized,

        "test_dual_stack_ipv4":
            dual_stack_ipv4,

        "test_dual_stack_ipv6":
            dual_stack_ipv6
    }

    for marker, file_name in (
        replacements.items()
    ):

        if not file_name:
            continue

        manifest_text = (
            replace_marker_filename(
                manifest_text,
                marker,
                file_name
            )
        )

        print(
            f"Updated: "
            f"{marker}"
            f" -> "
            f"{file_name}"
        )

    return manifest_text


def create_without_firmware_manifest(source_manifest,target_manifest):
    with open(source_manifest,"r",encoding="utf-8") as file:
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
                indent = (len(line)- len(line.lstrip()))
                output.append(
                    " " * indent
                    + "# "
                    + stripped
                    + "\n"
                )
                continue
            if stripped.startswith("efx32:"):
                inside_firmware = False
                output.append(line)
                continue
        if stripped.startswith("firmware_version_file"):
            output.append("#" + stripped + "\n")
            continue
        output.append(line)
    with open(
        target_manifest,
        "w",
        encoding="utf-8",
        newline="\n"
    ) as file:
        file.writelines(output)
    print(
        f"Created : "
        f"{os.path.basename(target_manifest)}"
    )


def copy_resource_files(manifest_folder):
    copy_files(RESOURCES_FOLDER, manifest_folder)


def create_manifest(milestone):
    manifest_folder = os.path.join(
        REGRESSION_ROOT,
        milestone,
        "utf_wifi",
        "manifest"
    )
    standard_name = MANIFEST_FILES.get(
        "standard",
        "manifest_917_ncp.yaml"
    )
    manifest_file = os.path.join(
        manifest_folder,
        standard_name
    )
    if not os.path.exists(
        manifest_file
    ):
        print("\n❌ Manifest Not Found")
        print(manifest_file)
        return False
    with open(
        manifest_file,
        "r",
        encoding="utf-8"
    ) as file:
        manifest_text = file.read()
    manifest_text = update_manifest_text(
        manifest_text
    )
    with open(
        manifest_file,
        "w",
        encoding="utf-8",
        newline="\n"
    ) as file:
        file.write(
            manifest_text
        )
    paho_manifest = os.path.join(
        manifest_folder,
        MANIFEST_FILES["paho"]
    )
    create_paho_manifest(
        manifest_file,
        paho_manifest
    )
    
    without_name = MANIFEST_FILES.get(
        "without_firmware",
        "manifest_917_ncp_without_fw.yaml"
    )
    without_fw_manifest = os.path.join(
        manifest_folder,
        without_name
    )
    create_without_firmware_manifest(
        manifest_file,
        without_fw_manifest
    )
    alias_name = MANIFEST_FILES.get(
        "without_firmware_alias",
        ""
    )
    if alias_name and alias_name != without_name:
        alias_manifest = os.path.join(
            manifest_folder,
            alias_name
        )
        shutil.copy2(
            without_fw_manifest,
            alias_manifest
        )
        print(f"Alias : {alias_name}")
    copy_resource_files(manifest_folder)
    print(
        f"\n✅ Updated : "
        f"{os.path.basename(manifest_file)}"
    )
    print(
        f"✅ Created : "
        f"{os.path.basename(without_fw_manifest)}"
    )
    print("\n✅ Manifest Update Completed")
    return True

def create_paho_manifest(
    standard_manifest,
    paho_manifest
):

    with open(
        standard_manifest,
        "r",
        encoding="utf-8"
    ) as file:

        content = file.read()

    paho_file = find_first_file(
        ["paho", "mqtt", "default"]
    )

    if not paho_file:

        print("\nPaho firmware not found.")

        return

    lines = content.splitlines()

    for index, line in enumerate(lines):

        if line.strip().startswith("efx32:"):

            indent = line[:len(line) - len(line.lstrip())]

            lines[index] = (
                f"{indent}efx32: '{paho_file}'"
            )

            break

    with open(
        paho_manifest,
        "w",
        encoding="utf-8",
        newline="\n"
    ) as file:

        file.write(
            "\n".join(lines)
        )

    print(
        f"Created : "
        f"{os.path.basename(paho_manifest)}"
    )

def main():
    global REGRESSION_ROOT
    global RESOURCES_FOLDER

    console_utf8()
    milestone, workspace, product, _setup = parse_args(sys.argv)
    REGRESSION_ROOT = workspace
    RESOURCES_FOLDER = resources_folder(product)

    if not create_manifest(milestone):
        sys.exit(1)


if __name__ == "__main__":
    main()
