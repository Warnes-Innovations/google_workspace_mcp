#!/usr/bin/env python3
"""Manage the Workspace-MCP server process using a configuration file."""

from __future__ import annotations

import argparse
import os
import shutil
import signal
import stat
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover
    import tomli as tomllib

_CONFIG_FIELDS = {
    "command",
    "args",
    "working_dir",
    "pid_file",
    "log_file",
    "env_file",
    "env",
    "start_timeout",
}

DEFAULT_CONFIG_PATH = "mcp-config.toml"
DEFAULT_START_TIMEOUT = 10


@dataclass(frozen=True)
class WorkspaceMCPConfig:
    command: list[str]
    args: list[str]
    working_dir: Path
    pid_file: Path
    log_file: Path
    env_file: Path | None
    env: dict[str, str]
    start_timeout: int


class WorkspaceMCPController:
    def __init__(self, config: WorkspaceMCPConfig) -> None:
        self.config = config

    def _pid_path(self) -> Path:
        return self.config.pid_file

    def _load_pid(self) -> int | None:
        pid_path = self._pid_path()
        if not pid_path.exists():
            return None
        try:
            content = pid_path.read_text().strip()
            return int(content)
        except Exception:
            return None

    def _write_pid(self, pid: int) -> None:
        self.config.pid_file.parent.mkdir(parents=True, exist_ok=True)
        self.config.pid_file.write_text(str(pid))
        os.chmod(self.config.pid_file, stat.S_IRUSR | stat.S_IWUSR | stat.S_IRGRP | stat.S_IROTH)

    def _remove_pid(self) -> None:
        try:
            self.config.pid_file.unlink()
        except FileNotFoundError:
            pass

    def _build_env(self) -> dict[str, str]:
        env = os.environ.copy()
        env.update(self.config.env)
        if self.config.env_file:
            env.update(self._load_env_file(self.config.env_file))
        return env

    def _load_env_file(self, path: Path) -> dict[str, str]:
        env: dict[str, str] = {}
        if not path.exists():
            raise FileNotFoundError(f"Env file not found: {path}")
        for line in path.read_text().splitlines():
            if not line or line.startswith("#"):
                continue
            if "=" not in line:
                continue
            key, value = line.split("=", 1)
            env[key.strip()] = value.strip().strip('"').strip("'")
        return env

    def _is_process_running(self, pid: int) -> bool:
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return False
        except PermissionError:
            return True
        return True

    def status(self) -> int:
        pid = self._load_pid()
        if pid is None:
            print("Workspace-MCP is not running.")
            return 1
        if self._is_process_running(pid):
            print(f"Workspace-MCP is running with PID {pid}.")
            return 0
        print(f"Workspace-MCP PID file exists but process {pid} is not running.")
        return 1

    def start(self) -> int:
        if self._load_pid() is not None:
            pid = self._load_pid()
            if pid and self._is_process_running(pid):
                print(f"Workspace-MCP is already running with PID {pid}.")
                return 0
            print("Stale PID file detected; removing.")
            self._remove_pid()

        self.config.working_dir.mkdir(parents=True, exist_ok=True)
        self.config.log_file.parent.mkdir(parents=True, exist_ok=True)

        stdout = stderr = open(self.config.log_file, "a", encoding="utf-8")
        command_line = self.config.command + self.config.args

        print(f"Starting Workspace-MCP with command: {' '.join(command_line)}")
        if self.config.env_file:
            print(f"Loading environment from: {self.config.env_file}")

        creationflags = 0
        kwargs: dict[str, Any] = {
            "cwd": str(self.config.working_dir),
            "env": self._build_env(),
            "stdout": stdout,
            "stderr": stderr,
        }
        if os.name == "nt":
            creationflags = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS
            kwargs["creationflags"] = creationflags
        else:
            kwargs["start_new_session"] = True

        try:
            process = subprocess.Popen(command_line, **kwargs)
        except FileNotFoundError as exc:
            print(f"Error: Unable to start command: {exc}")
            return 1

        self._write_pid(process.pid)
        print(f"Workspace-MCP started with PID {process.pid}. Logs -> {self.config.log_file}")

        if os.name != "nt":
            start_time = time.time()
            while time.time() - start_time < self.config.start_timeout:
                if self._is_process_running(process.pid):
                    return 0
                time.sleep(0.2)
            print("Warning: process did not remain running after start timeout.")
        return 0

    def stop(self) -> int:
        pid = self._load_pid()
        if pid is None:
            print("Workspace-MCP is not running.")
            return 1
        if not self._is_process_running(pid):
            print(f"Workspace-MCP PID {pid} is not active. Removing stale PID file.")
            self._remove_pid()
            return 1

        print(f"Stopping Workspace-MCP PID {pid}...")
        try:
            if os.name == "nt":
                os.kill(pid, signal.CTRL_BREAK_EVENT)
            else:
                os.kill(pid, signal.SIGTERM)
        except PermissionError:
            print(f"Permission denied stopping PID {pid}.")
            return 1
        except ProcessLookupError:
            print(f"Process {pid} already exited.")
            self._remove_pid()
            return 0

        stop_deadline = time.time() + 10
        while time.time() < stop_deadline:
            if not self._is_process_running(pid):
                print("Workspace-MCP stopped.")
                self._remove_pid()
                return 0
            time.sleep(0.2)

        print("Workspace-MCP did not stop gracefully; sending SIGKILL.")
        try:
            if os.name != "nt":
                os.kill(pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        self._remove_pid()
        return 0

    def restart(self) -> int:
        stop_code = self.stop()
        if stop_code not in (0, 1):
            return stop_code
        return self.start()


def parse_config(path: Path) -> WorkspaceMCPConfig:
    if not path.exists():
        raise FileNotFoundError(f"Config file not found: {path}")
    with path.open("rb") as fh:
        config_data = tomllib.load(fh)

    if not isinstance(config_data, dict):
        raise ValueError("Config file must contain a table at the root.")

    unknown = set(config_data) - _CONFIG_FIELDS
    if unknown:
        raise ValueError(f"Unknown config fields: {', '.join(sorted(unknown))}")

    command = config_data.get("command")
    args = config_data.get("args", [])
    if isinstance(command, str):
        command_list = [command]
    elif isinstance(command, list) and all(isinstance(item, str) for item in command):
        command_list = command
    else:
        raise ValueError("'command' must be a string or list of strings.")

    if not isinstance(args, list) or not all(isinstance(item, str) for item in args):
        raise ValueError("'args' must be a list of strings.")

    config_dir = path.parent
    working_dir = (config_dir / config_data.get("working_dir", ".")).expanduser().resolve()
    pid_file = (config_dir / config_data.get("pid_file", "workspace-mcp.pid")).expanduser().resolve()
    log_file = (config_dir / config_data.get("log_file", "workspace-mcp.log")).expanduser().resolve()
    env_file = config_data.get("env_file")
    env_file_path = (
        (config_dir / env_file).expanduser().resolve() if env_file else None
    )
    env = config_data.get("env", {})
    if not isinstance(env, dict) or not all(isinstance(k, str) and isinstance(v, str) for k, v in env.items()):
        raise ValueError("'env' must be a table of string values.")
    start_timeout = config_data.get("start_timeout", DEFAULT_START_TIMEOUT)
    if not isinstance(start_timeout, int) or start_timeout < 1:
        raise ValueError("'start_timeout' must be a positive integer.")

    return WorkspaceMCPConfig(
        command=command_list,
        args=args,
        working_dir=working_dir,
        pid_file=pid_file,
        log_file=log_file,
        env_file=env_file_path,
        env=env,
        start_timeout=start_timeout,
    )


def get_repo_root() -> Path:
    return Path(__file__).resolve().parent


def install_workspace_mcp_server(repo_root: Path) -> int:
    print(f"Installing Workspace-MCP package from {repo_root}")
    try:
        subprocess.run(
            [sys.executable, "-m", "pip", "install", "--editable", str(repo_root)],
            check=True,
        )
        print("Workspace-MCP package installed successfully.")
        return 0
    except subprocess.CalledProcessError as exc:
        print(f"Error installing Workspace-MCP package: {exc}", file=sys.stderr)
        return 1


def install_workspace_mcp_skill(source: Path, target: Path, copy_skill: bool = False, force: bool = False) -> int:
    if not source.exists():
        print(f"Skill source not found: {source}", file=sys.stderr)
        return 1

    target_parent = target.parent
    target_parent.mkdir(parents=True, exist_ok=True)

    if target.exists() or target.is_symlink():
        if target.is_symlink() and target.resolve() == source.resolve():
            print(f"Skill already installed at {target}")
            return 0
        if not force:
            print(
                f"Target skill path already exists: {target}. Use --force to overwrite.",
                file=sys.stderr,
            )
            return 1
        if target.is_dir() and not target.is_symlink():
            shutil.rmtree(target)
        else:
            target.unlink()

    if copy_skill or os.name == "nt":
        shutil.copytree(source, target)
        print(f"Copied skill files to {target}")
    else:
        try:
            target.symlink_to(source, target_is_directory=True)
            print(f"Symlinked skill files to {target}")
        except OSError:
            shutil.copytree(source, target)
            print(f"Failed to symlink; copied skill files to {target}")
    return 0


def normalize_client_name(client: str) -> str:
    canonical = client.strip().lower()
    if canonical == "clive":
        canonical = "cline"
    return canonical


def prompt_for_clients() -> str:
    print("Choose the client(s) you want to install skills for:")
    print("  1) Claude")
    print("  2) Copilot")
    print("  3) Codex")
    print("  4) Cline/Clive")
    print("  5) All of the above")
    choice = input("Enter a comma-separated list (for example 1,3 or 5) [5]: ").strip()
    if choice == "":
        return "all"
    selected: list[str] = []
    for token in [token.strip().lower() for token in choice.replace(" ", "").split(",") if token.strip()]:
        if token == "1" or token == "claude":
            selected.append("claude")
            continue
        if token == "2" or token == "copilot":
            selected.append("copilot")
            continue
        if token == "3" or token == "codex":
            selected.append("codex")
            continue
        if token == "4" or token == "cline" or token == "clive":
            selected.append("cline")
            continue
        if token == "5" or token == "all" or token == "*":
            return "all"
        raise ValueError(f"Unsupported client selection: {token}")
    return ",".join(dict.fromkeys(selected)) or "all"


def parse_clients(clients: str) -> list[str]:
    if clients is None:
        return []
    if not clients.strip():
        return ["claude", "copilot", "codex", "cline"]
    normalized = [normalize_client_name(client) for client in clients.split(",")]
    expanded: list[str] = []
    for client in normalized:
        if client in ("all", "*"):
            return ["claude", "copilot", "codex", "cline"]
        if client not in {"claude", "copilot", "codex", "cline"}:
            raise ValueError(
                f"Unsupported client: {client}. Supported clients are claude, copilot, codex, cline, clive, all."
            )
        if client not in expanded:
            expanded.append(client)
    return expanded


def default_skill_target_for_client(client: str) -> Path:
    home = Path.home()
    if client == "claude":
        return home / ".claude" / "skills" / "managing-google-workspace"
    if client == "copilot":
        return home / ".copilot" / "skills" / "managing-google-workspace"
    if client == "codex":
        return home / ".codex" / "skills" / "managing-google-workspace"
    if client == "cline":
        return home / ".clive" / "skills" / "managing-google-workspace"
    raise ValueError(f"No skill target mapping for client: {client}")


def install_client_skills(
    skill_source: Path,
    client: str,
    custom_target: Path | None,
    copy_skill: bool,
    force: bool,
) -> int:
    target = custom_target if custom_target is not None else default_skill_target_for_client(client)
    print(f"Installing skill for {client} at {target}")
    return install_workspace_mcp_skill(skill_source, target, copy_skill=copy_skill, force=force)


def install_command(args: argparse.Namespace) -> int:
    if args.no_server and args.no_skills:
        print("Nothing to install. Use --no-server or --no-skills only when one of the install steps should be skipped.", file=sys.stderr)
        return 1

    if args.clients is None:
        if not sys.stdin.isatty():
            print("Interactive prompt required when --clients is omitted.", file=sys.stderr)
            return 2
        try:
            args.clients = prompt_for_clients()
        except ValueError as exc:
            print(f"Error: {exc}", file=sys.stderr)
            return 2

    try:
        clients = parse_clients(args.clients)
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2

    if args.skill_dir and len(clients) != 1:
        print("--skill-dir may only be used with a single client selection.", file=sys.stderr)
        return 2

    repo_root = get_repo_root()
    if not args.no_server:
        status = install_workspace_mcp_server(repo_root)
        if status != 0:
            return status

    if not args.no_skills:
        skill_source = repo_root / "skills" / "managing-google-workspace"
        for client in clients:
            custom_target = args.skill_dir.expanduser().resolve() if args.skill_dir else None
            status = install_client_skills(
                skill_source,
                client,
                custom_target,
                copy_skill=args.copy_skills,
                force=args.force,
            )
            if status != 0:
                return status

    return 0


def print_config_summary(config: WorkspaceMCPConfig) -> None:
    print("Workspace-MCP management configuration:")
    print(f"  command: {' '.join(config.command + config.args)}")
    print(f"  working_dir: {config.working_dir}")
    print(f"  pid_file: {config.pid_file}")
    print(f"  log_file: {config.log_file}")
    print(f"  env_file: {config.env_file or '<none>'}")
    if config.env:
        print("  env:")
        for key, value in config.env.items():
            print(f"    {key}={value}")
    print(f"  start_timeout: {config.start_timeout}")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Workspace-MCP server process manager",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--config",
        default=DEFAULT_CONFIG_PATH,
        help="Path to the Workspace-MCP management config file.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("start", help="Start the Workspace-MCP server.")
    sub.add_parser("stop", help="Stop the Workspace-MCP server.")
    sub.add_parser("restart", help="Restart the Workspace-MCP server.")
    sub.add_parser("status", help="Show the current server status.")
    sub.add_parser("check-config", help="Validate the management config file.")
    install_parser = sub.add_parser(
        "install",
        help="Install the Workspace-MCP package and bundled skill files.",
    )
    install_parser.add_argument(
        "--no-server",
        action="store_true",
        help="Skip installing the Workspace-MCP package.",
    )
    install_parser.add_argument(
        "--no-skills",
        action="store_true",
        help="Skip installing the bundled skill files.",
    )
    install_parser.add_argument(
        "--clients",
        default=None,
        help="Comma-separated list of clients to install skills for. Supported values: claude, copilot, codex, cline, clive, all. If omitted, the command will prompt interactively.",
    )
    install_parser.add_argument(
        "--skill-dir",
        type=Path,
        default=None,
        help="Optional custom target directory for a single selected client's skill installation.",
    )
    install_parser.add_argument(
        "--copy-skills",
        action="store_true",
        help="Copy the bundled skills instead of creating a symlink.",
    )
    install_parser.add_argument(
        "--force",
        action="store_true",
        help="Overwrite an existing installed skill directory.",
    )

    args = parser.parse_args()
    if args.command == "install":
        return install_command(args)

    config_path = Path(args.config).expanduser().resolve()

    try:
        config = parse_config(config_path)
    except Exception as exc:
        print(f"Error loading config: {exc}", file=sys.stderr)
        return 2

    if args.command == "check-config":
        print_config_summary(config)
        return 0

    controller = WorkspaceMCPController(config)
    if args.command == "start":
        return controller.start()
    if args.command == "stop":
        return controller.stop()
    if args.command == "restart":
        return controller.restart()
    if args.command == "status":
        return controller.status()

    parser.print_help()
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
