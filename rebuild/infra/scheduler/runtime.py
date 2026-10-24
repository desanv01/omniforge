"""Finite, opt-in OF-013-A runtime. Never operates on core or legacy resources.

Private root must be supplied outside source. Output deliberately excludes config,
tokens, DSNs and raw service logs. Retain all containers/volumes after settlement.
"""
import argparse
import json
import os
from pathlib import Path
import secrets
import socket
import subprocess
import time

PREFIX = "omniforge-rebuild-scheduler-of013a"
PG = PREFIX + "-postgres"
LITE = PREFIX + "-lite"
NETWORK = PREFIX + "-net"
INGRESS = PREFIX + "-ingress"
PG_VOLUME = PREFIX + "-pgdata"
CONFIG_VOLUME = PREFIX + "-config"
PG_IMAGE = "sha256:32ebb7185baf2c9d38f91684417d140c0745aeff5082dfbb62edb330c2af6197"
LITE_TAG = "ghcr.io/hatchet-dev/hatchet/hatchet-lite:v0.110.5"
PORTS = (63151, 63152)


def docker(*args):
    result = subprocess.run(["docker", *args], capture_output=True, text=True)
    if result.returncode:
        raise RuntimeError("Docker operation failed: " + args[0])
    return result.stdout.strip()


def save(root, name, value):
    (root / name).write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")


def owned(name):
    label = docker("inspect", "--format", '{{index .Config.Labels "omniforge.owner"}}', name)
    if label != "OF-013-A":
        raise RuntimeError("Refusing unowned resource")


def prepare(root):
    source = Path(__file__).resolve().parents[2]
    if root.exists() or root == source or source in root.parents:
        raise RuntimeError("Requires a new private root outside source")
    names = docker("ps", "-a", "--format", "{{.Names}}").splitlines()
    volumes = docker("volume", "ls", "--format", "{{.Name}}").splitlines()
    networks = docker("network", "ls", "--format", "{{.Name}}").splitlines()
    if any(n in names for n in (PG, LITE)) or any(v in volumes for v in (PG_VOLUME, CONFIG_VOLUME)) or any(n in networks for n in (NETWORK, INGRESS)):
        raise RuntimeError("Owned names already exist; inspect instead of recreating")
    for port in PORTS:
        with socket.socket() as check:
            check.bind(("127.0.0.1", port))
    # Resolve downloaded tag to immutable local content before execution.
    image = json.loads(docker("image", "inspect", LITE_TAG))[0]
    digest = next(d for d in image["RepoDigests"] if "hatchet-lite@sha256:" in d)
    root.mkdir(parents=True)
    account = subprocess.run(["whoami"], capture_output=True, text=True, check=True).stdout.strip()
    subprocess.run(["icacls", str(root), "/inheritance:r", "/grant:r", account + ":(OI)(CI)F"], check=True, capture_output=True)
    password = secrets.token_hex(32)
    (root / "postgres-password").write_text(password, encoding="utf-8")
    env = {
        "DATABASE_URL": f"postgresql://scheduler:{password}@{PG}:5432/scheduler?sslmode=disable",
        "SERVER_AUTH_COOKIE_DOMAIN": "localhost", "SERVER_AUTH_COOKIE_INSECURE": "t",
        "SERVER_GRPC_BIND_ADDRESS": "0.0.0.0", "SERVER_GRPC_INSECURE": "t",
        "SERVER_GRPC_PORT": "7077", "SERVER_GRPC_BROADCAST_ADDRESS": "127.0.0.1:63152",
        "SERVER_URL": "http://127.0.0.1:63151", "SERVER_AUTH_SET_EMAIL_VERIFIED": "t",
        "SERVER_INTERNAL_CLIENT_INTERNAL_GRPC_BROADCAST_ADDRESS": "localhost:7077",
        "SERVER_MSGQUEUE_KIND": "postgres",
    }
    (root / "lite.env").write_text("".join(f"{k}={v}\n" for k, v in env.items()), encoding="utf-8")
    docker("network", "create", "--internal", "--label", "omniforge.owner=OF-013-A", NETWORK)
    docker("network", "create", "--label", "omniforge.owner=OF-013-A", "--opt", "com.docker.network.bridge.host_binding_ipv4=127.0.0.1", INGRESS)
    for volume in (PG_VOLUME, CONFIG_VOLUME):
        docker("volume", "create", "--label", "omniforge.owner=OF-013-A", volume)
    receipt = {"owner": "OF-013-A", "state": "preparing", "containers": {},
               "volumes": [PG_VOLUME, CONFIG_VOLUME], "network": NETWORK, "ingress_network": INGRESS,
               "loopback_ports": list(PORTS), "lite_image": digest, "pg_image": PG_IMAGE}
    save(root, "resource-receipt.json", receipt)
    receipt["containers"][PG] = docker("run", "-d", "--name", PG, "--label", "omniforge.owner=OF-013-A",
        "--restart", "no", "--network", NETWORK, "--memory", "512m", "--cpus", "1",
        "--mount", f"type=volume,src={PG_VOLUME},dst=/var/lib/postgresql/data",
        "--mount", f"type=bind,src={root / 'postgres-password'},dst=/run/secrets/password,readonly",
        "--env", "POSTGRES_PASSWORD_FILE=/run/secrets/password", "--env", "POSTGRES_USER=scheduler",
        "--env", "POSTGRES_DB=scheduler", "--health-cmd", "pg_isready -U scheduler -d scheduler",
        "--health-interval", "2s", "--health-timeout", "2s", "--health-retries", "20",
        PG_IMAGE, "postgres", "-c", "max_connections=200")
    save(root, "resource-receipt.json", receipt)
    deadline = time.monotonic() + 50
    while time.monotonic() < deadline:
        if docker("inspect", "--format", "{{.State.Health.Status}}", PG) == "healthy":
            break
        time.sleep(1)
    else:
        raise RuntimeError("Owned PostgreSQL readiness deadline")
    receipt["containers"][LITE] = docker("run", "-d", "--name", LITE, "--label", "omniforge.owner=OF-013-A",
        "--restart", "no", "--network", NETWORK, "--memory", "1536m", "--cpus", "2",
        "--publish", "127.0.0.1:63151:8888", "--publish", "127.0.0.1:63152:7077",
        "--env-file", str(root / "lite.env"), "--mount", f"type=volume,src={CONFIG_VOLUME},dst=/config", digest)
    docker("network", "connect", INGRESS, LITE)
    receipt["state"] = "started"
    save(root, "resource-receipt.json", receipt)
    print(json.dumps(receipt))


def status(root):
    receipt = json.loads((root / "resource-receipt.json").read_text())
    for name in receipt["containers"]:
        owned(name)
        obj = json.loads(docker("inspect", name))[0]
        receipt["containers"][name] = {"id": obj["Id"], "state": obj["State"]["Status"],
            "exit_code": obj["State"]["ExitCode"], "ports": obj["NetworkSettings"]["Ports"],
            "mounts": [{"type": m["Type"], "name": m.get("Name"), "destination": m["Destination"], "rw": m["RW"]} for m in obj["Mounts"]]}
    save(root, "status.json", receipt)
    print(json.dumps(receipt))


def settle(root):
    for name in (LITE, PG):
        owned(name)
        docker("stop", "--timeout", "15", name)
    receipt = json.loads((root / "resource-receipt.json").read_text())
    receipt["state"] = "stopped-preserved"
    save(root, "resource-receipt.json", receipt)
    status(root)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("operation", choices=("prepare", "status", "settle"))
    parser.add_argument("root", type=Path)
    args = parser.parse_args()
    if os.name != "nt":
        raise SystemExit("Windows ACL bootstrap only")
    globals()[args.operation](args.root.resolve())
