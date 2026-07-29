"""Bootstrap the retained data EBS mount without relying on its attachment name."""

from __future__ import annotations

from pathlib import Path

from aws_cdk import Fn
from constructs import Construct

from infrastructure.constructs.java_runtime import resolve_java_package
from infrastructure.constructs.minecraft_artifact import resolve_minecraft_artifact
from infrastructure.constructs.minecraft_data_volume import MinecraftDataVolume
from infrastructure.constructs.minecraft_instance import MinecraftInstance
from wishicraft.config import ProjectConfig, StageConfig

_SCRIPT_PATH = Path(__file__).parents[1] / "bootstrap" / "data_volume_mount.sh"
_JAVA_SCRIPT_PATH = Path(__file__).parents[1] / "bootstrap" / "java_runtime_install.sh"
_ARTIFACT_SCRIPT_PATH = Path(__file__).parents[1] / "bootstrap" / "minecraft_artifact_install.sh"
_GAME_SCRIPT_PATH = Path(__file__).parents[1] / "bootstrap" / "minecraft_game_setup.sh"


class DataVolumeBootstrap(Construct):
    """Install and start the fail-closed data volume preparation service."""

    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        *,
        instance: MinecraftInstance,
        data_volume: MinecraftDataVolume,
        project: ProjectConfig,
        stage: StageConfig,
    ) -> None:
        super().__init__(scope, construct_id)
        self.java_package = resolve_java_package(stage.java_runtime)
        self.artifact = resolve_minecraft_artifact(stage)
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
                        "cat > /usr/local/lib/wishicraft/minecraft-artifact-install "
                        "<<'WISHICRAFT_ARTIFACT_SCRIPT'\n",
                        _ARTIFACT_SCRIPT_PATH.read_text(encoding="utf-8"),
                        "WISHICRAFT_ARTIFACT_SCRIPT\n"
                        "chmod 0755 /usr/local/lib/wishicraft/minecraft-artifact-install\n",
                        "cat > /usr/local/lib/wishicraft/minecraft-game-setup "
                        "<<'WISHICRAFT_GAME_SCRIPT'\n",
                        _GAME_SCRIPT_PATH.read_text(encoding="utf-8"),
                        "WISHICRAFT_GAME_SCRIPT\n"
                        "chmod 0755 /usr/local/lib/wishicraft/minecraft-game-setup\n",
                        "cat > /etc/wishicraft/data-volume.env "
                        "<<'WISHICRAFT_DATA_VOLUME_ENV'\nDATA_VOLUME_ID=",
                        data_volume.volume.ref,
                        "\nMOUNT_PATH=",
                        stage.data_volume_mount_path,
                        "\nFILESYSTEM_TYPE=",
                        stage.data_volume_filesystem_type,
                        "\nWISHICRAFT_DATA_VOLUME_ENV\n",
                        "cat > /etc/wishicraft/minecraft.env "
                        "<<'WISHICRAFT_MINECRAFT_ENV'\n"
                        "MOUNT_GUARD=/usr/local/lib/wishicraft/data-volume-mount\n"
                        "MOUNT_PATH=",
                        stage.data_volume_mount_path,
                        "\nGAME_ID=",
                        project.initial_game_id,
                        "\nGAME_DIRECTORY=",
                        stage.data_volume_mount_path,
                        "/games/",
                        project.initial_game_id,
                        "\nARTIFACT_URL=",
                        self.artifact.url,
                        "\nARTIFACT_SHA1=",
                        self.artifact.sha1,
                        "\nARTIFACT_SHA256=",
                        self.artifact.sha256,
                        "\nARTIFACT_SIZE=",
                        str(self.artifact.size),
                        "\nARTIFACT_PATH=",
                        stage.data_volume_mount_path,
                        "/packages/vanilla/",
                        self.artifact.version,
                        "/server.jar\nMINECRAFT_PORT=",
                        str(stage.minecraft_port),
                        "\nPROFILE_NAME=",
                        project.initial_minecraft_profile_name,
                        "\nPROFILE_UUID=",
                        project.initial_minecraft_profile_uuid,
                        "\nWISHICRAFT_MINECRAFT_ENV\n",
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
                        " /usr/local/lib/wishicraft/java-runtime-install\n"
                        "set -a\n. /etc/wishicraft/minecraft.env\nset +a\n"
                        "/usr/local/lib/wishicraft/minecraft-game-setup --prepare\n"
                        "/usr/local/lib/wishicraft/minecraft-artifact-install\n"
                        "/usr/local/lib/wishicraft/minecraft-game-setup\n",
                        "cat > /etc/systemd/system/minecraft.service "
                        "<<'WISHICRAFT_MINECRAFT_UNIT'\n",
                        "[Unit]\nDescription=Wishicraft Minecraft server\n"
                        "Requires=wishicraft-data-volume.service\n"
                        "After=wishicraft-data-volume.service\n\n"
                        "[Service]\nType=simple\nUser=minecraft\nGroup=minecraft\n"
                        "EnvironmentFile=/etc/wishicraft/minecraft.env\n"
                        "WorkingDirectory=",
                        stage.data_volume_mount_path,
                        "/games/",
                        project.initial_game_id,
                        "/server\n"
                        "ExecStartPre=/usr/local/lib/wishicraft/data-volume-mount --verify\n"
                        "ExecStartPre=/usr/local/lib/wishicraft/minecraft-game-setup --verify\n"
                        "ExecStart=/usr/bin/java -Xms",
                        stage.java_xms,
                        " -Xmx",
                        stage.java_xmx,
                        " -jar ",
                        stage.data_volume_mount_path,
                        "/packages/vanilla/",
                        self.artifact.version,
                        "/server.jar nogui\nTimeoutStopSec=",
                        str(stage.minecraft_normal_stop_timeout_seconds),
                        "\nKillSignal=SIGTERM\nRestart=on-failure\nRestartSec=10\n"
                        "NoNewPrivileges=true\nPrivateTmp=true\nProtectHome=true\nProtectSystem=full\n"
                        "ReadWritePaths=",
                        stage.data_volume_mount_path,
                        "/games/",
                        project.initial_game_id,
                        "/server ",
                        stage.data_volume_mount_path,
                        "/games/",
                        project.initial_game_id,
                        "/runtime\n\n[Install]\nWantedBy=multi-user.target\n"
                        "WISHICRAFT_MINECRAFT_UNIT\n"
                        "systemctl daemon-reload\n"
                        "systemctl enable --now minecraft.service\n",
                    ],
                )
            ),
        )
