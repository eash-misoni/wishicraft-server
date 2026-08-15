"""Bootstrap the retained data EBS mount without relying on its attachment name."""

from __future__ import annotations

import base64
import gzip
from pathlib import Path

from aws_cdk import Fn
from constructs import Construct

from infrastructure.constructs.bootstrap_bundle import build_bundle, bundle_sha256, member_list
from infrastructure.constructs.java_runtime import resolve_java_package
from infrastructure.constructs.minecraft_artifact import resolve_minecraft_artifact
from infrastructure.constructs.minecraft_data_volume import MinecraftDataVolume
from infrastructure.constructs.minecraft_instance import MinecraftInstance
from wishicraft.config import ProjectConfig, StageConfig

_SCRIPT_PATH = Path(__file__).parents[1] / "bootstrap" / "data_volume_mount.sh"
_JAVA_SCRIPT_PATH = Path(__file__).parents[1] / "bootstrap" / "java_runtime_install.sh"
_ARTIFACT_SCRIPT_PATH = Path(__file__).parents[1] / "bootstrap" / "minecraft_artifact_install.sh"
_GAME_SCRIPT_PATH = Path(__file__).parents[1] / "bootstrap" / "minecraft_game_setup.sh"
_RCON_SCRIPT_PATH = Path(__file__).parents[1] / "bootstrap" / "minecraft_rcon_configure.sh"


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
        rcon_parameter_name: str,
    ) -> None:
        super().__init__(scope, construct_id)
        self.java_package = resolve_java_package(stage.java_runtime)
        bundle = build_bundle(Path(__file__).parents[1] / "bootstrap")
        bundle_base64 = base64.b64encode(bundle).decode("ascii")
        bundle_digest = bundle_sha256(bundle)
        runner = (Path(__file__).parents[1] / "bootstrap" / "bootstrap_runner.sh").read_text(
            encoding="utf-8"
        )
        runner_base64 = base64.b64encode(gzip.compress(runner.encode("utf-8"), mtime=0)).decode(
            "ascii"
        )
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
                        "printf '%s' '",
                        runner_base64,
                        "' | base64 -d | gzip -d > "
                        "/usr/local/sbin/wishicraft-bootstrap-runner\n"
                        "chmod 0700 /usr/local/sbin/wishicraft-bootstrap-runner\n"
                        "BUNDLE_BASE64='",
                        bundle_base64,
                        "' BUNDLE_SHA256='",
                        bundle_digest,
                        "' BUNDLE_MEMBERS='",
                        member_list(),
                        "' /usr/local/sbin/wishicraft-bootstrap-runner\n",
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
                        "MOUNT_GUARD=/usr/local/lib/wishicraft/data_volume_mount.sh\n"
                        "GAME_SETUP=/usr/local/lib/wishicraft/minecraft_game_setup.sh\n"
                        "DATA_VOLUME_ID=",
                        data_volume.volume.ref,
                        "\nFILESYSTEM_TYPE=",
                        stage.data_volume_filesystem_type,
                        "\n",
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
                        project.initial_minecraft_profile_uuid_hyphenated,
                        "\nRCON_PARAMETER_NAME=",
                        rcon_parameter_name,
                        "\nRCON_PORT=",
                        str(stage.rcon_port),
                        "\nSERVER_PROPERTIES=",
                        stage.data_volume_mount_path,
                        "/games/",
                        project.initial_game_id,
                        "/server/server.properties",
                        "\nWISHICRAFT_MINECRAFT_ENV\n",
                        "cat > /etc/systemd/system/wishicraft-data-volume.service "
                        "<<'WISHICRAFT_DATA_VOLUME_UNIT'\n",
                        "[Unit]\nDescription=Wishicraft data EBS preparation\n"
                        "Wants=network-online.target\nAfter=network-online.target\n"
                        "Before=minecraft.service\n\n",
                        "[Service]\nType=oneshot\n"
                        "EnvironmentFile=/etc/wishicraft/data-volume.env\n"
                        "ExecStart=/usr/local/lib/wishicraft/data_volume_mount.sh\n"
                        "ExecStart=/usr/local/lib/wishicraft/data_volume_mount.sh --verify\n"
                        "RemainAfterExit=yes\n\n",
                        "[Install]\nWantedBy=multi-user.target\nWISHICRAFT_DATA_VOLUME_UNIT\n",
                        "systemctl daemon-reload\n"
                        "systemctl enable --now wishicraft-data-volume.service\n"
                        "JAVA_RUNTIME=",
                        stage.java_runtime,
                        " /usr/local/lib/wishicraft/java_runtime_install.sh\n"
                        "set -a\n. /etc/wishicraft/minecraft.env\nset +a\n"
                        "/usr/local/lib/wishicraft/minecraft_game_setup.sh --prepare\n"
                        "/usr/local/lib/wishicraft/minecraft_artifact_install.sh\n"
                        "/usr/local/lib/wishicraft/minecraft_game_setup.sh\n"
                        "/usr/local/lib/wishicraft/minecraft_rcon_configure.sh\n",
                        "cat > /etc/systemd/system/wishicraft-rcon-firewall.service "
                        "<<'WISHICRAFT_RCON_FIREWALL_UNIT'\n"
                        "[Unit]\nDescription=Wishicraft RCON loopback firewall\n"
                        "Wants=network-online.target\nAfter=network-online.target\n"
                        "Before=minecraft.service\n\n"
                        "[Service]\nType=oneshot\n"
                        "EnvironmentFile=/etc/wishicraft/minecraft.env\n"
                        "ExecStart=/usr/local/lib/wishicraft/minecraft_rcon_firewall.sh\n"
                        "RemainAfterExit=yes\n\n"
                        "[Install]\nWantedBy=multi-user.target\n"
                        "WISHICRAFT_RCON_FIREWALL_UNIT\n"
                        "systemctl daemon-reload\n"
                        "systemctl enable --now wishicraft-rcon-firewall.service\n",
                        "cat > /etc/systemd/system/minecraft.service "
                        "<<'WISHICRAFT_MINECRAFT_UNIT'\n",
                        "[Unit]\nDescription=Wishicraft Minecraft server\n"
                        "Requires=wishicraft-data-volume.service\n"
                        "Requires=wishicraft-rcon-firewall.service\n"
                        "After=wishicraft-data-volume.service wishicraft-rcon-firewall.service\n\n"
                        "[Service]\nType=simple\nUser=minecraft\nGroup=minecraft\n"
                        "EnvironmentFile=/etc/wishicraft/minecraft.env\n"
                        "WorkingDirectory=",
                        stage.data_volume_mount_path,
                        "/games/",
                        project.initial_game_id,
                        "/server\n"
                        "ExecStartPre=+/usr/local/lib/wishicraft/data_volume_mount.sh --verify\n"
                        "ExecStartPre=+/usr/local/lib/wishicraft/minecraft_game_setup.sh --verify\n"
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
