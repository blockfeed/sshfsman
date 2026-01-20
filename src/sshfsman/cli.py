#!/usr/bin/env python3
"""
sshfsman: CLI-first sshfs mount manager

Design constraints:
- Deterministic mount detection: a path is "mounted" iff findmnt -T <path> reports FSTYPE=fuse.sshfs
- No heuristic checks (directory existence, mountpoint(1), /proc/mounts parsing)
- Manage mounts under a configurable mount_root (default: /mnt/sshfs)
- XDG config: ~/.config/sshfsman/config.toml
- Shortcuts persist mount invocation parameters (port/identity/options/readonly/no_reconnect_defaults)
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import subprocess
import textwrap
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

try:
    import tomllib  # py3.11+
except Exception:  # pragma: no cover
    tomllib = None  # type: ignore


APP_NAME = "sshfsman"
XDG_CONFIG_HOME = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
DEFAULT_CONFIG_PATH = XDG_CONFIG_HOME / APP_NAME / "config.toml"

DEFAULT_MOUNT_ROOT = Path("/mnt/sshfs")
DEFAULT_SUBNET = ""  # empty means disabled


class SshfsmanError(RuntimeError):
    pass


@dataclass
class Defaults:
    mount_root: Path = DEFAULT_MOUNT_ROOT
    default_subnet: str = DEFAULT_SUBNET  # e.g. "192.0.2"


@dataclass
class Shortcut:
    name: str
    remote: str
    mount_dir: Optional[str] = None

    # Saved invocation parameters (optional)
    port: Optional[int] = None
    identity: Optional[str] = None
    options: List[str] = None  # sshfs -o values (strings)
    readonly: Optional[bool] = None
    no_reconnect_defaults: Optional[bool] = None

    def __post_init__(self) -> None:
        if self.options is None:
            self.options = []


def _die(msg: str, code: int = 2) -> None:
    print(f"{APP_NAME}: {msg}", file=sys.stderr)
    raise SystemExit(code)


def _run(cmd: List[str], *, check: bool = False, capture: bool = False) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(
            cmd,
            check=check,
            text=True,
            capture_output=capture,
        )
    except FileNotFoundError:
        _die(f"missing dependency: {cmd[0]!r} not found in PATH")


def _load_config(config_path: Path) -> Tuple[Defaults, Dict[str, Shortcut]]:
    defaults = Defaults()
    shortcuts: Dict[str, Shortcut] = {}

    if not config_path.exists():
        return defaults, shortcuts

    if tomllib is None:
        _die("Python tomllib not available (requires Python 3.11+)")

    try:
        data = tomllib.loads(config_path.read_text(encoding="utf-8"))
    except Exception as e:
        _die(f"failed to read config {config_path}: {e}")

    cfg = data.get("config", {}) if isinstance(data, dict) else {}
    if isinstance(cfg, dict):
        mount_root = cfg.get("mount_root")
        if isinstance(mount_root, str) and mount_root.strip():
            defaults.mount_root = Path(mount_root).expanduser()
        subnet = cfg.get("default_subnet")
        if isinstance(subnet, str):
            defaults.default_subnet = subnet.strip()

    sc = data.get("shortcuts", {}) if isinstance(data, dict) else {}
    if isinstance(sc, dict):
        for name, val in sc.items():
            if not isinstance(name, str):
                continue
            if not isinstance(val, dict):
                continue
            remote = val.get("remote")
            if not isinstance(remote, str) or not remote.strip():
                continue
            mount_dir = val.get("mount_dir")
            if mount_dir is not None and not isinstance(mount_dir, str):
                mount_dir = None

            s = Shortcut(
                name=name,
                remote=remote.strip(),
                mount_dir=mount_dir.strip() if isinstance(mount_dir, str) and mount_dir.strip() else None,
                port=val.get("port") if isinstance(val.get("port"), int) else None,
                identity=val.get("identity") if isinstance(val.get("identity"), str) else None,
                options=list(val.get("options")) if isinstance(val.get("options"), list) else [],
                readonly=val.get("readonly") if isinstance(val.get("readonly"), bool) else None,
                no_reconnect_defaults=val.get("no_reconnect_defaults") if isinstance(val.get("no_reconnect_defaults"), bool) else None,
            )
            shortcuts[name] = s

    return defaults, shortcuts


def _write_config(config_path: Path, defaults: Defaults, shortcuts: Dict[str, Shortcut]) -> None:
    """
    Minimal TOML writer to avoid new dependencies.
    """
    config_path.parent.mkdir(parents=True, exist_ok=True)

    def toml_escape(s: str) -> str:
        return s.replace("\\", "\\\\").replace('"', '\\"')

    lines: List[str] = []
    lines.append("[config]")
    lines.append(f'mount_root = "{toml_escape(str(defaults.mount_root))}"')
    if defaults.default_subnet:
        lines.append(f'default_subnet = "{toml_escape(defaults.default_subnet)}"')
    lines.append("")
    lines.append("[shortcuts]")
    lines.append("")

    for name in sorted(shortcuts.keys()):
        s = shortcuts[name]
        lines.append(f'[shortcuts."{toml_escape(name)}"]')
        lines.append(f'remote = "{toml_escape(s.remote)}"')
        if s.mount_dir:
            lines.append(f'mount_dir = "{toml_escape(s.mount_dir)}"')

        if s.port is not None:
            lines.append(f"port = {int(s.port)}")
        if s.identity:
            lines.append(f'identity = "{toml_escape(s.identity)}"')
        if s.options:
            lines.append("options = [")
            for opt in s.options:
                lines.append(f'  "{toml_escape(str(opt))}",')
            lines.append("]")
        if s.readonly is not None:
            lines.append(f"readonly = {'true' if s.readonly else 'false'}")
        if s.no_reconnect_defaults is not None:
            lines.append(f"no_reconnect_defaults = {'true' if s.no_reconnect_defaults else 'false'}")

        lines.append("")

    config_path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


def _findmnt_fstype_for_path(path: Path) -> Optional[str]:
    cp = _run(["findmnt", "-T", str(path), "-n", "-o", "FSTYPE"], capture=True)
    if cp.returncode != 0:
        return None
    out = (cp.stdout or "").strip()
    return out or None


def is_sshfs_mounted(path: Path) -> bool:
    fstype = _findmnt_fstype_for_path(path)
    return fstype == "fuse.sshfs"


def _list_fuse_sshfs_mounts() -> List[Dict[str, str]]:
    cp = _run(["findmnt", "-t", "fuse.sshfs", "-n", "-o", "TARGET,SOURCE,FSTYPE"], capture=True)
    if cp.returncode != 0:
        return []
    mounts: List[Dict[str, str]] = []
    for line in (cp.stdout or "").splitlines():
        parts = line.split()
        if len(parts) < 3:
            continue
        mounts.append({"TARGET": parts[0], "SOURCE": parts[1], "FSTYPE": parts[2]})
    return mounts


def _filter_mounts_under_root(mounts: List[Dict[str, str]], mount_root: Path) -> List[Dict[str, str]]:
    root = str(mount_root.resolve())
    out: List[Dict[str, str]] = []
    for m in mounts:
        tgt = m.get("TARGET", "")
        if tgt == root or tgt.startswith(root.rstrip("/") + "/"):
            out.append(m)
    return out


def _safe_rmdir_empty_under_root(path: Path, mount_root: Path) -> None:
    try:
        path = path.resolve()
        mount_root = mount_root.resolve()
    except Exception:
        return

    if path == mount_root:
        return
    if not str(path).startswith(str(mount_root).rstrip("/") + "/"):
        return
    if is_sshfs_mounted(path):
        return
    try:
        path.rmdir()
    except OSError:
        return


def _resolve_host_with_optional_octet(remote: str, default_subnet: str, octet: Optional[str]) -> str:
    if octet is None:
        return remote

    if not default_subnet:
        _die("numeric host override provided but config.default_subnet is not set")

    if not octet.isdigit():
        _die(f"invalid host override {octet!r} (expected 1..254)")

    n = int(octet)
    if n < 1 or n > 254:
        _die(f"invalid host override {octet!r} (expected 1..254)")

    host = f"{default_subnet}.{n}"
    if ":" not in remote:
        return remote
    lhs, rhs = remote.split(":", 1)
    if "@" in lhs:
        user, _oldhost = lhs.split("@", 1)
        return f"{user}@{host}:{rhs}"
    return f"{host}:{rhs}"


def _build_sshfs_cmd(
    remote: str,
    target: Path,
    *,
    port: Optional[int],
    identity: Optional[str],
    options: List[str],
    readonly: bool,
    no_reconnect_defaults: bool,
) -> List[str]:
    cmd: List[str] = ["sshfs", remote, str(target)]

    if not no_reconnect_defaults:
        cmd += ["-o", "reconnect", "-o", "ServerAliveInterval=15", "-o", "ServerAliveCountMax=3"]

    if readonly:
        cmd += ["-o", "ro"]

    for opt in options:
        cmd += ["-o", opt]

    if port is not None:
        cmd += ["-p", str(int(port))]

    if identity:
        cmd += ["-o", f"IdentityFile={identity}"]

    return cmd


def _default_mount_dir_from_remote(remote: str) -> str:
    try:
        after = remote.split(":", 1)[1]
        return Path(after.rstrip("/")).name or "sshfs"
    except Exception:
        return "sshfs"


def _mount(
    defaults: Defaults,
    *,
    remote: str,
    mount_dir: Optional[str],
    port: Optional[int],
    identity: Optional[str],
    options: List[str],
    readonly: bool,
    no_reconnect_defaults: bool,
) -> Path:
    mount_root = defaults.mount_root
    mount_root.mkdir(parents=True, exist_ok=True)

    if not mount_dir:
        mount_dir = _default_mount_dir_from_remote(remote)

    target = (mount_root / mount_dir).resolve()

    if is_sshfs_mounted(target):
        _die(f"already mounted: {target}")

    target.mkdir(parents=True, exist_ok=True)

    cmd = _build_sshfs_cmd(
        remote,
        target,
        port=port,
        identity=identity,
        options=options,
        readonly=readonly,
        no_reconnect_defaults=no_reconnect_defaults,
    )

    cp = _run(cmd)
    if cp.returncode != 0:
        _die(f"sshfs mount failed: {' '.join(cmd)}")

    return target


def _unmount_path(path: Path, mount_root: Path) -> None:
    if not is_sshfs_mounted(path):
        return

    cp = _run(["fusermount3", "-u", str(path)])
    if cp.returncode != 0:
        cp2 = _run(["fusermount", "-u", str(path)])
        if cp2.returncode != 0:
            _die(f"failed to unmount {path}")

    _safe_rmdir_empty_under_root(path, mount_root)


def _cmd_list_mounts(defaults: Defaults, args: argparse.Namespace) -> None:
    mounts = _list_fuse_sshfs_mounts()
    if not args.all:
        mounts = _filter_mounts_under_root(mounts, defaults.mount_root)

    if args.json:
        print(json.dumps(mounts, indent=2, sort_keys=True))
        return

    for m in mounts:
        print(f'{m["SOURCE"]}\t{m["TARGET"]}')


def _cmd_list_shortcuts(shortcuts: Dict[str, Shortcut], args: argparse.Namespace) -> None:
    items = []
    for name in sorted(shortcuts.keys()):
        s = shortcuts[name]
        items.append(
            {
                "name": name,
                "remote": s.remote,
                "mount_dir": s.mount_dir,
                "port": s.port,
                "identity": s.identity,
                "options": list(s.options),
                "readonly": s.readonly,
                "no_reconnect_defaults": s.no_reconnect_defaults,
            }
        )

    if args.json:
        print(json.dumps(items, indent=2, sort_keys=True))
        return

    for it in items:
        md = it.get("mount_dir") or ""
        print(f'{it["name"]}\t{it["remote"]}\t{md}')


def _cmd_create_shortcut(
    config_path: Path,
    defaults: Defaults,
    shortcuts: Dict[str, Shortcut],
    args: argparse.Namespace,
) -> None:
    sc = Shortcut(
        name=args.name,
        remote=args.remote.strip(),
        mount_dir=args.mount_dir,
        port=args.port,
        identity=args.identity,
        options=list(args.options or []),
        readonly=bool(args.readonly),
        no_reconnect_defaults=bool(args.no_reconnect_defaults),
    )
    shortcuts[args.name] = sc
    _write_config(config_path, defaults, shortcuts)


def _cmd_delete_shortcut(
    config_path: Path,
    defaults: Defaults,
    shortcuts: Dict[str, Shortcut],
    args: argparse.Namespace,
) -> None:
    if args.name in shortcuts:
        shortcuts.pop(args.name)
        _write_config(config_path, defaults, shortcuts)


def _cmd_set_default_subnet(
    config_path: Path,
    defaults: Defaults,
    shortcuts: Dict[str, Shortcut],
    args: argparse.Namespace,
) -> None:
    subnet = args.subnet.strip()
    if subnet:
        parts = subnet.split(".")
        if len(parts) != 3 or any((not p.isdigit() or int(p) < 0 or int(p) > 255) for p in parts):
            _die("default_subnet must be three octets, e.g. 192.0.2")
    defaults.default_subnet = subnet
    _write_config(config_path, defaults, shortcuts)


def _cmd_status(defaults: Defaults, shortcuts: Dict[str, Shortcut], args: argparse.Namespace) -> None:
    if args.path:
        p = Path(args.path)
        print("mounted" if is_sshfs_mounted(p) else "not-mounted")
        return

    if args.shortcut:
        s = shortcuts.get(args.shortcut)
        if not s:
            _die(f"unknown shortcut: {args.shortcut}")
        target = defaults.mount_root / (s.mount_dir or _default_mount_dir_from_remote(s.remote))
        print("mounted" if is_sshfs_mounted(target) else "not-mounted")
        return

    for name in sorted(shortcuts.keys()):
        s = shortcuts[name]
        target = defaults.mount_root / (s.mount_dir or _default_mount_dir_from_remote(s.remote))
        state = "mounted" if is_sshfs_mounted(target) else "not-mounted"
        print(f"{name}\t{state}\t{target}")


def _cmd_mount(
    config_path: Path,
    defaults: Defaults,
    shortcuts: Dict[str, Shortcut],
    args: argparse.Namespace,
) -> None:
    if args.remote:
        remote = args.remote.strip()

        # Mount directory selection (remote mounts):
        # - If --mount-dir is provided, use it.
        # - If --create-shortcut NAME is provided, default mount_dir to NAME (prevents collisions).
        # - Otherwise, derive from the remote path leaf.
        if args.mount_dir:
            mount_dir_used = args.mount_dir
        elif args.create_shortcut:
            mount_dir_used = args.create_shortcut
        else:
            mount_dir_used = None  # _mount will derive from remote path leaf

        target = _mount(
            defaults,
            remote=remote,
            mount_dir=mount_dir_used,
            port=args.port,
            identity=args.identity,
            options=list(args.options or []),
            readonly=bool(args.readonly),
            no_reconnect_defaults=bool(args.no_reconnect_defaults),
        )

        if args.create_shortcut:
            name = args.create_shortcut

            # Prevent two different shortcuts from silently sharing the same mount_dir.
            # Use --mount-dir to select a different target directory when needed.
            if mount_dir_used:
                for other_name, other_sc in shortcuts.items():
                    if other_name == name:
                        continue
                    if other_sc.mount_dir == mount_dir_used:
                        _die(
                            f"mount_dir {mount_dir_used!r} already used by shortcut {other_name!r}; "
                            "choose --mount-dir or a different shortcut name"
                        )

            shortcuts[name] = Shortcut(
                name=name,
                remote=remote,
                mount_dir=mount_dir_used or target.name,
                port=args.port,
                identity=args.identity,
                options=list(args.options or []),
                readonly=bool(args.readonly),
                no_reconnect_defaults=bool(args.no_reconnect_defaults),
            )
            _write_config(config_path, defaults, shortcuts)

        print(str(target))
        return

    shortcut_name = args.shortcut_name or args.shortcut
    if not shortcut_name:
        _die("mount requires either --remote or a shortcut name (sshfsman mount <name> [octet])")

    sc = shortcuts.get(shortcut_name)
    if not sc:
        _die(f"unknown shortcut: {shortcut_name}")

    remote = _resolve_host_with_optional_octet(sc.remote, defaults.default_subnet, args.octet)

    port = args.port if args.port is not None else sc.port
    identity = args.identity if args.identity is not None else sc.identity
    readonly = bool(args.readonly) if args.readonly else bool(sc.readonly) if sc.readonly is not None else False
    no_reconnect_defaults = bool(args.no_reconnect_defaults) if args.no_reconnect_defaults else bool(sc.no_reconnect_defaults) if sc.no_reconnect_defaults is not None else False
    options = list(sc.options or [])
    if args.options:
        options.extend(list(args.options))

    mount_dir = args.mount_dir if args.mount_dir is not None else sc.mount_dir

    target = _mount(
        defaults,
        remote=remote,
        mount_dir=mount_dir,
        port=port,
        identity=identity,
        options=options,
        readonly=readonly,
        no_reconnect_defaults=no_reconnect_defaults,
    )
    print(str(target))


def _cmd_unmount(defaults: Defaults, shortcuts: Dict[str, Shortcut], args: argparse.Namespace) -> None:
    mount_root = defaults.mount_root

    if args.path:
        _unmount_path(Path(args.path), mount_root)
        return

    if args.shortcut:
        s = shortcuts.get(args.shortcut)
        if not s:
            _die(f"unknown shortcut: {args.shortcut}")
        target = mount_root / (s.mount_dir or _default_mount_dir_from_remote(s.remote))
        _unmount_path(target, mount_root)
        return

    _die("unmount requires either --path or --shortcut")


def _cmd_unmount_all(defaults: Defaults, args: argparse.Namespace) -> None:
    mounts = _list_fuse_sshfs_mounts()
    if not args.all:
        mounts = _filter_mounts_under_root(mounts, defaults.mount_root)

    for m in mounts:
        _unmount_path(Path(m["TARGET"]), defaults.mount_root)


def _cmd_debug_config(config_path: Path, defaults: Defaults, shortcuts: Dict[str, Shortcut], args: argparse.Namespace) -> None:
    info: Dict[str, Any] = {
        "config_path": str(config_path),
        "mount_root": str(defaults.mount_root),
        "default_subnet": defaults.default_subnet,
        "shortcuts": {
            name: {
                "remote": s.remote,
                "mount_dir": s.mount_dir,
                "port": s.port,
                "identity": s.identity,
                "options": list(s.options or []),
                "readonly": s.readonly,
                "no_reconnect_defaults": s.no_reconnect_defaults,
            }
            for name, s in shortcuts.items()
        },
        "mounts_under_root": _filter_mounts_under_root(_list_fuse_sshfs_mounts(), defaults.mount_root),
        "mounts_all": _list_fuse_sshfs_mounts(),
    }

    print(json.dumps(info, indent=2, sort_keys=True))


def build_parser() -> argparse.ArgumentParser:
    examples = f"""Examples:
  # Create a shortcut
  {APP_NAME} create-shortcut phone --remote user@192.0.2.10:/path

  # Mount by shortcut name
  {APP_NAME} mount phone

  # Override the last IPv4 octet using config.default_subnet (e.g. 192.0.2 -> 192.0.2.138)
  {APP_NAME} mount phone 138

  # Mount by remote and save as a shortcut (overwrites existing shortcut name)
  {APP_NAME} mount --remote user@192.0.2.10:/path --port 2200 --create-shortcut phone

  # sshfs options vs SSH options:
  #   sshfs options are passed as -o <value> (e.g. allow_other)
  {APP_NAME} mount phone -o allow_other

  #   SSH options must be passed via ssh_command
  {APP_NAME} mount phone -o "ssh_command=ssh -o KexAlgorithms=+diffie-hellman-group14-sha1"

  # List mounts under mount_root
  {APP_NAME} list-mounts

  # Unmount everything under mount_root (safe default)
  {APP_NAME} unmount-all

  # Unmount ALL sshfs mounts on the system (ignores mount_root; use with care)
  {APP_NAME} unmount-all --all

Config:
  {DEFAULT_CONFIG_PATH}
"""

    parser = argparse.ArgumentParser(
        prog=APP_NAME,
        description="CLI utility for managing sshfs mounts.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=examples,
    )

    parser.add_argument(
        "--config",
        default=str(DEFAULT_CONFIG_PATH),
        help="Path to config.toml (default: %(default)s)",
    )

    sub = parser.add_subparsers(dest="cmd", required=True)

    pm = sub.add_parser(
        "mount",
        help="Mount a shortcut or a remote via sshfs.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=textwrap.dedent(f"""\
        Examples:
          {APP_NAME} mount phone
          {APP_NAME} mount phone 138
          {APP_NAME} mount --remote user@192.0.2.10:/path --port 2200 --create-shortcut phone
          {APP_NAME} mount phone -o allow_other
          {APP_NAME} mount phone -o "ssh_command=ssh -o KexAlgorithms=+diffie-hellman-group14-sha1"
        """),
    )
    pm.add_argument("shortcut_name", nargs="?", help="Shortcut name (positional form).")
    pm.add_argument("octet", nargs="?", help="Optional last IPv4 octet override (requires config.default_subnet).")

    pm.add_argument("--remote", help="Remote in the form user@host:/path (bypasses shortcuts).")
    pm.add_argument("--mount-dir", help="Directory name under mount_root (defaults to remote path leaf).")
    pm.add_argument("-p", "--port", type=int, help="SSH port.")
    pm.add_argument("-i", "--identity", help="SSH identity file path.")
    pm.add_argument(
        "-o",
        "--option",
        dest="options",
        action="append",
        default=[],
        help="sshfs -o option value. For SSH options, use -o \"ssh_command=ssh <ssh-options>\".",
    )
    pm.add_argument("--readonly", action="store_true", help="Mount read-only (ro).")
    pm.add_argument("--no-reconnect-defaults", action="store_true", help="Disable default reconnect/ServerAlive options.")
    pm.add_argument("--create-shortcut", metavar="NAME", help="Create/overwrite shortcut NAME from this mount.")
    pm.add_argument("--shortcut", metavar="NAME", help="Shortcut name (legacy flag form; prefer positional).")

    plm = sub.add_parser("list-mounts", help="List current fuse.sshfs mounts (scoped to mount_root by default).")
    plm.add_argument("--all", action="store_true", help="List all fuse.sshfs mounts on the system.")
    plm.add_argument("--json", action="store_true", help="Emit JSON.")

    pu = sub.add_parser("unmount", help="Unmount a single sshfs mount under mount_root.")
    pu.add_argument("--path", help="Mount path to unmount.")
    pu.add_argument("--shortcut", help="Shortcut name to unmount.")

    pua = sub.add_parser("unmount-all", help="Unmount all sshfs mounts under mount_root (safe default).")
    pua.add_argument("--all", action="store_true", help="Also unmount ALL fuse.sshfs mounts on the system (dangerous; ignores mount_root).")

    ps = sub.add_parser("status", help="Show mount status for shortcuts or a path.")
    ps.add_argument("--shortcut", help="Shortcut name to check.")
    ps.add_argument("--path", help="Path to check.")

    pls = sub.add_parser("list-shortcuts", help="List configured shortcuts.")
    pls.add_argument("--json", action="store_true", help="Emit JSON.")

    pcs = sub.add_parser("create-shortcut", help="Create or update a shortcut.")
    pcs.add_argument("name", help="Shortcut name.")
    pcs.add_argument("--remote", required=True, help="Remote in the form user@host:/path.")
    pcs.add_argument("--mount-dir", help="Directory name under mount_root (defaults to remote path leaf).")
    pcs.add_argument("-p", "--port", type=int, help="SSH port to save.")
    pcs.add_argument("-i", "--identity", help="SSH identity file path to save.")
    pcs.add_argument("-o", "--option", dest="options", action="append", default=[], help="sshfs -o option value.")
    pcs.add_argument("--readonly", action="store_true", help="Save as read-only.")
    pcs.add_argument("--no-reconnect-defaults", action="store_true", help="Save without reconnect defaults.")

    pds = sub.add_parser("delete-shortcut", help="Delete a shortcut.")
    pds.add_argument("name", help="Shortcut name.")

    psub = sub.add_parser("set-default-subnet", help="Set config.default_subnet (three octets) for numeric host overrides.")
    psub.add_argument("subnet", help='Three octets like "192.0.2" (or empty string to clear).')

    pdc = sub.add_parser("debug-config", help="Print resolved config and mount diagnostics.")
    pdc.add_argument("--json", action="store_true", help="Emit JSON.")

    return parser


def main(argv: Optional[List[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    config_path = Path(args.config).expanduser()
    defaults, shortcuts = _load_config(config_path)

    if args.cmd == "list-mounts":
        _cmd_list_mounts(defaults, args)
    elif args.cmd == "list-shortcuts":
        _cmd_list_shortcuts(shortcuts, args)
    elif args.cmd == "create-shortcut":
        _cmd_create_shortcut(config_path, defaults, shortcuts, args)
    elif args.cmd == "delete-shortcut":
        _cmd_delete_shortcut(config_path, defaults, shortcuts, args)
    elif args.cmd == "set-default-subnet":
        _cmd_set_default_subnet(config_path, defaults, shortcuts, args)
    elif args.cmd == "mount":
        _cmd_mount(config_path, defaults, shortcuts, args)
    elif args.cmd == "unmount":
        _cmd_unmount(defaults, shortcuts, args)
    elif args.cmd == "unmount-all":
        _cmd_unmount_all(defaults, args)
    elif args.cmd == "status":
        _cmd_status(defaults, shortcuts, args)
    elif args.cmd == "debug-config":
        _cmd_debug_config(config_path, defaults, shortcuts, args)
    else:
        _die(f"unknown command: {args.cmd}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
