"""Fireagent CLI — command-line interface for sandbox lifecycle management.

Usage:
    fireagent --help
    fireagent sandboxes create --image ubuntu:24.04 --vcpus 2 --memory 1024
    fireagent sandboxes ls
    fireagent sandboxes exec <id> --command "echo hello"
    fireagent sandboxes stop <id>
    fireagent sandboxes delete <id>
    fireagent images ls
    fireagent hosts ls
    fireagent config show
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any, TextIO

import click
import yaml

from fireagent import FireagentClient, __version__
from fireagent.exceptions import FireagentError, NotFoundError, SandboxFailedError, SandboxTimeoutError
from fireagent.models import SandboxStatus


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
DEFAULT_CONFIG_PATH = Path.home() / ".fireagent" / "config.yaml"
DEFAULT_CONFIG = {
    "api": {
        "base_url": "http://127.0.0.1:8000",
        "api_key": None,
        "timeout": 30,
        "retries": 3,
        "retry_delay": 0.5,
    },
    "cli": {"default_format": "table", "color": True},
    "sandbox": {
        "default_image": "ubuntu:24.04",
        "default_vcpus": 1,
        "default_memory_mib": 512,
        "default_disk_mib": 1024,
        "default_ttl_seconds": 3600,
    },
}


def load_config(path: Path | None = None) -> dict:
    cfg = DEFAULT_CONFIG.copy()
    config_path = path or DEFAULT_CONFIG_PATH
    if config_path.exists():
        with open(config_path) as f:
            user_cfg = yaml.safe_load(f) or {}
        _deep_merge(cfg, user_cfg)
    env_config = os.environ.get("FIREAGENT_CONFIG")
    if env_config and env_config != str(config_path):
        env_path = Path(env_config)
        if env_path.exists():
            with open(env_path) as f:
                env_cfg = yaml.safe_load(f) or {}
            _deep_merge(cfg, env_cfg)
    if os.environ.get("FIREAGENT_API_KEY"):
        cfg["api"]["api_key"] = os.environ["FIREAGENT_API_KEY"]
    if os.environ.get("FIREAGENT_BASE_URL"):
        cfg["api"]["base_url"] = os.environ["FIREAGENT_BASE_URL"]
    return cfg


def _deep_merge(base: dict, override: dict) -> None:
    for key, value in override.items():
        if key in base and isinstance(base[key], dict) and isinstance(value, dict):
            _deep_merge(base[key], value)
        else:
            base[key] = value


def save_config(cfg: dict, path: Path | None = None) -> None:
    config_path = path or DEFAULT_CONFIG_PATH
    config_path.parent.mkdir(parents=True, exist_ok=True)
    with open(config_path, "w") as f:
        yaml.dump(cfg, f, default_flow_style=False)


def build_client(cfg: dict) -> FireagentClient:
    api_cfg = cfg.get("api", {})
    return FireagentClient(
        base_url=api_cfg.get("base_url"),
        api_key=api_cfg.get("api_key"),
        timeout=api_cfg.get("timeout", 30),
        retries=api_cfg.get("retries", 3),
        retry_delay=api_cfg.get("retry_delay", 0.5),
    )


# ---------------------------------------------------------------------------
# Output formatting
# ---------------------------------------------------------------------------
def format_output(data: Any, fmt: str = "table", stream: TextIO | None = None) -> list[str]:
    """Format and print CLI output, returning the formatted lines.

    Lines are also echoed via click.echo when *stream* is None or when
    running in a click context.
    """
    lines = _emit_lines(data, fmt)
    for line in lines:
        if stream is None:
            click.echo(line)
        else:
            try:
                click.echo(line, file=stream, err=False)
            except (RuntimeError, TypeError):
                print(line, file=stream)
    return lines


def _emit_lines(data: Any, fmt: str = "table") -> list[str]:
    """Return formatted output as a list of strings."""
    lines: list[str] = []
    if fmt == "json":
        lines.append(json.dumps(data, indent=2, default=str))
    elif fmt == "yaml":
        lines.append(yaml.dump(data, default_flow_style=False).strip())
    elif fmt == "table":
        _table_lines(data, lines)
    else:
        lines.append(str(data))
    return lines


def _table_lines(data: Any, lines: list[str]) -> None:
    """Append table-formatted lines."""
    if isinstance(data, list):
        if not data:
            lines.append("(no results)")
            return
        keys = list(dict.fromkeys(k for d in data if isinstance(d, dict) for k in d))
        if not keys:
            for item in data:
                lines.append(str(item))
            return
        col_widths = {k: len(str(k)) for k in keys}
        for item in data:
            if isinstance(item, dict):
                for k in keys:
                    col_widths[k] = max(col_widths.get(k, 0), len(str(item.get(k, ""))))
        header = " | ".join(k.ljust(col_widths[k]) for k in keys)
        lines.append(header)
        lines.append("-" * len(header))
        for item in data:
            if isinstance(item, dict):
                row = " | ".join(str(item.get(k, "")).ljust(col_widths[k]) for k in keys)
                lines.append(row)
    elif isinstance(data, dict):
        max_key_len = max(len(str(k)) for k in data)
        for k, v in data.items():
            lines.append(f"{str(k).ljust(max_key_len)}  {v}")
    else:
        lines.append(str(data))


def _print_table(data: Any, stream: TextIO = sys.stdout) -> None:
    """Legacy: print table directly to stream."""
    lines: list[str] = []
    _table_lines(data, lines)
    for line in lines:
        print(line, file=stream)


# ---------------------------------------------------------------------------
# CLI Context
# ---------------------------------------------------------------------------
class Config:
    def __init__(self, cfg: dict, fmt: str) -> None:
        self.cfg = cfg
        self.fmt = fmt
        self.client = build_client(cfg)


# ---------------------------------------------------------------------------
# CLI Group
# ---------------------------------------------------------------------------
@click.group(context_settings={"help_option_names": ["-h", "--help"]})
@click.option("--config", type=click.Path(exists=True), help="Config file path")
@click.option("--format", "-f", type=click.Choice(["table", "json", "yaml"]), default=None, help="Output format")
@click.option("--base-url", envvar="FIREAGENT_BASE_URL", help="API base URL")
@click.option("--api-key", envvar="FIREAGENT_API_KEY", help="API key")
@click.option("--debug/--no-debug", default=False, help="Enable debug output")
@click.version_option(version=__version__, prog_name="fireagent")
@click.pass_context
def cli(ctx, config, format, base_url, api_key, debug):
    """Fireagent CLI — manage isolated microVM sandboxes for AI agents."""
    cfg = load_config(Path(config) if config else None)
    if base_url:
        cfg["api"]["base_url"] = base_url
    if api_key:
        cfg["api"]["api_key"] = api_key
    fmt = format or cfg.get("cli", {}).get("default_format", "table")
    ctx.obj = Config(cfg, fmt)
    if debug:
        import logging
        logging.basicConfig(level=logging.DEBUG)


# ---------------------------------------------------------------------------
# Config commands
# ---------------------------------------------------------------------------
@cli.group()
def config():
    """Manage CLI configuration."""


@config.command("show")
@click.pass_obj
def config_show(obj: Config):
    """Show current configuration."""
    format_output(obj.cfg, obj.fmt)


@config.command("init")
@click.option("--force", is_flag=True, help="Overwrite existing config")
def config_init(force):
    """Initialize default configuration."""
    if DEFAULT_CONFIG_PATH.exists() and not force:
        click.echo(f"Config already exists at {DEFAULT_CONFIG_PATH}")
        click.echo("Use --force to overwrite")
        return
    save_config(DEFAULT_CONFIG)
    click.echo(f"Config written to {DEFAULT_CONFIG_PATH}")


@config.command("set")
@click.argument("key")
@click.argument("value")
@click.pass_obj
def config_set(obj: Config, key: str, value: str):
    """Set a config value (dot-separated)."""
    cfg = obj.cfg
    parts = key.split(".")
    target = cfg
    for part in parts[:-1]:
        if part not in target:
            target[part] = {}
        target = target[part]
    if value.lower() == "true":
        value = True
    elif value.lower() == "false":
        value = False
    else:
        try:
            value = int(value)
        except ValueError:
            try:
                value = float(value)
            except ValueError:
                pass
    target[parts[-1]] = value
    save_config(cfg)
    click.echo(f"Set {key} = {value}")


# ---------------------------------------------------------------------------
# Sandbox commands
# ---------------------------------------------------------------------------
@cli.group()
def sandboxes():
    """Create, manage, and destroy sandboxes."""


@sandboxes.command("create")
@click.option("--image", default=None, help="Guest image name")
@click.option("--vcpus", type=int, default=None, help="Virtual CPU count")
@click.option("--memory", "--memory-mib", type=int, default=None, help="Memory in MiB")
@click.option("--disk", "--disk-mib", type=int, default=None, help="Disk in MiB")
@click.option("--ttl", "--ttl-seconds", type=int, default=None, help="TTL in seconds")
@click.option("--idle-timeout", type=int, default=None, help="Idle timeout in seconds")
@click.option("--label", "-l", multiple=True, help="Labels (key=value)")
@click.option("--network-rule", "-n", multiple=True,
              help="Network rule (action:protocol:dest:port e.g. allow:tcp:github.com:443)")
@click.option("--wait/--no-wait", default=True, help="Wait for ready state")
@click.option("--timeout", "wait_timeout", type=int, default=120, help="Wait timeout")
@click.pass_obj
def sandbox_create(obj: Config, **kw):
    """Create a new sandbox."""
    scfg = obj.cfg.get("sandbox", {})
    body = {
        "image": kw["image"] or scfg.get("default_image", "ubuntu:24.04"),
        "vcpus": kw["vcpus"] or scfg.get("default_vcpus", 1),
        "memory_mib": kw["memory"] or scfg.get("default_memory_mib", 512),
        "disk_mib": kw["disk"] or scfg.get("default_disk_mib", 1024),
    }
    if kw["ttl"]:
        body["ttl_seconds"] = kw["ttl"]
    if kw["idle_timeout"]:
        body["idle_timeout_seconds"] = kw["idle_timeout"]
    if kw["label"]:
        body["labels"] = {}
        for label in kw["label"]:
            if "=" in label:
                k, v = label.split("=", 1)
                body["labels"][k] = v
    if kw["network_rule"]:
        rules = []
        for rule in kw["network_rule"]:
            parts = rule.split(":", 3)
            if len(parts) == 4:
                rules.append({"action": parts[0], "protocol": parts[1], "destination": parts[2], "port": int(parts[3])})
        if rules:
            body["network_policy"] = {"rules": rules}
    try:
        sb = obj.client.create(**body)
        if kw["wait"]:
            click.echo(f"Creating sandbox {sb.id}...")
            try:
                sb.wait_for("ready", timeout_seconds=kw["wait_timeout"])
            except SandboxTimeoutError:
                click.echo(f"Warning: sandbox {sb.id} did not reach ready state", err=True)
        format_output(_status_to_dict(sb.status()), obj.fmt)
    except FireagentError as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)


@sandboxes.command("ls")
@click.option("--state", help="Filter by state (ready, running, stopped, etc.)")
@click.option("--limit", type=int, default=50, help="Max results")
@click.pass_obj
def sandbox_list(obj: Config, state, limit):
    """List sandboxes."""
    try:
        sandboxes = obj.client.list()
        if state:
            sandboxes = [s for s in sandboxes if s.status().state == state]
        if limit:
            sandboxes = sandboxes[:limit]
        data = [_status_to_dict(s.status()) for s in sandboxes]
        format_output(data, obj.fmt)
    except FireagentError as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)


@sandboxes.command("get")
@click.argument("sandbox_id")
@click.pass_obj
def sandbox_get(obj: Config, sandbox_id):
    """Get sandbox details."""
    try:
        status = obj.client._get_sandbox(sandbox_id)
        format_output(_status_to_dict(status), obj.fmt)
    except NotFoundError:
        click.echo(f"Sandbox {sandbox_id} not found", err=True)
        sys.exit(1)
    except FireagentError as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)


@sandboxes.command("exec")
@click.argument("sandbox_id")
@click.option("--command", "-c", required=True, help="Command to run")
@click.option("--workdir", "-w", help="Working directory")
@click.option("--env", "-e", multiple=True, help="Environment variable (KEY=VALUE)")
@click.option("--timeout", "exec_timeout", type=int, default=300, help="Execution timeout")
@click.option("--stdin", help="Standard input")
@click.pass_obj
def sandbox_exec(obj: Config, sandbox_id, **kw):
    """Execute a command in a sandbox."""
    env_dict = None
    if kw["env"]:
        env_dict = {}
        for e in kw["env"]:
            if "=" in e:
                k, v = e.split("=", 1)
                env_dict[k] = v
    try:
        result = obj.client._exec(
            sandbox_id=sandbox_id, command=kw["command"],
            working_dir=kw["workdir"], environment=env_dict,
            execution_timeout_seconds=kw["exec_timeout"], stdin=kw["stdin"],
        )
        data = {
            "stdout": result.stdout, "stderr": result.stderr,
            "exit_code": result.exit_code, "timed_out": result.timed_out,
            "oom_killed": result.oom_killed,
            "start_time": str(result.start_time) if result.start_time else None,
            "finish_time": str(result.finish_time) if result.finish_time else None,
        }
        format_output(data, obj.fmt)
        if result.exit_code != 0:
            sys.exit(result.exit_code)
    except NotFoundError:
        click.echo(f"Sandbox {sandbox_id} not found", err=True)
        sys.exit(1)
    except FireagentError as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)


@sandboxes.command("stop")
@click.argument("sandbox_id")
@click.option("--wait/--no-wait", default=True, help="Wait for stopped state")
@click.option("--timeout", "wait_timeout", type=int, default=30, help="Wait timeout")
@click.pass_obj
def sandbox_stop(obj: Config, sandbox_id, **kw):
    """Stop a sandbox."""
    try:
        sb = obj.client.get(sandbox_id)
        sb.stop()
        if kw["wait"]:
            try:
                sb.wait_for("stopped", timeout_seconds=kw["wait_timeout"])
            except SandboxTimeoutError:
                click.echo("Warning: sandbox did not reach stopped state", err=True)
        click.echo(f"Sandbox {sandbox_id} stopped")
    except NotFoundError:
        click.echo(f"Sandbox {sandbox_id} not found", err=True)
        sys.exit(1)
    except FireagentError as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)


@sandboxes.command("delete")
@click.argument("sandbox_id")
@click.option("--yes", "-y", is_flag=True, help="Skip confirmation")
@click.pass_obj
def sandbox_delete(obj: Config, sandbox_id, yes):
    """Delete a sandbox and its writable state."""
    if not yes:
        click.confirm(f"Delete sandbox {sandbox_id}?", abort=True)
    try:
        sb = obj.client.get(sandbox_id)
        sb.delete()
        click.echo(f"Sandbox {sandbox_id} deleted")
    except NotFoundError:
        click.echo(f"Sandbox {sandbox_id} not found", err=True)
        sys.exit(1)
    except FireagentError as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)


@sandboxes.command("wait")
@click.argument("sandbox_id")
@click.argument("state", default="ready")
@click.option("--timeout", type=int, default=120, help="Wait timeout")
@click.pass_obj
def sandbox_wait(obj: Config, sandbox_id, state, timeout):
    """Wait for a sandbox to reach a given state."""
    try:
        sb = obj.client.get(sandbox_id)
        status = sb.wait_for(state, timeout_seconds=timeout)
        format_output(_status_to_dict(status), obj.fmt)
    except SandboxTimeoutError:
        click.echo(f"Sandbox {sandbox_id} did not reach {state!r} in {timeout}s", err=True)
        sys.exit(1)
    except SandboxFailedError as e:
        click.echo(f"Sandbox {sandbox_id} failed: {e}", err=True)
        sys.exit(1)
    except FireagentError as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)


# ---------------------------------------------------------------------------
# Image commands
# ---------------------------------------------------------------------------
@cli.group()
def images():
    """Manage guest images."""


@images.command("ls")
@click.pass_obj
def image_list(obj: Config):
    """List available guest images."""
    click.echo("Use 'fireagent images build' for image management.")
    click.echo("See docs/architecture/guest-image.md for build instructions.")


# ---------------------------------------------------------------------------
# Host commands
# ---------------------------------------------------------------------------
@cli.group()
def hosts():
    """Manage worker hosts."""


@hosts.command("ls")
@click.pass_obj
def host_list(obj: Config):
    """List registered hosts."""
    click.echo("Host management: see 'fireagent hosts register' (coming soon).")


# ---------------------------------------------------------------------------
# Utility
# ---------------------------------------------------------------------------
def _status_to_dict(status: SandboxStatus) -> dict:
    return {
        "id": status.sandbox_id,
        "state": status.state,
        "image": status.image,
        "vcpus": status.vcpus,
        "memory_mib": status.memory_mib,
        "disk_mib": status.disk_mib,
        "host": status.host,
        "created_at": str(status.created_at) if status.created_at else None,
        "failure_reason": status.failure_reason,
    }


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------
def main() -> None:
    cli()


if __name__ == "__main__":
    main()