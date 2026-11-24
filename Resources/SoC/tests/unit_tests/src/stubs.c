#include <stddef.h>
#include <stdint.h>
#include <stdbool.h>
#include "cmsis_os2.h"
#include "sl_si91x_types.h"

bool device_initialized                                           = false;
bool bg_enabled                                                   = false;
sl_wifi_advanced_scan_configuration_t advanced_scan_configuration = { 0 };
