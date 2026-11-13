import os
import re
import shutil
import sys

from sanity_config import (MANIFEST_FILES, BUILD_CONFIG)

PROJECT_ROOT = os.path.dirname(
    os.path.abspath(__file__)
)

REGRESSION_ROOT = os.path.dirname(
    PROJECT_ROOT
)

RESOURCES_FOLDER = os.path.join(
    PROJECT_ROOT,
    "Resources"
)


def find_first_file(
    include_patterns,
    exclude_patterns=None
):

    exclude_patterns = exclude_patterns or []

    files = sorted(
        os.listdir(
            RESOURCES_FOLDER
        )
    )

    for file_name in files:

        lower = file_name.lower()

        if not all(
            pattern.lower() in lower
            for pattern in include_patterns
        ):
            continue

        if any(
            pattern.lower() in lower
            for pattern in exclude_patterns
        ):
            continue

        return file_name

    return None


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


def replace_marker_filename(
    text,
    marker,
    filename
):

    lines = text.splitlines()

    inside_marker = False

    for index, line in enumerate(lines):

        stripped = line.strip()

        if stripped.startswith(
            f"{marker}:"
        ):

            inside_marker = True
            continue

        if inside_marker:

            if (
                stripped.endswith(":")
                and
                not stripped.startswith("-")
                and
                "device_type" not in stripped
                and
                "device_subtype" not in stripped
                and
                "filename" not in stripped
            ):
                break

            if stripped.startswith(
                "filename:"
            ):

                indent = (
                    len(line)
                    - len(line.lstrip())
                )

                lines[index] = (
                    " " * indent
                    + f"filename: '{filename}'"
                )

                break

    return "\n".join(lines)

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


def copy_resource_files(
    manifest_folder
):

    copied = 0

    for file_name in os.listdir(
        RESOURCES_FOLDER
    ):

        if file_name.lower().endswith(
            (
                ".hex",
                ".rps",
                ".slcp"
            )
        ):

            shutil.copy2(

                os.path.join(
                    RESOURCES_FOLDER,
                    file_name
                ),

                os.path.join(
                    manifest_folder,
                    file_name
                )
            )

            copied += 1

    print(
        f"Copied Files : {copied}"
    )


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
        return
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

    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

    if len(sys.argv) > 1:
        milestone = sys.argv[1].strip()
    else:
        milestone = input(
            "\nEnter Current Milestone (Eg: M99): "
        ).strip()

    if len(sys.argv) > 2 and sys.argv[2].strip():
        REGRESSION_ROOT = sys.argv[2].strip()

    product = "NCP"

    if len(sys.argv) > 3 and sys.argv[3].strip():
        product = sys.argv[3].strip()

    RESOURCES_FOLDER = os.path.join(
        PROJECT_ROOT,
        "Resources",
        product
    )

    create_manifest(milestone)


if __name__ == "__main__":
    main()