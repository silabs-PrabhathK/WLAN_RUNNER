from . import ResetInterface
import subprocess


def create_interface(device, config):
    return ResetCommanderInterface(cli, config)


class ResetCommanderInterface(ResetInterface):
    def __init__(self, config):
        super().__init__(config)

    def reset(self):
        p = subprocess.run(["commander", "device", "reset"], capture_output=True)
        
        if "delay" in self.config:
            time.sleep(self.config["delay"])
