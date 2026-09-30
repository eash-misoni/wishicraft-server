"""Select Lambda assets via CDK manifest/template, then run networkless Linux probes.

No AWS SDK/client or CDK deployment is used. Docker pulls/builds precede isolated runs.
Only selected assets, a standalone driver and synthetic JSON cross the boundary.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import tomllib
from pathlib import Path
from typing import Any, cast

ROOT = Path(__file__).resolve().parents[2]


def command(args: list[str], **kw: Any) -> str:
    return cast(str, subprocess.check_output(args, text=True, **kw)).strip()


def select(assembly: Path) -> list[dict[str, Any]]:
    result = []
    for template in sorted(assembly.glob("*.template.json")):
        assets = json.loads(
            template.with_name(template.name.replace(".template.json", ".assets.json")).read_text()
        )["files"]
        for logical, resource in json.loads(template.read_text())["Resources"].items():
            if resource["Type"] != "AWS::Lambda::Function":
                continue
            p = resource["Properties"]
            assert p["Runtime"] == "python3.12"
            assert p.get("Architectures", ["x86_64"]) == ["x86_64"]
            key = p["Code"]["S3Key"]
            matches = [
                (h, a)
                for h, a in assets.items()
                if any(d["objectKey"] == key for d in a["destinations"].values())
            ]
            assert len(matches) == 1
            identity, asset = matches[0]
            path = (assembly / asset["source"]["path"]).resolve()
            assert path.is_relative_to(assembly.resolve()) and path.is_dir()
            result.append(
                dict(
                    logical_id=logical,
                    handler=p["Handler"],
                    asset_id=identity,
                    path=str(path),
                    template_sha256=hashlib.sha256(template.read_bytes()).hexdigest(),
                )
            )
    assert result
    return result


def sdk_requirements() -> str:
    packages = {p["name"]: p for p in tomllib.loads((ROOT / "uv.lock").read_text())["package"]}
    pending = ["boto3"]
    seen = set()
    lines = []
    while pending:
        name = pending.pop()
        if name in seen:
            continue
        seen.add(name)
        p = packages[name]
        pending.extend(d["name"] for d in p.get("dependencies", []))
        lines.append(
            name + "==" + p["version"] + " " + " ".join("--hash=" + w["hash"] for w in p["wheels"])
        )
    assert "pyyaml" not in seen and "aws-cdk-lib" not in seen
    return "\n".join(sorted(lines)) + "\n"


def run(current: list[Path], old: Path, output: Path, fixture: Path) -> None:
    output.mkdir(parents=True, exist_ok=False)
    shutil.copy2(fixture, output / "recovery.json")
    subprocess.run(["docker", "version"], check=True, stdout=subprocess.DEVNULL)
    image = "python:3.12-slim"
    subprocess.run(["docker", "pull", "--platform", "linux/amd64", image], check=True)
    base = json.loads(command(["docker", "image", "inspect", image]))[0]
    digest = base["RepoDigests"][0]
    build = output / "build"
    build.mkdir()
    (build / "sdk.txt").write_text(sdk_requirements())
    (build / "Dockerfile").write_text(
        "FROM "
        + digest
        + "\nCOPY sdk.txt /sdk.txt\nRUN pip install --no-cache-dir --require-hashes -r /sdk.txt\n"
    )
    subprocess.run(
        [
            "docker",
            "build",
            "--platform",
            "linux/amd64",
            "--iidfile",
            str(output / "image-id"),
            str(build),
        ],
        check=True,
    )
    runtime = (output / "image-id").read_text().strip()
    driver = output / "driver"
    driver.mkdir()
    shutil.copy2(ROOT / "tests/artifact/probe.py", driver / "probe.py")
    items = [item for assembly in current for item in select(assembly)]
    previous = next(
        x for x in select(old) if x["handler"] == "wishicraft.retention_workflow_lambda.handler"
    )
    retention = next(
        x for x in items if x["handler"] == "wishicraft.retention_workflow_lambda.handler"
    )
    scenarios: list[tuple[dict[str, Any], str, list[str]]] = [
        (previous, "old", []),
        (retention, "disabled", []),
        (retention, "dry-run", []),
        (retention, "recovery", []),
    ]
    for item in items:
        scenarios.append((item, "imports", [item["handler"]]))
    results = []
    for index, (item, mode, handlers) in enumerate(scenarios):
        args = [
            "docker",
            "run",
            "--rm",
            "--platform",
            "linux/amd64",
            "--network",
            "none",
            "--read-only",
            "--cap-drop",
            "ALL",
            "--security-opt",
            "no-new-privileges",
            "--user",
            "65534:65534",
            "--tmpfs",
            "/tmp:rw,noexec,nosuid,size=16m",
            "--workdir",
            "/tmp",
            "-v",
            item["path"] + ":/asset:ro",
            "-v",
            str(driver) + ":/driver:ro",
            "-v",
            str(output / "recovery.json") + ":/fixture/recovery.json:ro",
            runtime,
            "python",
            "-I",
            "-B",
            "/driver/probe.py",
            mode,
            *handlers,
        ]
        process = subprocess.run(args, text=True, capture_output=True)
        # The standalone driver emits only fixed status/identity, never exception bodies.
        (output / f"probe-{index}.jsonl").write_text(process.stdout)
        if process.returncode:
            raise RuntimeError(f"ARTIFACT_PROBE_FAILED:{index}:{mode}; inspect projected stdout")
        result = json.loads(process.stdout)
        assert result["status"] == "PASS"
        results.append(dict(asset=item["asset_id"], handler=item["handler"], **result))
    evidence = dict(
        base_image=digest,
        local_runtime_image=runtime,
        base_platform=base["Architecture"],
        sdk_requirements_sha256=hashlib.sha256((build / "sdk.txt").read_bytes()).hexdigest(),
        old_origin=(
            "regenerated CDK assembly of "
            "51fa628179c43c2ca1559077d3b196e9797822e9; not downloaded ZIP"
        ),
        artifacts=[{k: v for k, v in i.items() if k != "path"} for i in [previous, *items]],
        results=results,
        aws_calls=0,
        managed_lambda_identity_verified=False,
    )
    (output / "evidence.json").write_text(json.dumps(evidence, indent=2) + "\n")
    print(json.dumps(evidence, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--assembly", action="append", type=Path, required=True)
    parser.add_argument("--old-assembly", type=Path, required=True)
    parser.add_argument("--fixture", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    run(args.assembly, args.old_assembly, args.output, args.fixture)
