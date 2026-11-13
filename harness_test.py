import os
import yaml

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


def load_yaml(file_path):

    with open(
        file_path,
        "r",
        encoding="utf-8"
    ) as file:

        return yaml.safe_load(file)


def find_previous_milestone(
    current_milestone
):

    current_num = int(
        "".join(
            filter(
                str.isdigit,
                current_milestone
            )
        )
    )

    return f"M{current_num - 1}"


def get_harness_paths(
    current_milestone
):

    previous_milestone = (
        find_previous_milestone(
            current_milestone
        )
    )

    current_harness_folder = os.path.join(
        REGRESSION_ROOT,
        current_milestone,
        "utf_wifi",
        "config",
        "harnesses"
    )

    previous_harness_folder = os.path.join(
        REGRESSION_ROOT,
        previous_milestone,
        "utf_wifi",
        "config",
        "harnesses"
    )

    return {
        "current": current_harness_folder,
        "previous": previous_harness_folder
    }


def flatten_yaml(
    data,
    parent_key=""
):

    items = {}

    if isinstance(data, dict):

        for key, value in data.items():

            new_key = (
                f"{parent_key}.{key}"
                if parent_key
                else key
            )

            items.update(
                flatten_yaml(
                    value,
                    new_key
                )
            )

    elif isinstance(data, list):

        items[parent_key] = data

    else:

        items[parent_key] = data

    return items


def compare_harnesses(
    default_harness,
    source_harness
):

    ALLOWED_KEYS = [

        "devices.asus_rt_ax3000_ap",

        "devices.airpcap",

        "devices.raspi_wifi_ssh",

        "devices.switched_ap",

        "devices.switched_ap1",

        "devices.switched_ap2",

        "devices.raspi_radius_server",

        "devices.raspi_radius_server_v2",

        "devices.static_radius_server",

        "defaults.iop_sockets",

        "defaults.iot_sockets",

        "defaults.wifi.http_url",

        "constants.rejoin_time"
    ]

    def is_allowed_key(path):

        for allowed_key in ALLOWED_KEYS:

            if path.startswith(
                allowed_key
            ):
                return True

        return False

    default_yaml = flatten_yaml(
        load_yaml(default_harness)
    )

    source_yaml = flatten_yaml(
        load_yaml(source_harness)
    )

    changed = {}

    added_in_default = []

    missing_in_default = {}

    ignored_changes = {}

    for key, value in source_yaml.items():

        if key not in default_yaml:

            missing_in_default[key] = value

            continue

        if default_yaml[key] != value:

            if not is_allowed_key(key):

                ignored_changes[key] = {
                    "old": default_yaml[key],
                    "new": value
                }

                continue

            changed[key] = {
                "old": default_yaml[key],
                "new": value
            }

    for key in default_yaml:

        if key not in source_yaml:

            added_in_default.append(
                key
            )

    return (
        changed,
        added_in_default,
        missing_in_default,
        ignored_changes
    )


def run_test():

    current_milestone = input(
        "\nEnter Current Milestone (Example: M99): "
    ).strip()

    paths = get_harness_paths(
        current_milestone
    )

    current_harness_folder = (
        paths["current"]
    )

    previous_harness_folder = (
        paths["previous"]
    )

    default_harness = os.path.join(
        current_harness_folder,
        "harness_example_ncp_si917_sdk.yaml"
    )

    setups = [
        "23A",
        "23B"
    ]

    for setup in setups:

        print(
            "\n================================================"
        )

        print(
            f"SETUP : {setup}"
        )

        print(
            "================================================"
        )

        previous_harness = os.path.join(
            previous_harness_folder,
            f"harness_example_ncp_si917_sdk_{setup}.yaml"
        )

        if not os.path.exists(
            previous_harness
        ):

            print(
                f"\nPrevious harness not found for {setup}"
            )

            print(
                "Using Resource Harness"
            )

            previous_harness = os.path.join(
                RESOURCES_FOLDER,
                f"harness_example_ncp_si917_sdk_{setup}.yaml"
            )

        if not os.path.exists(
            previous_harness
        ):

            print(
                "\n❌ Resource Harness Missing"
            )

            continue

        (
            changes,
            new_keys,
            missing_keys,
            ignored_changes

        ) = compare_harnesses(

            default_harness,

            previous_harness
        )

        print(
            f"\nChanged Keys Count : {len(changes)}"
        )

        print(
            f"Ignored Keys Count : {len(ignored_changes)}"
        )

        print(
            "\nChanged Keys:"
        )

        if changes:

            for key in sorted(
                changes.keys()
            ):

                value = changes[key]

                print(
                    f"\n{key}"
                )

                print(
                    f"Default : {value['old']}"
                )

                print(
                    f"Previous: {value['new']}"
                )

        else:

            print(
                "No changes found."
            )

        print(
            f"\nNew Keys In Default Harness : {len(new_keys)}"
        )

        if new_keys:

            for key in sorted(
                new_keys
            ):

                print(key)

        else:

            print(
                "No new keys."
            )

        print(
            f"\nKeys Present In Previous Harness But Missing In Default : "
            f"{len(missing_keys)}"
        )

        if missing_keys:

            for key in sorted(
                missing_keys.keys()
            ):

                print(
                    f"MISSING -> {key}"
                )

        else:

            print(
                "No missing keys."
            )

        print(
            "\n================================================"
        )

        print(
            "\nSUMMARY"
        )

        print(
            f"\nSetup : {setup}"
        )

        print(
            f"Changed Keys     : {len(changes)}"
        )

        print(
            f"New M99 Keys     : {len(new_keys)}"
        )

        print(
            f"Missing M98 Keys : {len(missing_keys)}"
        )

        print(
            f"Ignored Keys     : {len(ignored_changes)}"
        )


if __name__ == "__main__":

    run_test()