from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
import subprocess
import psutil
import json
import os

router = APIRouter()

_STATE_FILE = "/opt/abeonasec/plugins/.plugin-state.json"

def _read_state() -> dict:
    try:
        with open(_STATE_FILE) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def _set_plugin_state(plugin_id: str, **fields):
    state = _read_state()
    state.setdefault(plugin_id, {}).update(fields)
    os.makedirs(os.path.dirname(_STATE_FILE), exist_ok=True)
    with open(_STATE_FILE, "w") as f:
        json.dump(state, f)


def _default_interface() -> str:
    try:
        with open("/proc/net/route") as f:
            for line in f.readlines()[1:]:
                parts = line.split()
                if len(parts) >= 2 and parts[1] == "00000000":
                    return parts[0]
    except Exception:
        pass
    return ""


def _container_running(container_name: str) -> bool:
    try:
        r = subprocess.run(["docker", "ps", "--format", "{{.Names}}"],
                           capture_output=True, text=True)
        return container_name in r.stdout
    except FileNotFoundError:
        return False


def _get_plugin(plugin_id: str) -> dict:
    plugin = next((p for p in PLUGIN_REGISTRY if p["id"] == plugin_id), None)
    if plugin is None:
        raise HTTPException(status_code=404, detail="Plugin not found")
    return plugin


def _plugin_status(plugin: dict) -> str:
    state = _read_state().get(plugin["id"], {})
    if not state.get("installed"):
        return "not_installed"
    return "running" if _container_running(plugin["container_name"]) else "stopped"


def _abp_stdin(inputs: dict) -> str:
    return "accept\n"


def _abp_args(inputs: dict) -> list:
    iface = inputs.get("interface", "").strip() or _default_interface()
    return [iface] if iface else []


PLUGIN_REGISTRY = [
    {
        "id": "abp",
        "name": "Anomalous Behavior Profiling",
        "description": "ML-based network anomaly detection using live packet capture.",
        "repo": "https://github.com/AbeonaSec/abeonasec-plugin-abp.git",
        "install_path": "/opt/abeonasec/plugins/abp",
        "container_name": "plugin-abp",
        "install_fields": [
            {"key": "interface", "label": "Network Interface", "type": "interface_select", "required": False}
        ],
        "requires_disclaimer": True,
        "build_stdin": _abp_stdin,
        "build_args": _abp_args,
    }
]



@router.get("/plugins")
def list_plugins():
    default_if = _default_interface()
    result = []
    for p in PLUGIN_REGISTRY:
        entry = {k: v for k, v in p.items() if k != "build_stdin"}
        entry["status"] = _plugin_status(p)
        entry["default_interface"] = default_if
        result.append(entry)
    return {"plugins": result}


@router.get("/plugins/interfaces")
def list_interfaces():
    default_if = _default_interface()
    interfaces = [
        {"name": name, "address": next((a.address for a in addrs if a.family == 2), None), "is_default": name == default_if}
        for name, addrs in psutil.net_if_addrs().items()
        if name != "lo"
    ]
    return {"interfaces": interfaces, "default": default_if}


class InstallRequest(BaseModel):
    accepted: bool
    interface: str = ""


@router.post("/plugins/{plugin_id}/install")
def install_plugin(plugin_id: str, req: InstallRequest):
    plugin = _get_plugin(plugin_id)
    if plugin.get("requires_disclaimer") and not req.accepted:
        raise HTTPException(status_code=400, detail="Must accept the legal disclaimer")

    install_path = plugin["install_path"]

    if not os.path.exists(os.path.join(install_path, "init.sh")):
        r = subprocess.run(["git", "clone", plugin["repo"], install_path],
                           capture_output=True, text=True)
        if r.returncode != 0:
            raise HTTPException(status_code=500, detail=f"Clone failed: {r.stderr or r.stdout}")

    inputs = {"interface": req.interface}
    extra_args = plugin.get("build_args", lambda _: [])(inputs)
    env = os.environ.copy()
    env["PATH"] = "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
    proc = subprocess.run(
        ["bash", os.path.join(install_path, "init.sh")] + extra_args,
        input=plugin["build_stdin"](inputs),
        capture_output=True, text=True, cwd=install_path, env=env,
    )
    if proc.returncode != 0:
        raise HTTPException(status_code=500,
                            detail=proc.stderr or proc.stdout or "init.sh failed")

    _set_plugin_state(plugin_id, installed=True)
    return {"status": "installed", "output": proc.stdout}


@router.post("/plugins/{plugin_id}/enable")
def enable_plugin(plugin_id: str):
    plugin = _get_plugin(plugin_id)
    if _plugin_status(plugin) == "not_installed":
        raise HTTPException(status_code=400, detail="Plugin is not installed")

    r = subprocess.run(["docker", "start", plugin["container_name"]],
                       capture_output=True, text=True)
    if r.returncode != 0:
        raise HTTPException(status_code=500, detail=r.stderr)

    _set_plugin_state(plugin_id, status="running")
    return {"status": "running"}


@router.post("/plugins/{plugin_id}/disable")
def disable_plugin(plugin_id: str):
    plugin = _get_plugin(plugin_id)

    r = subprocess.run(["docker", "stop", plugin["container_name"]],
                       capture_output=True, text=True)
    if r.returncode != 0:
        raise HTTPException(status_code=500, detail=r.stderr)

    _set_plugin_state(plugin_id, status="stopped")
    return {"status": "stopped"}
