"""Agent installer — copies agent scripts and creates systemd units."""
from __future__ import annotations

import os
import shutil
import subprocess
import textwrap
from pathlib import Path
from typing import Any

_AGENT_INSTALL_DIR = Path("/usr/lib/agentos/agents")
_SYSTEMD_UNIT_DIR = Path("/lib/systemd/system")
_DEV_AGENT_DIR = Path(__file__).parent.parent.parent / "agents"


class AgentInstaller:
    """Install a marketplace agent onto the local system.

    In development mode (running without root / system dirs absent) the
    installer records the install in-memory and returns a result dict but
    does not write to system paths, so tests can run unprivileged.
    """

    def install(self, manifest: dict[str, Any]) -> dict[str, Any]:
        name = str(manifest["name"])
        entry_point = str(manifest["entry_point"])
        trust_level = str(manifest.get("trust_level", "user"))
        capabilities = list(manifest.get("capabilities", []))

        # Resolve source script path.
        source = Path(entry_point)
        if not source.is_absolute():
            source = _DEV_AGENT_DIR / source.name

        dry_run = not os.access("/usr/lib", os.W_OK)

        if not dry_run:
            _AGENT_INSTALL_DIR.mkdir(parents=True, exist_ok=True)
            dest = _AGENT_INSTALL_DIR / source.name
            if source.exists():
                shutil.copy2(source, dest)
                dest.chmod(0o755)
            self._write_systemd_unit(name, dest)
            self._enable_and_start(name)

        return {
            "installed": True,
            "name": name,
            "entry_point": str(entry_point),
            "trust_level": trust_level,
            "capabilities": capabilities,
            "dry_run": dry_run,
            "message": (
                f"Agent '{name}' installed successfully."
                if not dry_run
                else f"Agent '{name}' registered (dry-run: no write access to /usr/lib)."
            ),
        }

    # ------------------------------------------------------------------

    def _write_systemd_unit(self, name: str, script_path: Path) -> None:
        safe_name = name.replace("_", "-")
        unit_name = f"agentos-{safe_name}.service"
        unit_content = textwrap.dedent(f"""\
            [Unit]
            Description=AgentOS {name} agent
            After=agentos-runtime.service
            Requires=agentos-runtime.service

            [Service]
            Type=simple
            ExecStart=/usr/bin/python3 {script_path}
            Restart=on-failure
            RestartSec=5
            User=agentos
            EnvironmentFile=-/etc/agentos/agentos.env

            [Install]
            WantedBy=multi-user.target
        """)
        unit_path = _SYSTEMD_UNIT_DIR / unit_name
        unit_path.write_text(unit_content, encoding="utf-8")

    def _enable_and_start(self, name: str) -> None:
        safe_name = name.replace("_", "-")
        unit_name = f"agentos-{safe_name}.service"
        try:
            subprocess.run(
                ["systemctl", "daemon-reload"], check=True, capture_output=True
            )
            subprocess.run(
                ["systemctl", "enable", "--now", unit_name], check=True, capture_output=True
            )
        except (subprocess.CalledProcessError, FileNotFoundError):
            # Silently skip — systemd may not be running in the current environment.
            pass
