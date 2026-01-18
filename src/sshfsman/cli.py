# SPDX-License-Identifier: GPL-3.0-only
"""
sshfsman: manage sshfs mounts under a configurable mount root.

Authoritative mount detection (single ground truth everywhere):

A path is considered sshfs-mounted ONLY if:

    findmnt -T <path> shows FSTYPE == fuse.sshfs

No use of mountpoint(1), directory existence, or loose /proc/mounts parsing.
"""

from __future__ import annotations

import argparse
import os
import re
import shlex
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple

try:
    import tomllib  # py>=3.11
except Exception:  # pragma: no cover
    tomllib = None  # type: ignore[assignment]

APP_NAME = "sshfsman"
XDG_CONFIG_HOME = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
CONFIG_PATH = XDG_CONFIG_HOME / APP_NAME / "config.toml"

FSTYPE_SSHFS = "fuse.sshfs"


# ----------------------------
# Config model
# ----------------------------

@dataclass(frozen=True)
class Shortcut:
    name: str
    id: str
    remote: str
    mount_dir: str

    # Saved invocation parameters (so shortcut mounts are repeatable)
    port: Optional[int] = None
    identity: Optional[str] = None
    options: Tuple[str, ...] = ()
    readonly: bool = False
    no_reconnect_defaults: bool = False


@dataclass(frozen=True)
class AppConfig:
    mount_root: Path
    default_subnet: Optional[str]
    shortcuts: Dict[str, Shortcut]


def _default_mount_root() -> Path:
    return Path("/mnt/sshfs")


def _read_config(path: Path = CONFIG_PATH) -> AppConfig:
    mount_root = _default_mount_root()
    default_subnet: Optional[str] = None
    shortcuts: Dict[str, Shortcut] = {}

    if not path.exists():
        return AppConfig(mount_root=mount_root, default_subnet=default_subnet, shortcuts=shortcuts)

    if tomllib is None:
        raise RuntimeError("tomllib unavailable (requires Python 3.11+)")

    data = tomllib.loads(path.read_text(encoding="utf-8"))

    cfg = data.get("config", {}) if isinstance(data, dict) else {}
    mr = cfg.get("mount_root")
    if isinstance(mr, str) and mr.strip():
        mount_root = Path(mr).expanduser()

    ds = cfg.get("default_subnet")
    if isinstance(ds, str) and ds.strip():
        default_subnet = ds.strip()

    raw_shortcuts = data.get("shortcuts", {}) if isinstance(data, dict) else {}
    if isinstance(raw_shortcuts, dict):
        for name, sc in raw_shortcuts.items():
            if not isinstance(name, str) or not isinstance(sc, dict):
                continue

            sid = sc.get("id", name)
            remote = sc.get("remote")
            mount_dir = sc.get("mount_dir", name)

            if not isinstance(sid, str) or not sid.strip():
                sid = name
            if not isinstance(remote, str) or not remote.strip():
                continue
            if not isinstance(mount_dir, str) or not mount_dir.strip():
                mount_dir = name

            # Optional persisted invocation args
            port = sc.get("port")
            if isinstance(port, int):
                if not (1 <= port <= 65535):
                    port = None
            else:
                port = None

            identity = sc.get("identity")
            if not isinstance(identity, str) or not identity.strip():
                identity = None
            else:
                identity = identity.strip()

            readonly = bool(sc.get("readonly", False))
            no_reconnect_defaults = bool(sc.get("no_reconnect_defaults", False))

            options_raw = sc.get("options", [])
            options: List[str] = []
            if isinstance(options_raw, list):
                for o in options_raw:
                    if isinstance(o, str) and o.strip():
                        options.append(o.strip())
            elif isinstance(options_raw, str) and options_raw.strip():
                # tolerate legacy string form
                options.append(options_raw.strip())

            shortcuts[name] = Shortcut(
                name=name,
                id=sid.strip(),
                remote=remote.strip(),
                mount_dir=_sanitize_mount_dir(mount_dir.strip()),
                port=port,
                identity=identity,
                options=tuple(options),
                readonly=readonly,
                no_reconnect_defaults=no_reconnect_defaults,
            )

    return AppConfig(mount_root=mount_root, default_subnet=default_subnet, shortcuts=shortcuts)


def _write_config(cfg: AppConfig, path: Path = CONFIG_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)

    def esc(s: str) -> str:
        return s.replace("\\", "\\\\").replace('"', '\\"')

    lines: List[str] = []
    lines.append("[config]")
    lines.append(f'mount_root = "{esc(str(cfg.mount_root))}"')
    if cfg.default_subnet:
        lines.append(f'default_subnet = "{esc(cfg.default_subnet)}"')
    lines.append("")
    lines.append("[shortcuts]")

    for name in sorted(cfg.shortcuts.keys()):
        sc = cfg.shortcuts[name]
        lines.append(f'[shortcuts."{esc(name)}"]')
        lines.append(f'id = "{esc(sc.id)}"')
        lines.append(f'remote = "{esc(sc.remote)}"')
        lines.append(f'mount_dir = "{esc(sc.mount_dir)}"')

        if sc.port is not None:
            lines.append(f"port = {int(sc.port)}")
        if sc.identity:
            lines.append(f'identity = "{esc(sc.identity)}"')
        if sc.options:
            lines.append("options = [")
            for o in sc.options:
                lines.append(f'  "{esc(o)}",')
            lines.append("]")
        if sc.readonly:
            lines.append("readonly = true")
        if sc.no_reconnect_defaults:
            lines.append("no_reconnect_defaults = true")

        lines.append("")

    path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


# ----------------------------
# Ground-truth mount detection
# ----------------------------

def is_sshfs_mounted(target_path: Path) -> bool:
    """
    Single ground truth:

    A path is considered mounted only if:

        findmnt -T <path> shows FSTYPE == fuse.sshfs
    """
    target_path = target_path.expanduser()

    if not target_path.exists():
        return False

    cmd = ["findmnt", "-n", "-T", str(target_path), "-o", "FSTYPE"]
    try:
        cp = subprocess.run(cmd, text=True, capture_output=True, check=False)
    except FileNotFoundError:
        raise RuntimeError("findmnt not found; required for sshfsman mount detection")

    if cp.returncode != 0:
        return False

    fstype = (cp.stdout or "").strip()
    return fstype == FSTYPE_SSHFS


# ----------------------------
# Helpers
# ----------------------------

_IPV4_RE = re.compile(r"^(?P<a>\d{1,3})\.(?P<b>\d{1,3})\.(?P<c>\d{1,3})\.(?P<d>\d{1,3})$")


def _is_ipv4(s: str) -> bool:
    m = _IPV4_RE.match(s.strip())
    if not m:
        return False
    parts = [int(m.group(k)) for k in ("a", "b", "c", "d")]
    return all(0 <= p <= 255 for p in parts)


def _replace_last_octet(ip: str, last: str) -> str:
    if not _is_ipv4(ip):
        return ip
    if not last.isdigit():
        return ip
    v = int(last)
    if not (0 <= v <= 255):
        return ip
    a, b, c, _ = ip.split(".")
    return f"{a}.{b}.{c}.{v}"


def _sanitize_mount_dir(name: str) -> str:
    name = (name or "").strip()
    if not name:
        return "mount"
    name = re.sub(r"[^A-Za-z0-9._-]+", "_", name)
    name = re.sub(r"_+", "_", name).strip("_.-")
    return name or "mount"


def _run(cmd: List[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, text=True, check=False)


def _run_checked(cmd: List[str], *, what: str) -> None:
    cp = _run(cmd)
    if cp.returncode != 0:
        stderr = (cp.stderr or "").strip()
        stdout = (cp.stdout or "").strip()
        msg = f"{what} failed: {shlex.join(cmd)}"
        if stdout:
            msg += f"\nstdout: {stdout}"
        if stderr:
            msg += f"\nstderr: {stderr}"
        raise RuntimeError(msg)


def _parse_remote(remote: str) -> Tuple[str, str]:
    """
    Parse 'user@host:/path' into ('user@host', '/path').
    """
    if ":" not in remote:
        raise ValueError("remote must be in the form user@host:/path")
    left, right = remote.split(":", 1)
    if not left or not right:
        raise ValueError("remote must be in the form user@host:/path")
    if not right.startswith("/"):
        right = "/" + right
    return left, right


def _build_remote_from_shortcut(sc: Shortcut, id_override: Optional[str], default_subnet: Optional[str]) -> str:
    """
    If id_override is provided:

    - If shortcut remote contains an IPv4 host, replace last octet with id_override.
    - Else, if default_subnet exists and id_override is 0..255, use default_subnet.id_override.
    - Otherwise, leave remote unchanged.
    """
    remote = sc.remote
    if not id_override:
        return remote

    userhost, path = _parse_remote(remote)
    if "@" in userhost:
        user, host = userhost.split("@", 1)
        prefix = user + "@"
    else:
        host = userhost
        prefix = ""

    host = host.strip()
    new_host = host

    if _is_ipv4(host):
        new_host = _replace_last_octet(host, id_override)
    elif default_subnet and id_override.isdigit():
        v = int(id_override)
        if 0 <= v <= 255:
            new_host = f"{default_subnet}.{v}"

    return f"{prefix}{new_host}:{path}"


def _infer_mount_dir_from_remote(remote: str) -> str:
    userhost, path = _parse_remote(remote)
    host = userhost.split("@", 1)[-1]
    base = Path(path).name or host
    return _sanitize_mount_dir(base)


def _ensure_under_mount_root(mount_root: Path, p: Path) -> None:
    mr = mount_root.resolve()
    pp = p.resolve()
    try:
        pp.relative_to(mr)
    except Exception as e:
        raise RuntimeError(f"refusing to operate outside mount_root: {pp} (mount_root={mr})") from e


def _safe_prune_empty_dirs(mount_root: Path, start: Path) -> None:
    """
    Safety:
    - Only under mount_root
    - Only empty directories via rmdir()
    - Only if NOT sshfs-mounted (ground truth)
    - Never recurse-delete; prune upward at most to mount_root
    """
    mount_root = mount_root.resolve()
    cur = start.resolve()

    while True:
        if cur == mount_root:
            return

        _ensure_under_mount_root(mount_root, cur)

        if is_sshfs_mounted(cur):
            return

        try:
            cur.rmdir()
        except OSError:
            return

        parent = cur.parent
        if parent == cur:
            return
        cur = parent


def _find_sshfs_mounts_system() -> List[Tuple[Path, str]]:
    """
    Return [(target, source), ...] for all fuse.sshfs mounts on the system.
    """
    cmd = ["findmnt", "-rn", "-t", FSTYPE_SSHFS, "-o", "TARGET,SOURCE,FSTYPE"]
    try:
        cp = subprocess.run(cmd, text=True, capture_output=True, check=False)
    except FileNotFoundError:
        raise RuntimeError("findmnt not found; required for sshfsman mount listing")

    if cp.returncode != 0:
        return []

    mounts: List[Tuple[Path, str]] = []
    for line in (cp.stdout or "").splitlines():
        line = line.strip()
        if not line:
            continue
        parts = line.split()
        if len(parts) < 3:
            continue
        target, source, fstype = parts[0], parts[1], parts[2]
        if fstype != FSTYPE_SSHFS:
            continue
        mounts.append((Path(target), source))
    return mounts


def _validate_default_subnet(s: str) -> str:
    s = (s or "").strip()
    parts = s.split(".")
    if len(parts) != 3:
        raise ValueError("default_subnet must be three octets like 192.0.2")
    out = []
    for p in parts:
        if not p.isdigit():
            raise ValueError("default_subnet must be three octets like 192.0.2")
        v = int(p)
        if not (0 <= v <= 255):
            raise ValueError("default_subnet octets must be 0..255")
        out.append(str(v))
    return ".".join(out)


def _resolve_mountpoint_from_shortcut(cfg: AppConfig, name: str) -> Path:
    sc = cfg.shortcuts.get(name)
    if sc is None:
        raise RuntimeError(f"unknown shortcut: {name}")
    mount_name = _sanitize_mount_dir(sc.mount_dir or sc.name)
    return (cfg.mount_root.expanduser().resolve() / mount_name).resolve()


def _merge_saved_and_cli_mount_args(sc: Optional[Shortcut], args: argparse.Namespace) -> dict:
    """
    Determine mount invocation parameters.
    CLI flags override saved shortcut values.
    """
    port = args.port
    identity = args.identity
    readonly = args.readonly
    no_reconnect_defaults = args.no_reconnect_defaults
    options = list(args.options or [])

    if sc is not None:
        if port is None:
            port = sc.port
        if identity is None:
            identity = sc.identity
        if not readonly:
            readonly = sc.readonly
        if not no_reconnect_defaults:
            no_reconnect_defaults = sc.no_reconnect_defaults
        if not options and sc.options:
            options = list(sc.options)

    # Normalize options: split comma-delimited parts.
    norm: List[str] = []
    for o in options:
        if not isinstance(o, str):
            continue
        for part in o.split(","):
            part = part.strip()
            if part:
                norm.append(part)

    return {
        "port": port,
        "identity": identity,
        "readonly": readonly,
        "no_reconnect_defaults": no_reconnect_defaults,
        "options": tuple(norm),
    }


# ----------------------------
# Commands
# ----------------------------

def cmd_debug_config(args: argparse.Namespace) -> int:
    cfg = _read_config()
    mr = cfg.mount_root.expanduser().resolve()
    print(f"config_path: {CONFIG_PATH}")
    print(f"mount_root:  {mr}")
    print(f"default_subnet: {cfg.default_subnet or ''}")
    print("shortcuts:")
    for name in sorted(cfg.shortcuts.keys()):
        sc = cfg.shortcuts[name]
        print(f"  - {name}")
        print(f"      id: {sc.id}")
        print(f"      remote: {sc.remote}")
        print(f"      mount_dir: {sc.mount_dir}")
        if sc.port is not None:
            print(f"      port: {sc.port}")
        if sc.identity:
            print(f"      identity: {sc.identity}")
        if sc.options:
            print(f"      options: {', '.join(sc.options)}")
        if sc.readonly:
            print("      readonly: true")
        if sc.no_reconnect_defaults:
            print("      no_reconnect_defaults: true")

    print("")
    print("mounts_under_mount_root:")
    for target, source in _find_sshfs_mounts_system():
        try:
            target.resolve().relative_to(mr)
        except Exception:
            continue
        print(f"  - {target}  {source}")

    return 0


def cmd_list_mounts(args: argparse.Namespace) -> int:
    cfg = _read_config()
    mr = cfg.mount_root.expanduser().resolve()

    mounts = _find_sshfs_mounts_system()
    rows: List[Tuple[str, str]] = []
    for target, source in mounts:
        t = target.resolve()
        if not args.all:
            try:
                t.relative_to(mr)
            except Exception:
                continue
        rows.append((str(t), source))

    if args.json:
        import json as _json  # stdlib

        print(_json.dumps([{"target": t, "source": s} for t, s in rows], indent=2, sort_keys=True))
        return 0

    if not rows:
        return 0

    width = max(len(t) for t, _ in rows)
    for t, s in rows:
        print(f"{t.ljust(width)}  {s}")
    return 0


def cmd_list_shortcuts(args: argparse.Namespace) -> int:
    cfg = _read_config()

    if args.json:
        import json as _json  # stdlib

        payload = []
        for name in sorted(cfg.shortcuts.keys()):
            sc = cfg.shortcuts[name]
            payload.append(
                {
                    "name": name,
                    "id": sc.id,
                    "remote": sc.remote,
                    "mount_dir": sc.mount_dir,
                    "port": sc.port,
                    "identity": sc.identity,
                    "options": list(sc.options),
                    "readonly": sc.readonly,
                    "no_reconnect_defaults": sc.no_reconnect_defaults,
                }
            )
        print(_json.dumps(payload, indent=2, sort_keys=True))
        return 0

    if not cfg.shortcuts:
        return 0

    name_w = max(len(n) for n in cfg.shortcuts.keys())
    for name in sorted(cfg.shortcuts.keys()):
        sc = cfg.shortcuts[name]
        extras: List[str] = []
        if sc.port is not None:
            extras.append(f"port={sc.port}")
        if sc.identity:
            extras.append("identity=…")
        if sc.options:
            extras.append(f"options={len(sc.options)}")
        if sc.readonly:
            extras.append("readonly")
        if sc.no_reconnect_defaults:
            extras.append("no_reconnect_defaults")
        extra_s = ("  " + " ".join(extras)) if extras else ""
        print(f"{name.ljust(name_w)}  id={sc.id}  mount_dir={sc.mount_dir}  remote={sc.remote}{extra_s}")
    return 0


def cmd_create_shortcut(args: argparse.Namespace) -> int:
    cfg = _read_config()

    name = args.name
    remote = args.remote
    mount_dir = _sanitize_mount_dir(args.mount_dir or _infer_mount_dir_from_remote(remote))
    sid = args.id or name

    options = tuple(_split_options(args.options or []))

    sc_new = Shortcut(
        name=name,
        id=sid,
        remote=remote,
        mount_dir=mount_dir,
        port=args.port,
        identity=args.identity,
        options=options,
        readonly=args.readonly,
        no_reconnect_defaults=args.no_reconnect_defaults,
    )

    shortcuts = dict(cfg.shortcuts)
    shortcuts[name] = sc_new  # overwrite
    cfg2 = AppConfig(mount_root=cfg.mount_root, default_subnet=cfg.default_subnet, shortcuts=shortcuts)
    _write_config(cfg2)
    return 0


def cmd_delete_shortcut(args: argparse.Namespace) -> int:
    cfg = _read_config()
    if args.name not in cfg.shortcuts:
        return 0
    shortcuts = dict(cfg.shortcuts)
    del shortcuts[args.name]
    cfg2 = AppConfig(mount_root=cfg.mount_root, default_subnet=cfg.default_subnet, shortcuts=shortcuts)
    _write_config(cfg2)
    return 0


def cmd_set_default_subnet(args: argparse.Namespace) -> int:
    cfg = _read_config()
    subnet = _validate_default_subnet(args.subnet)
    cfg2 = AppConfig(mount_root=cfg.mount_root, default_subnet=subnet, shortcuts=dict(cfg.shortcuts))
    _write_config(cfg2)
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    cfg = _read_config()
    mr = cfg.mount_root.expanduser().resolve()

    if args.path:
        target = Path(args.path).expanduser().resolve()
        _ensure_under_mount_root(mr, target)
        mounted = is_sshfs_mounted(target)
        print("mounted" if mounted else "not mounted")
        return 0

    if args.shortcut:
        target = _resolve_mountpoint_from_shortcut(cfg, args.shortcut)
        mounted = is_sshfs_mounted(target)
        print("mounted" if mounted else "not mounted")
        return 0

    rows: List[Tuple[str, str, str]] = []
    for name in sorted(cfg.shortcuts.keys()):
        target = _resolve_mountpoint_from_shortcut(cfg, name)
        rows.append((name, str(target), "mounted" if is_sshfs_mounted(target) else "not mounted"))

    if args.json:
        import json as _json

        print(_json.dumps([{"shortcut": n, "mountpoint": p, "status": s} for n, p, s in rows], indent=2, sort_keys=True))
        return 0

    if not rows:
        return 0

    n_w = max(len(n) for n, _, _ in rows)
    p_w = max(len(p) for _, p, _ in rows)
    for n, p, s in rows:
        print(f"{n.ljust(n_w)}  {p.ljust(p_w)}  {s}")
    return 0


def _split_options(opts: List[str]) -> List[str]:
    out: List[str] = []
    for o in opts:
        if not isinstance(o, str):
            continue
        for part in o.split(","):
            part = part.strip()
            if part:
                out.append(part)
    return out


def cmd_mount(args: argparse.Namespace) -> int:
    cfg = _read_config()
    mr = cfg.mount_root.expanduser()
    mr.mkdir(parents=True, exist_ok=True)

    shortcut_name: Optional[str] = args.shortcut
    remote: Optional[str] = args.remote
    id_override: Optional[str] = args.id

    created_shortcut: Optional[str] = args.create_shortcut
    mount_dir: Optional[str] = args.mount_dir

    if shortcut_name and remote:
        raise RuntimeError("provide either --shortcut or --remote, not both")

    if not shortcut_name and not remote:
        raise RuntimeError("mount requires --shortcut NAME or --remote user@host:/path")

    sc_for_args: Optional[Shortcut] = None

    if shortcut_name:
        sc = cfg.shortcuts.get(shortcut_name)
        if sc is None:
            raise RuntimeError(f"unknown shortcut: {shortcut_name}")
        sc_for_args = sc
        remote_final = _build_remote_from_shortcut(sc, id_override, cfg.default_subnet)
        mount_name = _sanitize_mount_dir(mount_dir or sc.mount_dir or shortcut_name)
    else:
        remote_final = remote  # type: ignore[assignment]
        mount_name = _sanitize_mount_dir(mount_dir or _infer_mount_dir_from_remote(remote_final))  # type: ignore[arg-type]

    mountpoint = (mr / mount_name).resolve()
    _ensure_under_mount_root(mr, mountpoint)

    # Determine invocation params (shortcut-saved + CLI overrides)
    inv = _merge_saved_and_cli_mount_args(sc_for_args, args)

    # Shortcut behavior (required):
    # --create-shortcut NAME does NOT require --id, sets id=NAME, overwrites existing shortcut.
    if created_shortcut:
        name = created_shortcut
        sc_new = Shortcut(
            name=name,
            id=name,
            remote=remote_final,
            mount_dir=mount_name,
            port=inv["port"],
            identity=inv["identity"],
            options=inv["options"],
            readonly=bool(inv["readonly"]),
            no_reconnect_defaults=bool(inv["no_reconnect_defaults"]),
        )
        shortcuts = dict(cfg.shortcuts)
        shortcuts[name] = sc_new
        cfg2 = AppConfig(mount_root=cfg.mount_root, default_subnet=cfg.default_subnet, shortcuts=shortcuts)
        _write_config(cfg2)
        cfg = cfg2

    # Guard: only block if actually sshfs-mounted (ground truth)
    if is_sshfs_mounted(mountpoint):
        print(f"already mounted: {mountpoint}")
        return 0

    mountpoint.mkdir(parents=True, exist_ok=True)

    cmd: List[str] = ["sshfs", remote_final, str(mountpoint)]

    opts: List[str] = []
    if not inv["no_reconnect_defaults"]:
        opts.extend(["reconnect", "ServerAliveInterval=15", "ServerAliveCountMax=3"])
    if inv["readonly"]:
        opts.append("ro")
    if inv["options"]:
        opts.extend(list(inv["options"]))

    for o in opts:
        cmd.extend(["-o", o])

    if inv["port"] is not None:
        cmd.extend(["-p", str(inv["port"])])
    if inv["identity"]:
        cmd.extend(["-o", f"IdentityFile={inv['identity']}"])

    _run_checked(cmd, what="sshfs mount")

    if not is_sshfs_mounted(mountpoint):
        raise RuntimeError(f"mount command succeeded but mount not detected as {FSTYPE_SSHFS} via findmnt: {mountpoint}")

    return 0


def _unmount_one(mount_root: Path, target: Path) -> None:
    target = target.resolve()
    _ensure_under_mount_root(mount_root, target)

    if not is_sshfs_mounted(target):
        return

    try:
        subprocess.run(["fusermount3", "-V"], text=True, capture_output=True, check=False)
        use_fuse = True
    except FileNotFoundError:
        use_fuse = False

    if use_fuse:
        _run_checked(["fusermount3", "-u", str(target)], what="fusermount3 -u")
    else:
        _run_checked(["umount", str(target)], what="umount")

    if is_sshfs_mounted(target):
        raise RuntimeError(f"unmount failed (still mounted as {FSTYPE_SSHFS}): {target}")

    _safe_prune_empty_dirs(mount_root, target)


def cmd_unmount(args: argparse.Namespace) -> int:
    cfg = _read_config()
    mr = cfg.mount_root.expanduser().resolve()

    if args.path:
        target = Path(args.path).expanduser().resolve()
        _unmount_one(mr, target)
        return 0

    if args.shortcut:
        target = _resolve_mountpoint_from_shortcut(cfg, args.shortcut)
        _unmount_one(mr, target)
        return 0

    raise RuntimeError("unmount requires --path PATH or --shortcut NAME")


def cmd_unmount_all(args: argparse.Namespace) -> int:
    cfg = _read_config()
    mr = cfg.mount_root.expanduser().resolve()

    mounts = _find_sshfs_mounts_system()
    targets: List[Path] = []

    for target, _source in mounts:
        t = target.resolve()
        if not args.all:
            try:
                t.relative_to(mr)
            except Exception:
                continue
        targets.append(t)

    targets = sorted(set(targets), key=lambda p: (len(str(p)), str(p)), reverse=True)

    for t in targets:
        if args.all:
            if is_sshfs_mounted(t):
                try:
                    subprocess.run(["fusermount3", "-V"], text=True, capture_output=True, check=False)
                    use_fuse = True
                except FileNotFoundError:
                    use_fuse = False

                if use_fuse:
                    _run_checked(["fusermount3", "-u", str(t)], what="fusermount3 -u")
                else:
                    _run_checked(["umount", str(t)], what="umount")

                if is_sshfs_mounted(t):
                    raise RuntimeError(f"unmount-all failed (still mounted as {FSTYPE_SSHFS}): {t}")

                try:
                    t.relative_to(mr)
                    _safe_prune_empty_dirs(mr, t)
                except Exception:
                    pass
            continue

        _unmount_one(mr, t)

    return 0


# ----------------------------
# CLI
# ----------------------------

HELP_EXAMPLES = r"""
Examples

  # Mount by remote and create/overwrite a shortcut named "phone" (port saved in shortcut)
  sshfsman mount --remote user@192.0.2.10:/path --port 2222 --create-shortcut phone

  # Mount using a shortcut, overriding the last octet of the shortcut's IPv4 host
  sshfsman mount --shortcut phone 138

  # Create/overwrite a shortcut explicitly (including saved port/options)
  sshfsman create-shortcut phone --remote user@192.0.2.10:/path --port 2222 -o allow_other

  # List sshfs mounts under mount_root
  sshfsman list-mounts

  # Unmount everything under mount_root
  sshfsman unmount-all

  # Set default_subnet (three octets)
  sshfsman set-default-subnet 192.0.2
""".rstrip()


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog=APP_NAME,
        description="Manage sshfs mounts under a configurable mount root (default /mnt/sshfs).",
        epilog=HELP_EXAMPLES,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = p.add_subparsers(dest="cmd", required=True)

    # mount
    pm = sub.add_parser("mount", help="Mount an sshfs target")
    pm.add_argument("--remote", help="Remote in form user@host:/path")
    pm.add_argument("--shortcut", help="Shortcut name from config.")
    pm.add_argument("id", nargs="?", help="Optional ID override (e.g., last IPv4 octet). Used with --shortcut.")
    pm.add_argument("--create-shortcut", metavar="NAME", help="Create/overwrite shortcut NAME. Sets shortcut id=NAME and saves invocation.")
    pm.add_argument("--mount-dir", metavar="DIR", help="Mount directory name under mount_root.")
    pm.add_argument("-p", "--port", type=int, help="SSH port (passed to sshfs -p). Saved into shortcut when creating.")
    pm.add_argument("-i", "--identity", metavar="PATH", help="SSH identity file. Saved into shortcut when creating.")
    pm.add_argument("--readonly", action="store_true", help="Mount read-only. Saved into shortcut when creating.")
    pm.add_argument(
        "-o",
        "--option",
        dest="options",
        action="append",
        default=[],
        help="Extra sshfs -o option (repeatable; comma-delimited ok). Saved into shortcut when creating.",
    )
    pm.add_argument(
        "--no-reconnect-defaults",
        action="store_true",
        help="Disable default reconnect/keepalive sshfs options. Saved into shortcut when creating.",
    )
    pm.set_defaults(func=cmd_mount)

    # unmount
    pu = sub.add_parser("unmount", help="Unmount an sshfs mount")
    pu.add_argument("--path", help="Mountpoint path to unmount (must be under mount_root).")
    pu.add_argument("--shortcut", help="Shortcut name to unmount (maps to its mount_dir under mount_root).")
    pu.set_defaults(func=cmd_unmount)

    # unmount-all
    pua = sub.add_parser("unmount-all", help="Unmount all sshfs mounts under mount_root")
    pua.add_argument("--all", action="store_true", help="Also unmount fuse.sshfs mounts outside mount_root.")
    pua.set_defaults(func=cmd_unmount_all)

    # status
    ps = sub.add_parser("status", help="Show mount status")
    ps.add_argument("--path", help="Check status of a mountpoint path (under mount_root).")
    ps.add_argument("--shortcut", help="Check status of a shortcut name.")
    ps.add_argument("--json", action="store_true", help="Emit JSON (when listing all shortcuts).")
    ps.set_defaults(func=cmd_status)

    # list-mounts (hard break: list-mounted removed)
    plm = sub.add_parser("list-mounts", help="List sshfs mounts under mount_root")
    plm.add_argument("--all", action="store_true", help="Show all system fuse.sshfs mounts, not just those under mount_root.")
    plm.add_argument("--json", action="store_true", help="Emit JSON.")
    plm.set_defaults(func=cmd_list_mounts)

    # list-shortcuts
    pls = sub.add_parser("list-shortcuts", help="List configured shortcuts")
    pls.add_argument("--json", action="store_true", help="Emit JSON.")
    pls.set_defaults(func=cmd_list_shortcuts)

    # create-shortcut
    pcs = sub.add_parser("create-shortcut", help="Create or update a shortcut")
    pcs.add_argument("name", help="Shortcut name")
    pcs.add_argument("--remote", required=True, help="Remote in form user@host:/path")
    pcs.add_argument("--id", help="Optional id field for the shortcut (defaults to NAME).")
    pcs.add_argument("--mount-dir", metavar="DIR", help="Mount directory name under mount_root.")
    pcs.add_argument("-p", "--port", type=int, help="Saved SSH port for this shortcut.")
    pcs.add_argument("-i", "--identity", metavar="PATH", help="Saved identity file for this shortcut.")
    pcs.add_argument("--readonly", action="store_true", help="Saved read-only flag for this shortcut.")
    pcs.add_argument(
        "-o",
        "--option",
        dest="options",
        action="append",
        default=[],
        help="Saved sshfs -o option (repeatable; comma-delimited ok).",
    )
    pcs.add_argument(
        "--no-reconnect-defaults",
        action="store_true",
        help="Saved flag: disable default reconnect/keepalive sshfs options.",
    )
    pcs.set_defaults(func=cmd_create_shortcut)

    # delete-shortcut
    pds = sub.add_parser("delete-shortcut", help="Delete a shortcut")
    pds.add_argument("name", help="Shortcut name")
    pds.set_defaults(func=cmd_delete_shortcut)

    # set-default-subnet
    psub = sub.add_parser("set-default-subnet", help="Set defaults.default_subnet (three octets)")
    psub.add_argument("subnet", help="Three octets like 192.0.2")
    psub.set_defaults(func=cmd_set_default_subnet)

    # debug-config
    pdc = sub.add_parser("debug-config", help="Print resolved config and mount diagnostics")
    pdc.set_defaults(func=cmd_debug_config)

    return p


def main(argv: Optional[List[str]] = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        return int(args.func(args))
    except KeyboardInterrupt:
        return 130
    except Exception as e:
        msg = str(e).strip() or repr(e)
        print(f"{APP_NAME}: {msg}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
