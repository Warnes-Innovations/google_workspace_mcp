#!/usr/bin/env python3
"""Manage the Workspace-MCP server process using a configuration file."""

from __future__ import annotations

import argparse
import os
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

DEFAULT_CONFIG_PATH = "workspace-mcp-config.toml"
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

    args = parser.parse_args()
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
