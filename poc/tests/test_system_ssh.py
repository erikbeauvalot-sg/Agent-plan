"""mcp-system contre un faux ssh (sorties de sonde préparées), et refus de la sonde distante."""

import asyncio
import json
import subprocess

import pytest
import yaml

from conftest import POC
from diagagent import catalog
from diagagent.connectors import ssh
from diagagent.tools import ToolHub

CID = "a" * 64
OUTPUTS = {
    "memory": """### meminfo
MemTotal:       12247704 kB
MemAvailable:   10694792 kB
AnonPages:        901236 kB
Cached:           658420 kB
SwapCached:        41484 kB
SwapTotal:        999420 kB
SwapFree:         325580 kB
Committed_AS:    3145728 kB
### psi
some avg10=0.00 avg60=0.12 avg300=0.05 total=123
full avg10=0.00 avg60=0.01 avg300=0.00 total=45
### swappiness
60
### uptime
500094.12 900000.00
""",
    "processes": f"""### ps
      1 root          7180  500094 /sbin/init
      2 root             0  500094 [kthreadd]
    812 www-data   1048576   86400 php-fpm: pool www
    950 999         204800    3600 postgres: checkpointer
### swap
/proc/1/status:VmSwap:	       0 kB
/proc/812/status:VmSwap:	  102400 kB
/proc/950/status:VmSwap:	  307200 kB
### cgroup
/proc/1/cgroup:0::/init.scope
/proc/812/cgroup:0::/system.slice/docker-{CID}.scope
/proc/950/cgroup:0::/system.slice/docker-{"b" * 64}.scope
### docker
{CID} nextcloud-app
""",
    "containers": f"""### cgroups
{CID} 1073741824 104857600 1610612736 max
{"b" * 64} 209715200 314572800 - 536870912
### docker
{CID} nextcloud-app
""",
    "oom": """### oom
2026-10-06T03:17:02+0200 xdocker kernel: Out of memory: Killed process 4242 (php-fpm)
""",
}


@pytest.fixture
def fake_ssh(tmp_path, monkeypatch):
    for probe, text in OUTPUTS.items():
        (tmp_path / f"{probe}.out").write_text(text)
    script = tmp_path / "ssh"
    script.write_text(f'#!/bin/sh\necho "$@" >> {tmp_path}/args.log\ncat > {tmp_path}/stdin.sh\n'
                      f'for last; do :; done\ncat {tmp_path}/$last.out\n')
    script.chmod(0o755)
    monkeypatch.setenv("DIAGAGENT_SSH_COMMAND", str(script))
    for var in ("PROMETHEUS_URL", "ALERTMANAGER_URL"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("SSH_HOSTS", "xdocker=192.168.1.20,pdocker")
    monkeypatch.setenv("SSH_USER", "diagagent")
    monkeypatch.setenv("DIAGAGENT_SOURCES", "maison")
    catalog.load_catalog.cache_clear()
    return tmp_path


def _call(name, args):
    servers = yaml.safe_load((POC / "config" / "poc.yaml").read_text())["mcp_servers"]

    async def go():
        async with ToolHub(servers) as hub:
            return await hub.call(name, args)
    return asyncio.run(go())


def _ok(name, args):
    res = _call(name, args)
    assert not res.is_error, res.content
    return json.loads(res.content)


def test_ssh_sources_alone_make_home_set_available(fake_ssh):
    assert set(catalog.load_catalog()) == {"system-ssh"}
    assert catalog.configured_sources() == ["demo", "maison"]
    assert _ok("list_ssh_hosts", {})["hosts"] == ["pdocker", "xdocker"]


def test_host_memory_sends_fixed_probe_to_declared_address(fake_ssh):
    data = _ok("host_memory", {"host": "xdocker"})
    assert data["swap_used_mb"] == 658.0 and data["mem_available_mb"] == 10444.1
    assert data["pressure_pct"]["some"]["avg60"] == 0.12 and data["swappiness"] == 60
    assert data["observed_at"] and "pas à l'heure de référence" in data["note"]
    args = (fake_ssh / "args.log").read_text().split()
    assert args[-6:] == ["diagagent", "192.168.1.20", "sh", "-s", "--", "memory"]
    assert "BatchMode=yes" in args and "StrictHostKeyChecking=yes" in args
    assert (fake_ssh / "stdin.sh").read_text() == (POC / "remote" / "diagagent-probe").read_text()


def test_top_processes_by_swap_with_containers(fake_ssh):
    data = _ok("top_processes", {"host": "xdocker", "sort_by": "swap"})
    assert [p["pid"] for p in data["processes"]] == [950, 812, 1]  # threads du noyau exclus
    assert data["processes"][0]["container"] == "b" * 12  # conteneur sans nom connu
    assert data["processes"][1] == {"pid": 812, "user": "www-data", "command": "php-fpm: pool www",
                                    "rss_mb": 1024.0, "swap_mb": 100.0, "running_h": 24.0,
                                    "container": "nextcloud-app"}
    assert data["swap_total_mb"] == 400.0


def test_container_memory_and_oom(fake_ssh):
    containers = _ok("container_memory", {"host": "xdocker"})["containers"]
    assert containers[0] == {"container": "nextcloud-app", "id": "a" * 12, "mem_mb": 1024.0,
                             "swap_mb": 100.0, "peak_mb": 1536.0, "limit_mb": None}
    assert containers[1]["peak_mb"] is None and containers[1]["limit_mb"] == 512.0
    events = _ok("oom_events", {"host": "xdocker"})
    assert events["total"] == 1 and "Killed process 4242" in events["events"][0]


def test_undeclared_host_is_refused_without_connecting(fake_ssh):
    res = _call("host_memory", {"host": "192.168.1.20; rm -rf /"})
    assert res.is_error and "SSH_HOSTS" in res.content
    assert not (fake_ssh / "args.log").exists()


def test_ssh_failure_comes_back_as_tool_error(fake_ssh):
    (fake_ssh / "ssh").write_text("#!/bin/sh\necho 'Host key verification failed.' >&2\nexit 255\n")
    res = _call("oom_events", {"host": "pdocker"})
    assert res.is_error and "Host key verification failed" in res.content


def test_system_role_and_server_off_without_ssh_hosts():
    assert "system-ssh" not in catalog.load_catalog()
    with pytest.raises(ValueError, match="SSH_HOSTS"):
        ssh.SshProbe({"id": "x", "backend": {}}).run("xdocker", "memory")


@pytest.mark.parametrize("request_line", ["rm", "sh -s -- memory; rm -rf /", "", "processes extra"])
def test_remote_probe_refuses_anything_else(request_line):
    done = subprocess.run(["sh", str(POC / "remote" / "diagagent-probe")], capture_output=True, text=True,
                          env={"PATH": "/usr/bin:/bin", "SSH_ORIGINAL_COMMAND": request_line})
    assert done.returncode == 2 and "sonde inconnue" in done.stderr
    assert done.stdout == ""
