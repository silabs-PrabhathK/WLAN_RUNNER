from utf.interfaces.network import NetworkInterface
from utf.interfaces.shell.shell import Shell
import re


def create_interface(config, shell: Shell, interface: str):
    return WindowsNetworkInterface(config, shell, interface)


class WindowsNetworkInterface(NetworkInterface):
    def __init__(self, config, shell: Shell, interface: str):
        super().__init__(config)
        self.shell = shell
        self.interface_name = interface

    def get_ip_address(self):
        if self.interface_name is None:
            self.interface_name = self.config["interface"]
        rc, stdout, stderr = self.shell(
            f"netsh interface ip show config name=\"{self.interface_name}\"", wait_for="IP Address: [0-9.]+.*"
        )
        if rc != 0:
            raise RuntimeError(stderr)

        if isinstance(stdout, bytes):
            stdout = stdout.decode()
        m = re.search(r"IP Address:\s*([0-9.]+)", stdout)
        if m is not None:
            return m.group(1)
        else:
            self.logger.info(f"stdout: {stdout}")
            self.logger.info(f"stderr: {stderr}")
            raise RuntimeError("Unable to determine ip address")
