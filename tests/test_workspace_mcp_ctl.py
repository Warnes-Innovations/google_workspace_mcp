import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

from workspace_mcp_ctl import WorkspaceMCPController, parse_config, WorkspaceMCPConfig


def test_parse_config_minimal(tmp_path: Path):
    config_path = tmp_path / "workspace-mcp-config.toml"
    config_path.write_text(
        f"""command = [\"{sys.executable}\", \"-m\", \"http.server\"]\nargs = [\"8000\"]\nworking_dir = \".\"\npid_file = \"workspace-mcp.pid\"\nlog_file = \"workspace-mcp.log\"\n"""
    )

    config = parse_config(config_path)

    assert config.command == [sys.executable, "-m", "http.server"]
    assert config.args == ["8000"]
    assert config.pid_file.name == "workspace-mcp.pid"
    assert config.log_file.name == "workspace-mcp.log"
    assert config.start_timeout == 10


def test_parse_config_unknown_field(tmp_path: Path):
    config_path = tmp_path / "workspace-mcp-config.toml"
    config_path.write_text("command = [\"python\"]\nunknown = true\n")

    with pytest.raises(ValueError, match="Unknown config fields"):
        parse_config(config_path)


def test_status_start_stop_cycle(tmp_path: Path):
    config_path = tmp_path / "workspace-mcp-config.toml"
    pid_file = tmp_path / "workspace.pid"
    log_file = tmp_path / "workspace.log"
    config_path.write_text(
        f"""command = [\"{sys.executable}\", \"-c\", \"import time; time.sleep(30)\"]\nargs = []\nworking_dir = \".\"\npid_file = \"workspace.pid\"\nlog_file = \"workspace.log\"\nstart_timeout = 2\n"""
    )

    config = parse_config(config_path)
    controller = WorkspaceMCPController(config)

    assert controller.status() == 1
    assert controller.start() == 0
    assert controller.status() == 0
    assert pid_file.exists()

    stop_code = controller.stop()
    assert stop_code == 0
    assert controller.status() == 1


def test_check_config_invalid_env(tmp_path: Path):
    config_path = tmp_path / "workspace-mcp-config.toml"
    config_path.write_text(
        """command = [\"python\"]\nargs = []\nenv = { TEST = 5 }\n"""
    )

    with pytest.raises(ValueError, match="'env' must be a table of string values"):
        parse_config(config_path)
