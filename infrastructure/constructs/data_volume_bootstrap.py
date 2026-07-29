"""Bootstrap the retained data EBS mount without relying on its attachment name."""

from __future__ import annotations

from pathlib import Path

from aws_cdk import Fn
from constructs import Construct

from infrastructure.constructs.java_runtime import resolve_java_package
from infrastructure.constructs.minecraft_data_volume import MinecraftDataVolume
from infrastructure.constructs.minecraft_instance import MinecraftInstance
from wishicraft.config import StageConfig

_SCRIPT_PATH = Path(__file__).parents[1] / "bootstrap" / "data_volume_mount.sh"
_JAVA_SCRIPT_PATH = Path(__file__).parents[1] / "bootstrap" / "java_runtime_install.sh"


class DataVolumeBootstrap(Construct):
    """Install and start the fail-closed data volume preparation service."""

    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        *,
        instance: MinecraftInstance,
        data_volume: MinecraftDataVolume,
        stage: StageConfig,
    ) -> None:
        super().__init__(scope, construct_id)
        self.java_package = resolve_java_package(stage.java_runtime)
        if stage.data_volume_filesystem_type != "xfs":
            raise ValueError(
                f"Unsupported Phase 1 data filesystem type: {stage.data_volume_filesystem_type}"
            )

        instance.instance.add_property_override(
            "UserData",
            Fn.base64(
                Fn.join(
                    "",
                    [
                        "#!/bin/bash\nset -eu\n"
                        "install -d -m 0755 /usr/local/lib/wishicraft /etc/wishicraft\n",
                        "cat > /usr/local/lib/wishicraft/data-volume-mount "
                        "<<'WISHICRAFT_DATA_VOLUME_SCRIPT'\n",
                        _SCRIPT_PATH.read_text(encoding="utf-8"),
                        "WISHICRAFT_DATA_VOLUME_SCRIPT\n"
                        "chmod 0755 /usr/local/lib/wishicraft/data-volume-mount\n",
                        "cat > /usr/local/lib/wishicraft/java-runtime-install "
                        "<<'WISHICRAFT_JAVA_RUNTIME_SCRIPT'\n",
                        _JAVA_SCRIPT_PATH.read_text(encoding="utf-8"),
                        "WISHICRAFT_JAVA_RUNTIME_SCRIPT\n"
                        "chmod 0755 /usr/local/lib/wishicraft/java-runtime-install\n",
                        "cat > /etc/wishicraft/data-volume.env "
                        "<<'WISHICRAFT_DATA_VOLUME_ENV'\nDATA_VOLUME_ID=",
                        data_volume.volume.ref,
                        "\nMOUNT_PATH=",
                        stage.data_volume_mount_path,
                        "\nFILESYSTEM_TYPE=",
                        stage.data_volume_filesystem_type,
                        "\nWISHICRAFT_DATA_VOLUME_ENV\n",
                        "cat > /etc/systemd/system/wishicraft-data-volume.service "
                        "<<'WISHICRAFT_DATA_VOLUME_UNIT'\n",
                        "[Unit]\nDescription=Wishicraft data EBS preparation\n"
                        "Wants=network-online.target\nAfter=network-online.target\n"
                        "Before=minecraft.service\n\n",
                        "[Service]\nType=oneshot\n"
                        "EnvironmentFile=/etc/wishicraft/data-volume.env\n"
                        "ExecStart=/usr/local/lib/wishicraft/data-volume-mount\n"
                        "ExecStart=/usr/local/lib/wishicraft/data-volume-mount --verify\n"
                        "RemainAfterExit=yes\n\n",
                        "[Install]\nWantedBy=multi-user.target\nWISHICRAFT_DATA_VOLUME_UNIT\n",
                        "systemctl daemon-reload\n"
                        "systemctl enable --now wishicraft-data-volume.service\n"
                        "JAVA_RUNTIME=",
                        stage.java_runtime,
                        " /usr/local/lib/wishicraft/java-runtime-install\n",
                    ],
                )
            ),
        )
