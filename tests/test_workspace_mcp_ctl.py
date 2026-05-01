import argparse
import os
import subprocess
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from mcp_ctl import (
    WorkspaceMCPController,
    install_command,
    install_workspace_mcp_skill,
    parse_config,
    WorkspaceMCPConfig,
)


def test_parse_config_minimal(tmp_path: Path):
    config_path = tmp_path / "mcp-config.toml"
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
    config_path = tmp_path / "mcp-config.toml"
    config_path.write_text("command = [\"python\"]\nunknown = true\n")

    with pytest.raises(ValueError, match="Unknown config fields"):
        parse_config(config_path)


def test_status_start_stop_cycle(tmp_path: Path):
    config_path = tmp_path / "mcp-config.toml"
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
    config_path = tmp_path / "mcp-config.toml"
    config_path.write_text(
        """command = [\"python\"]\nargs = []\nenv = { TEST = 5 }\n"""
    )

    with pytest.raises(ValueError, match="'env' must be a table of string values"):
        parse_config(config_path)


def test_parse_config_command_string_and_env_file(tmp_path: Path):
    config_path = tmp_path / "mcp-config.toml"
    env_file = tmp_path / ".env"
    env_file.write_text('TEST_ENV="hello"\n# comment\nFOO=bar\n')
    config_path.write_text(
        f"""command = \"{sys.executable}\"\nargs = [\"-c\", \"print(\\\"x\\\")\"]\nworking_dir = \".\"\npid_file = \"workspace.pid\"\nlog_file = \"workspace.log\"\nenv_file = \"{env_file.name}\"\nenv = {{ TEST2 = \"world\" }}\nstart_timeout = 3\n"""
    )

    config = parse_config(config_path)

    assert config.command == [sys.executable]
    assert config.env_file.name == env_file.name
    assert config.env == {"TEST2": "world"}
    controller = WorkspaceMCPController(config)
    assert controller._load_env_file(env_file) == {"TEST_ENV": "hello", "FOO": "bar"}
    merged_env = controller._build_env()
    assert merged_env["TEST2"] == "world"
    assert merged_env["TEST_ENV"] == "hello"


def test_parse_config_invalid_start_timeout(tmp_path: Path):
    config_path = tmp_path / "mcp-config.toml"
    config_path.write_text(
        """command = [\"python\"]\nargs = []\nstart_timeout = 0\n"""
    )

    with pytest.raises(ValueError, match="'start_timeout' must be a positive integer"):
        parse_config(config_path)


def test_restart_reuses_config(tmp_path: Path):
    config_path = tmp_path / "mcp-config.toml"
    pid_file = tmp_path / "workspace.pid"
    log_file = tmp_path / "workspace.log"
    config_path.write_text(
        f"""command = [\"{sys.executable}\", \"-c\", \"import time; time.sleep(30)\"]\nargs = []\nworking_dir = \".\"\npid_file = \"workspace.pid\"\nlog_file = \"workspace.log\"\nstart_timeout = 2\n"""
    )

    config = parse_config(config_path)
    controller = WorkspaceMCPController(config)

    assert controller.start() == 0
    assert pid_file.exists()
    assert controller.restart() == 0
    assert controller.stop() == 0
    assert controller.status() == 1


def test_start_removes_stale_pid(tmp_path: Path):
    config_path = tmp_path / "mcp-config.toml"
    pid_file = tmp_path / "workspace.pid"
    log_file = tmp_path / "workspace.log"
    config_path.write_text(
        f"""command = [\"{sys.executable}\", \"-c\", \"import time; time.sleep(30)\"]\nargs = []\nworking_dir = \".\"\npid_file = \"workspace.pid\"\nlog_file = \"workspace.log\"\nstart_timeout = 2\n"""
    )

    pid_file.write_text("999999")

    config = parse_config(config_path)
    controller = WorkspaceMCPController(config)

    assert controller.start() == 0
    assert pid_file.exists()
    assert controller.stop() == 0


def test_main_check_config_outputs_summary(tmp_path: Path, monkeypatch, capsys: pytest.CaptureFixture):
    import mcp_ctl

    config_path = tmp_path / "mcp-config.toml"
    config_path.write_text(
        f"""command = [\"{sys.executable}\", \"-m\", \"http.server\"]\nargs = [\"8000\"]\nworking_dir = \".\"\npid_file = \"workspace.pid\"\nlog_file = \"workspace.log\"\nstart_timeout = 2\n"""
    )

    monkeypatch.setattr(sys, "argv", ["mcp_ctl.py", "--config", str(config_path), "check-config"])
    assert mcp_ctl.main() == 0
    captured = capsys.readouterr()
    assert "Workspace-MCP management configuration:" in captured.out
    assert "command:" in captured.out


def test_install_workspace_mcp_skill_symlink(tmp_path: Path):
    source = tmp_path / "skills" / "managing-google-workspace"
    source.mkdir(parents=True)
    (source / "SKILL.md").write_text("skill")

    target = tmp_path / "install" / "managing-google-workspace"
    status = install_workspace_mcp_skill(source, target)

    assert status == 0
    assert target.is_symlink()
    assert target.resolve() == source.resolve()
    assert (target / "SKILL.md").exists()


def test_install_wordspace_mcp_skill_copy_on_windows(tmp_path: Path, monkeypatch):
    source = tmp_path / "skills" / "managing-google-workspace"
    source.mkdir(parents=True)
    (source / "SKILL.md").write_text("skill")

    monkeypatch.setattr(os, "name", "nt")
    target = tmp_path / "install" / "managing-google-workspace"
    status = install_workspace_mcp_skill(source, target)

    assert status == 0
    assert target.is_dir()
    assert (target / "SKILL.md").exists()


def test_install_command_installs_package_and_skill(tmp_path: Path, monkeypatch):
    root = tmp_path / "repo"
    skill_source = root / "skills" / "managing-google-workspace"
    skill_source.mkdir(parents=True)
    (skill_source / "SKILL.md").write_text("skill")

    target = tmp_path / "home" / ".claude" / "skills" / "managing-google-workspace"
    monkeypatch.setattr("mcp_ctl.get_repo_root", lambda: root)

    def fake_run(cmd, check):
        assert cmd[:3] == [sys.executable, "-m", "pip"]
        assert "install" in cmd
        assert "--editable" in cmd
        return subprocess.CompletedProcess(cmd, 0)

    monkeypatch.setattr("mcp_ctl.subprocess.run", fake_run)

    args = SimpleNamespace(
        command="install",
        config=Path("mcp-config.toml"),
        no_server=False,
        no_skills=False,
        clients="claude",
        skill_dir=target,
        copy_skills=False,
        force=True,
    )

    status = install_command(args)
    assert status == 0
    assert target.exists()
    assert (target / "SKILL.md").exists()


def test_install_command_prompts_for_clients(tmp_path: Path, monkeypatch):
    import mcp_ctl

    root = tmp_path / "repo"
    skill_source = root / "skills" / "managing-google-workspace"
    skill_source.mkdir(parents=True)
    (skill_source / "SKILL.md").write_text("skill")

    home = tmp_path / "home"
    import mcp_ctl

    monkeypatch.setattr("mcp_ctl.get_repo_root", lambda: root)
    monkeypatch.setattr(mcp_ctl.sys, "stdin", SimpleNamespace(isatty=lambda: True), raising=False)

    def fake_run(cmd, check):
        assert cmd[:3] == [sys.executable, "-m", "pip"]
        return subprocess.CompletedProcess(cmd, 0)

    monkeypatch.setattr("mcp_ctl.subprocess.run", fake_run)
    monkeypatch.setattr("builtins.input", lambda prompt="": "1,4")
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))

    args = SimpleNamespace(
        command="install",
        config=Path("mcp-config.toml"),
        no_server=False,
        no_skills=False,
        clients=None,
        skill_dir=None,
        copy_skills=False,
        force=True,
    )

    status = install_command(args)
    assert status == 0
    assert (home / ".claude" / "skills" / "managing-google-workspace" / "SKILL.md").exists()
    assert (home / ".clive" / "skills" / "managing-google-workspace" / "SKILL.md").exists()


def test_install_command_installs_multiple_clients(tmp_path: Path, monkeypatch):
    root = tmp_path / "repo"
    skill_source = root / "skills" / "managing-google-workspace"
    skill_source.mkdir(parents=True)
    (skill_source / "SKILL.md").write_text("skill")

    home = tmp_path / "home"
    monkeypatch.setattr("mcp_ctl.get_repo_root", lambda: root)
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))

    def fake_run(cmd, check):
        assert cmd[:3] == [sys.executable, "-m", "pip"]
        return subprocess.CompletedProcess(cmd, 0)

    monkeypatch.setattr("mcp_ctl.subprocess.run", fake_run)

    args = SimpleNamespace(
        command="install",
        config=Path("mcp-config.toml"),
        no_server=False,
        no_skills=False,
        clients="claude,copilot,codex,clive",
        skill_dir=None,
        copy_skills=False,
        force=True,
    )

    status = install_command(args)
    assert status == 0
    assert (home / ".claude" / "skills" / "managing-google-workspace" / "SKILL.md").exists()
    assert (home / ".copilot" / "skills" / "managing-google-workspace" / "SKILL.md").exists()
    assert (home / ".codex" / "skills" / "managing-google-workspace" / "SKILL.md").exists()
    assert (home / ".clive" / "skills" / "managing-google-workspace" / "SKILL.md").exists()
