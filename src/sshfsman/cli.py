#!/usr/bin/env python3
"""sshfsman: mount/unmount sshfs targets under an XDG-configured mount root.

Goals:
- predictable mountpoints: <mount_root>/<id>
- mount/unmount + safe prune of empty mountpoint dirs
- XDG config: $XDG_CONFIG_HOME/sshfsman/config.toml or ~/.config/sshfsman/config.toml
- shortcuts: name -> directives (id/user/path/port/auth flags/default subnet)
- supports dynamic IPs via last-octet targets (e.g., Android MAC randomization)
"""

from __future__ import annotations

import argparse
import os
import re
import shlex
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

try:
    import tomllib  # py3.11+
except Exception:  # pragma: no cover
    tomllib = None  # type: ignore


DEFAULT_CONFIG_REL = Path("sshfsman") / "config.toml"


def eprint(*a: object) -> None:
    print(*a, file=sys.stderr)


def run(cmd: list[str], *, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, check=check, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)


def which_first(names: list[str]) -> str | None:
    for n in names:
        p = shutil_which(n)
        if p:
            return p
    return None


def shutil_which(name: str) -> str | None:
    # avoid importing shutil in a tight tool (but it's fine either way)
    from shutil import which

    return which(name)


def config_path(explicit: str | None = None) -> Path:
    if explicit:
        return Path(explicit).expanduser()
    xdg = os.environ.get("XDG_CONFIG_HOME")
    if xdg:
        return Path(xdg) / DEFAULT_CONFIG_REL
    return Path.home() / ".config" / DEFAULT_CONFIG_REL


def ensure_parent_dir(p: Path) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)


def load_config(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    if tomllib is None:
        raise RuntimeError("Python 3.11+ required (tomllib missing)")
    data = tomllib.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        return {}
    return data


def toml_quote(s: str) -> str:
    # Basic TOML string quoting, good enough for our expected fields.
    s = s.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{s}"'


def dump_toml(data: dict[str, Any]) -> str:
    """Small TOML emitter for our limited schema.

    Note: this rewrites formatting and drops comments by design.
    """

    lines: list[str] = []

    def emit_kv(k: str, v: Any) -> None:
        if isinstance(v, bool):
            lines.append(f"{k} = {'true' if v else 'false'}")
        elif isinstance(v, int):
            lines.append(f"{k} = {v}")
        elif isinstance(v, float):
            lines.append(f"{k} = {v}")
        elif isinstance(v, str):
            lines.append(f"{k} = {toml_quote(v)}")
        elif isinstance(v, list):
            parts = []
            for it in v:
                if isinstance(it, str):
                    parts.append(toml_quote(it))
                elif isinstance(it, bool):
                    parts.append("true" if it else "false")
                elif isinstance(it, (int, float)):
                    parts.append(str(it))
                else:
                    parts.append(toml_quote(str(it)))
            lines.append(f"{k} = [{', '.join(parts)}]")
        else:
            # fallback string
            lines.append(f"{k} = {toml_quote(str(v))}")

    defaults = data.get("defaults")
    if isinstance(defaults, dict):
        lines.append("[defaults]")
        for k in sorted(defaults.keys()):
            emit_kv(k, defaults[k])
        lines.append("")

    shortcuts = data.get("shortcuts")
    if isinstance(shortcuts, dict):
        for name in sorted(shortcuts.keys()):
            entry = shortcuts[name]
            if not isinstance(entry, dict):
                continue
            lines.append(f"[shortcuts.{name}]")
            for k in sorted(entry.keys()):
                emit_kv(k, entry[k])
            lines.append("")

    if not lines:
        return ""
    # strip trailing blank lines
    while lines and lines[-1] == "":
        lines.pop()
    return "\n".join(lines) + "\n"


@dataclass
class Defaults:
    mount_root: str = "/mnt/sshfs"
    default_port: int = 22
    default_subnet: str | None = None  # e.g., "10.0.20"
    default_user: str | None = None


@dataclass
class Shortcut:
    name: str
    id: str
    remote_path: str
    user: str | None = None
    port: int | None = None
    insecure_hostkey: bool = False
    prefer_password: bool = False
    disable_pubkey: bool = False
    extra_sshfs_opts: list[str] = field(default_factory=list)
    fixed_host: str | None = None  # optional pinned host/ip for "--shortcut NAME --mount" with no target


def parse_defaults(cfg: dict[str, Any]) -> Defaults:
    d = Defaults()
    raw = cfg.get("defaults")
    if isinstance(raw, dict):
        if isinstance(raw.get("mount_root"), str):
            d.mount_root = raw["mount_root"]
        if isinstance(raw.get("default_port"), int):
            d.default_port = raw["default_port"]
        if isinstance(raw.get("default_subnet"), str):
            d.default_subnet = raw["default_subnet"].strip().strip(".")
        if isinstance(raw.get("default_user"), str):
            d.default_user = raw["default_user"]
    return d


def parse_shortcuts(cfg: dict[str, Any], defaults: Defaults) -> dict[str, Shortcut]:
    out: dict[str, Shortcut] = {}
    raw = cfg.get("shortcuts")
    if not isinstance(raw, dict):
        return out

    for name, ent in raw.items():
        if not isinstance(name, str) or not isinstance(ent, dict):
            continue
        sid = ent.get("id") if isinstance(ent.get("id"), str) else name
        rpath = ent.get("remote_path")
        if not isinstance(rpath, str):
            continue
        sc = Shortcut(
            name=name,
            id=sid,
            remote_path=rpath,
            user=ent.get("user") if isinstance(ent.get("user"), str) else defaults.default_user,
            port=ent.get("port") if isinstance(ent.get("port"), int) else None,
            insecure_hostkey=bool(ent.get("insecure_hostkey")) if "insecure_hostkey" in ent else False,
            prefer_password=bool(ent.get("prefer_password")) if "prefer_password" in ent else False,
            disable_pubkey=bool(ent.get("disable_pubkey")) if "disable_pubkey" in ent else False,
            extra_sshfs_opts=list(ent.get("extra_sshfs_opts")) if isinstance(ent.get("extra_sshfs_opts"), list) else [],
            fixed_host=ent.get("fixed_host") if isinstance(ent.get("fixed_host"), str) else None,
        )
        out[name] = sc

    return out


def realpath_strict(p: Path) -> Path:
    # resolve without requiring path exists
    try:
        return p.resolve(strict=False)
    except Exception:
        return Path(os.path.realpath(str(p)))


def ensure_under_root(mount_root: Path, mountpoint: Path) -> None:
    mr = realpath_strict(mount_root)
    mp = realpath_strict(mountpoint)
    try:
        mp.relative_to(mr)
    except Exception:
        raise SystemExit(f"Refusing to operate: mountpoint {mp} is not under mount_root {mr}")


def is_mounted(mountpoint: Path) -> bool:
    # fast path: findmnt if available
    if shutil_which("findmnt"):
        r = subprocess.run(["findmnt", "-n", "-T", str(mountpoint)], text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        return r.returncode == 0

    # fallback: /proc/mounts
    try:
        text = Path("/proc/mounts").read_text(encoding="utf-8")
    except Exception:
        return False
    mp = str(mountpoint)
    for line in text.splitlines():
        parts = line.split()
        if len(parts) >= 2 and parts[1] == mp:
            return True
    return False


def list_mounted_under(mount_root: Path) -> list[dict[str, str]]:
    """Return mounted fuse.sshfs entries under mount_root.

    Each entry: {mountpoint, source, fstype}
    """
    # Prefer findmnt if present: it understands mount namespaces and is robust.
    if shutil_which("findmnt"):
        try:
            # -r no headings, -n raw, -t type, -o columns
            r = run(["findmnt", "-rn", "-t", "fuse.sshfs", "-o", "TARGET,SOURCE,FSTYPE"], check=False)
            text = (r.stdout or "").strip("\n")
        except Exception:
            text = ""
        out: list[dict[str, str]] = []
        mr = realpath_strict(mount_root)
        for line in text.splitlines():
            # TARGET SOURCE FSTYPE (space-separated; SOURCE can include spaces rarely, but sshfs sources won't)
            parts = line.split()
            if len(parts) < 3:
                continue
            mp, src, fstype = parts[0], parts[1], parts[2]
            try:
                realpath_strict(Path(mp)).relative_to(mr)
            except Exception:
                continue
            out.append({"mountpoint": mp, "source": src, "fstype": fstype})
        out.sort(key=lambda d: d["mountpoint"])
        return out

    # Fallback: parse /proc/mounts
    out2: list[dict[str, str]] = []
    mr2 = realpath_strict(mount_root)
    try:
        text2 = Path("/proc/mounts").read_text(encoding="utf-8")
    except Exception:
        return out2

    for line in text2.splitlines():
        parts = line.split()
        if len(parts) < 3:
            continue
        src, mp, fstype = parts[0], parts[1], parts[2]
        if fstype != "fuse.sshfs":
            continue
        try:
            realpath_strict(Path(mp)).relative_to(mr2)
        except Exception:
            continue
        out2.append({"mountpoint": mp, "source": src, "fstype": fstype})

    out2.sort(key=lambda d: d["mountpoint"])
    return out2


def list_all_sshfs_mounts() -> list[dict[str, str]]:
    """Return all fuse.sshfs mounts visible to this process."""
    out: list[dict[str, str]] = []
    if shutil_which("findmnt"):
        r = run(["findmnt", "-rn", "-t", "fuse.sshfs", "-o", "TARGET,SOURCE,FSTYPE"], check=False)
        for line in (r.stdout or "").splitlines():
            parts = line.split()
            if len(parts) < 3:
                continue
            mp, src, fstype = parts[0], parts[1], parts[2]
            out.append({"mountpoint": mp, "source": src, "fstype": fstype})
    else:
        try:
            text = Path("/proc/mounts").read_text(encoding="utf-8")
        except Exception:
            return out
        for line in text.splitlines():
            parts = line.split()
            if len(parts) < 3:
                continue
            src, mp, fstype = parts[0], parts[1], parts[2]
            if fstype != "fuse.sshfs":
                continue
            out.append({"mountpoint": mp, "source": src, "fstype": fstype})
    out.sort(key=lambda d: d["mountpoint"])
    return out


def build_sshfs_cmd(
    remote: str,
    mountpoint: Path,
    *,
    port: int,
    password: bool,
    non_interactive: bool,
    insecure_hostkey: bool,
    disable_pubkey: bool,
    extra_sshfs_opts: list[str],
) -> list[str]:
    cmd = ["sshfs", remote, str(mountpoint)]

    # base stability
    opts = [
        "reconnect",
        "ServerAliveInterval=15",
        "ServerAliveCountMax=3",
    ]

    # port
    opts.append(f"ssh_command=ssh -p {port}")

    if insecure_hostkey:
        opts.append("StrictHostKeyChecking=no")
        opts.append("UserKnownHostsFile=/dev/null")

    if password:
        opts.append("PasswordAuthentication=yes")

    if disable_pubkey:
        opts.append("PubkeyAuthentication=no")

    # user-provided extra -o entries
    for o in extra_sshfs_opts:
        # accept either "foo=bar" or already "-o foo=bar"
        o = o.strip()
        if not o:
            continue
        if o.startswith("-o "):
            cmd.extend(shlex.split(o))
        else:
            opts.append(o)

    for o in opts:
        cmd.extend(["-o", o])

    if non_interactive:
        # sshfs itself doesn't read password from env; we need sshpass.
        if not shutil_which("sshpass"):
            raise SystemExit("--non-interactive requires sshpass")
        pw = os.environ.get("SSHFSMAN_PASSWORD")
        if not pw:
            raise SystemExit("--non-interactive requires SSHFSMAN_PASSWORD env var")
        cmd = ["sshpass", "-p", pw] + cmd

    return cmd


def parse_remote(remote: str) -> tuple[str | None, str, str]:
    """Return (user, host, path) from user@host:/path or host:/path."""
    m = re.match(r"^(?:(?P<user>[^@]+)@)?(?P<host>[^:]+):(?P<path>/.*)$", remote)
    if not m:
        raise SystemExit("--remote must look like [user@]host:/absolute/path")
    return m.group("user"), m.group("host"), m.group("path")


def resolve_shortcut_target(defaults: Defaults, sc: Shortcut, target: str | None) -> str:
    """Resolve target host/IP.

    Rules:
    - if target is None and sc.fixed_host exists, use it
    - if target is digits-only and defaults.default_subnet exists, build <subnet>.<target>
    - else use target as given
    """
    if target is None:
        if sc.fixed_host:
            return sc.fixed_host
        raise SystemExit(f"Shortcut '{sc.name}' requires a target unless fixed_host is set")

    t = target.strip()
    if re.fullmatch(r"\d{1,3}", t):
        if not defaults.default_subnet:
            raise SystemExit("No default_subnet configured. Set one with: sshfsman set-default-subnet 10.0.20")
        return f"{defaults.default_subnet}.{t}"

    return t


def ensure_mountpoint(defaults: Defaults, id_: str) -> Path:
    root = Path(defaults.mount_root)
    mp = root / id_
    root.mkdir(parents=True, exist_ok=True)
    mp.mkdir(parents=True, exist_ok=True)
    ensure_under_root(root, mp)
    return mp


def prune_mountpoint_if_safe(defaults: Defaults, mountpoint: Path, keep_dir: bool) -> None:
    if keep_dir:
        return
    # must not be mounted
    if is_mounted(mountpoint):
        return
    # must be under mount_root
    ensure_under_root(Path(defaults.mount_root), mountpoint)
    # must be empty
    try:
        next(mountpoint.iterdir())
        return
    except StopIteration:
        pass
    except FileNotFoundError:
        return

    try:
        mountpoint.rmdir()  # ONLY removes empty dir
    except OSError:
        return


def unmount_one(defaults: Defaults, mountpoint: Path, keep_dir: bool) -> None:
    # prefer fusermount3
    if shutil_which("fusermount3"):
        r = subprocess.run(["fusermount3", "-u", str(mountpoint)])
        if r.returncode != 0:
            raise SystemExit(f"unmount failed for {mountpoint}")
    elif shutil_which("fusermount"):
        r = subprocess.run(["fusermount", "-u", str(mountpoint)])
        if r.returncode != 0:
            raise SystemExit(f"unmount failed for {mountpoint}")
    else:
        raise SystemExit("Need fusermount3 (fuse3) or fusermount")

    prune_mountpoint_if_safe(defaults, mountpoint, keep_dir=keep_dir)


def upsert_shortcut(cfg_path: Path, cfg: dict[str, Any], name: str, entry: dict[str, Any]) -> None:
    if "shortcuts" not in cfg or not isinstance(cfg.get("shortcuts"), dict):
        cfg["shortcuts"] = {}
    cfg["shortcuts"][name] = entry
    ensure_parent_dir(cfg_path)
    cfg_path.write_text(dump_toml(cfg), encoding="utf-8")


def delete_shortcut(cfg_path: Path, cfg: dict[str, Any], name: str) -> None:
    raw = cfg.get("shortcuts")
    if not isinstance(raw, dict) or name not in raw:
        raise SystemExit(f"No such shortcut: {name}")
    del raw[name]
    ensure_parent_dir(cfg_path)
    cfg_path.write_text(dump_toml(cfg), encoding="utf-8")


def set_default_subnet(cfg_path: Path, cfg: dict[str, Any], subnet: str) -> None:
    subnet = subnet.strip().strip(".")
    if not re.fullmatch(r"\d{1,3}\.\d{1,3}\.\d{1,3}", subnet):
        raise SystemExit("default_subnet must look like '10.0.20' (three octets)")

    if "defaults" not in cfg or not isinstance(cfg.get("defaults"), dict):
        cfg["defaults"] = {}
    cfg["defaults"]["default_subnet"] = subnet
    ensure_parent_dir(cfg_path)
    cfg_path.write_text(dump_toml(cfg), encoding="utf-8")


def cmd_list_shortcuts(args: argparse.Namespace, cfg_path: Path, cfg: dict[str, Any]) -> int:
    defaults = parse_defaults(cfg)
    shortcuts = parse_shortcuts(cfg, defaults)
    if not shortcuts:
        print("(no shortcuts)")
        return 0

    for name in sorted(shortcuts.keys()):
        sc = shortcuts[name]
        subnet = defaults.default_subnet if defaults.default_subnet else "(no-default_subnet)"
        port = sc.port if sc.port is not None else defaults.default_port
        user = sc.user if sc.user else "(no-user)"
        flags = []
        if sc.prefer_password:
            flags.append("prefer_password")
        if sc.disable_pubkey:
            flags.append("disable_pubkey")
        if sc.insecure_hostkey:
            flags.append("insecure_hostkey")
        if sc.fixed_host:
            flags.append(f"fixed_host={sc.fixed_host}")

        print(
            f"{name}: id={sc.id} user={user} port={port} subnet={subnet} remote_path={sc.remote_path}"
            + (f" flags={','.join(flags)}" if flags else "")
        )

    return 0


def cmd_list_mounted(args: argparse.Namespace, cfg_path: Path, cfg: dict[str, Any]) -> int:
    defaults = parse_defaults(cfg)
    entries = list_all_sshfs_mounts() if getattr(args, "all", False) else list_mounted_under(Path(defaults.mount_root))
    if not entries:
        if getattr(args, "all", False):
            print("(no sshfs mounts)")
        else:
            print("(no sshfs mounts under mount_root)")
        return 0
    for e in entries:
        mp = e["mountpoint"]
        ident = Path(mp).name
        print(f"{ident}: mountpoint={mp} source={e['source']}")
    return 0


def cmd_debug_config(args: argparse.Namespace, cfg_path: Path, cfg: dict[str, Any]) -> int:
    """Print resolved config + defaults + mount_root realpath."""
    defaults = parse_defaults(cfg)
    shortcuts = parse_shortcuts(cfg, defaults)

    print(f"config_path={cfg_path}")
    print(f"config_exists={cfg_path.exists()}")
    print(f"mount_root={defaults.mount_root}")
    try:
        print(f"mount_root_realpath={realpath_strict(Path(defaults.mount_root))}")
    except Exception as ex:
        print(f"mount_root_realpath=(error: {ex})")
    print(f"default_subnet={defaults.default_subnet if defaults.default_subnet else '(unset)'}")
    print(f"default_port={defaults.default_port}")
    print(f"default_user={defaults.default_user if defaults.default_user else '(unset)'}")
    print(f"shortcuts_count={len(shortcuts)}")

    # quick mount visibility check
    all_m = list_all_sshfs_mounts()
    under = list_mounted_under(Path(defaults.mount_root))
    print(f"sshfs_mounts_total={len(all_m)}")
    print(f"sshfs_mounts_under_mount_root={len(under)}")
    return 0


def cmd_unmount_all(args: argparse.Namespace, cfg_path: Path, cfg: dict[str, Any]) -> int:
    defaults = parse_defaults(cfg)
    entries = list_mounted_under(Path(defaults.mount_root))
    if not entries:
        print("(no sshfs mounts under mount_root)")
        return 0

    failures: list[str] = []
    for e in entries:
        mp = Path(e["mountpoint"])
        try:
            unmount_one(defaults, mp, keep_dir=args.keep_dir)
        except SystemExit as ex:
            failures.append(f"{mp}: {ex}")

    if failures:
        eprint("Some unmounts failed:")
        for f in failures:
            eprint("-", f)
        return 2

    return 0


def cmd_delete_shortcut(args: argparse.Namespace, cfg_path: Path, cfg: dict[str, Any]) -> int:
    delete_shortcut(cfg_path, cfg, args.name)
    print(f"Deleted shortcut: {args.name}")
    return 0




def cmd_create_shortcut(args: argparse.Namespace, cfg_path: Path, cfg: dict[str, Any]) -> int:
    """Create or update a shortcut entry in the config.

    Note: This uses a minimal TOML writer and will not preserve comments/formatting.
    """
    defaults = parse_defaults(cfg)

    name = args.name
    entry: dict[str, object] = {}

    entry["id"] = args.id or name
    if args.remote_path is None:
        raise SystemExit("create-shortcut requires --remote-path")
    entry["remote_path"] = args.remote_path

    if args.user:
        entry["user"] = args.user
    if args.port:
        entry["port"] = int(args.port)

    # Optional fixed host. If set, `sshfsman mount --shortcut NAME` can omit the target.
    if args.fixed_host:
        entry["fixed_host"] = args.fixed_host

    entry["prefer_password"] = bool(args.prefer_password)
    entry["disable_pubkey"] = bool(args.disable_pubkey)
    entry["insecure_hostkey"] = bool(args.insecure_hostkey)

    extra = list(args.extra_sshfs_opt) if args.extra_sshfs_opt else []
    if extra:
        entry["extra_sshfs_opts"] = extra

    upsert_shortcut(cfg_path, cfg, name, entry)
    print(f"Saved shortcut: {name}")
    return 0


def cmd_set_default_subnet(args: argparse.Namespace, cfg_path: Path, cfg: dict[str, Any]) -> int:
    set_default_subnet(cfg_path, cfg, args.subnet)
    print(f"Set default_subnet={args.subnet}")
    return 0


def cmd_mount(args: argparse.Namespace, cfg_path: Path, cfg: dict[str, Any]) -> int:
    defaults = parse_defaults(cfg)
    shortcuts = parse_shortcuts(cfg, defaults)

    # Determine effective parameters
    create_name: str | None = args.create_shortcut

    if args.shortcut:
        sc = shortcuts.get(args.shortcut)
        if not sc:
            raise SystemExit(f"No such shortcut: {args.shortcut}")
        host = resolve_shortcut_target(defaults, sc, args.target)
        user = sc.user or defaults.default_user
        if not user:
            raise SystemExit(f"Shortcut '{sc.name}' has no user and no defaults.default_user")
        port = sc.port if sc.port is not None else defaults.default_port
        remote = f"{user}@{host}:{sc.remote_path}"
        id_ = sc.id

        password = bool(args.password) or sc.prefer_password
        disable_pubkey = bool(args.disable_pubkey) or sc.disable_pubkey
        insecure_hostkey = bool(args.insecure_hostkey) or sc.insecure_hostkey
        extra = list(sc.extra_sshfs_opts)
        if args.extra_sshfs_opt:
            extra.extend(args.extra_sshfs_opt)

        mp = ensure_mountpoint(defaults, id_)
        cmd = build_sshfs_cmd(
            remote,
            mp,
            port=port,
            password=password,
            non_interactive=bool(args.non_interactive),
            insecure_hostkey=insecure_hostkey,
            disable_pubkey=disable_pubkey,
            extra_sshfs_opts=extra,
        )

        # already mounted?
        if is_mounted(mp):
            print(f"already mounted: {mp}")
            return 0

        r = subprocess.run(cmd)
        if r.returncode != 0:
            raise SystemExit(f"sshfs failed ({r.returncode})")

        if create_name:
            entry = {
                "id": id_,
                "remote_path": sc.remote_path,
                "user": user,
                "port": port,
                "prefer_password": password,
                "disable_pubkey": disable_pubkey,
                "insecure_hostkey": insecure_hostkey,
                "extra_sshfs_opts": extra,
                # if user passed a target, we preserve dynamic behavior by NOT pinning fixed_host
            }
            # only pin fixed_host if user did NOT specify target (meaning they likely want stable host)
            if args.target is None:
                entry["fixed_host"] = host
            upsert_shortcut(cfg_path, cfg, create_name, entry)
            print(f"Saved shortcut: {create_name}")

        return 0

    # Non-shortcut mount
    if not args.remote:
        raise SystemExit("mount requires --remote when not using --shortcut")

    u, host, rpath = parse_remote(args.remote)

    # If user is creating a shortcut and didn't provide --id, default id to shortcut name
    id_ = args.id
    if not id_:
        if create_name:
            id_ = create_name
        else:
            raise SystemExit("mount requires --id (or use --create-shortcut NAME to auto-derive id)")

    mp = ensure_mountpoint(defaults, id_)

    port = args.port if args.port else defaults.default_port
    password = bool(args.password)
    disable_pubkey = bool(args.disable_pubkey)
    insecure_hostkey = bool(args.insecure_hostkey)

    extra = list(args.extra_sshfs_opt) if args.extra_sshfs_opt else []

    cmd = build_sshfs_cmd(
        args.remote,
        mp,
        port=port,
        password=password,
        non_interactive=bool(args.non_interactive),
        insecure_hostkey=insecure_hostkey,
        disable_pubkey=disable_pubkey,
        extra_sshfs_opts=extra,
    )

    if is_mounted(mp):
        print(f"already mounted: {mp}")
        return 0

    r = subprocess.run(cmd)
    if r.returncode != 0:
        raise SystemExit(f"sshfs failed ({r.returncode})")

    if create_name:
        user = u or defaults.default_user
        entry = {
            "id": id_,
            "remote_path": rpath,
            "user": user,
            "port": port,
            "prefer_password": password,
            "disable_pubkey": disable_pubkey,
            "insecure_hostkey": insecure_hostkey,
            "extra_sshfs_opts": extra,
            # pin fixed host to allow "sshfsman --shortcut NAME --mount" later
            "fixed_host": host,
        }
        upsert_shortcut(cfg_path, cfg, create_name, entry)
        print(f"Saved shortcut: {create_name}")

    return 0


def cmd_unmount(args: argparse.Namespace, cfg_path: Path, cfg: dict[str, Any]) -> int:
    defaults = parse_defaults(cfg)
    shortcuts = parse_shortcuts(cfg, defaults)

    if args.shortcut:
        sc = shortcuts.get(args.shortcut)
        if not sc:
            raise SystemExit(f"No such shortcut: {args.shortcut}")
        mp = Path(defaults.mount_root) / sc.id
    else:
        if not args.id:
            raise SystemExit("unmount requires --id or --shortcut")
        mp = Path(defaults.mount_root) / args.id

    ensure_under_root(Path(defaults.mount_root), mp)

    if not is_mounted(mp):
        print(f"not mounted: {mp}")
        prune_mountpoint_if_safe(defaults, mp, keep_dir=args.keep_dir)
        return 0

    unmount_one(defaults, mp, keep_dir=args.keep_dir)
    return 0


def cmd_status(args: argparse.Namespace, cfg_path: Path, cfg: dict[str, Any]) -> int:
    defaults = parse_defaults(cfg)
    shortcuts = parse_shortcuts(cfg, defaults)

    if args.shortcut:
        sc = shortcuts.get(args.shortcut)
        if not sc:
            raise SystemExit(f"No such shortcut: {args.shortcut}")
        mp = Path(defaults.mount_root) / sc.id
    else:
        if not args.id:
            raise SystemExit("status requires --id or --shortcut")
        mp = Path(defaults.mount_root) / args.id

    print("mounted" if is_mounted(mp) else "not-mounted")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="sshfsman")
    p.add_argument("--config", help="Override config path (defaults to XDG)")

    sub = p.add_subparsers(dest="cmd", required=True)

    # mount
    pm = sub.add_parser("mount", help="Mount an sshfs target")
    pm.add_argument("--id", help="Mountpoint identifier (directory name)")
    pm.add_argument("--remote", help="Remote like user@host:/absolute/path")
    pm.add_argument("--port", type=int, help="SSH port")
    pm.add_argument("--password", action="store_true", help="Allow password auth (interactive)")
    pm.add_argument("--non-interactive", action="store_true", help="Use sshpass + SSHFSMAN_PASSWORD")
    pm.add_argument("--disable-pubkey", action="store_true", help="Disable pubkey auth")
    pm.add_argument("--insecure-hostkey", action="store_true", help="Disable hostkey checking")
    pm.add_argument("--extra-sshfs-opt", action="append", help="Extra sshfs -o option (repeatable)")
    pm.add_argument("--create-shortcut", metavar="NAME", help="If mount succeeds, create/clobber shortcut NAME")

    # shortcut mode for mount: use positional target (optional)
    pm.add_argument("--shortcut", help="Shortcut name from config")
    pm.add_argument("target", nargs="?", help="Target host/IP or last octet when using default_subnet")

    pm.set_defaults(func=cmd_mount)

    # unmount
    pu = sub.add_parser("unmount", help="Unmount an sshfs mount")
    pu.add_argument("--id", help="Identifier")
    pu.add_argument("--shortcut", help="Shortcut name")
    pu.add_argument("--keep-dir", action="store_true", help="Do not prune empty mountpoint dir")
    pu.set_defaults(func=cmd_unmount)

    # status
    ps = sub.add_parser("status", help="Show mount status")
    ps.add_argument("--id", help="Identifier")
    ps.add_argument("--shortcut", help="Shortcut name")
    ps.set_defaults(func=cmd_status)

    # list-shortcuts
    pl = sub.add_parser("list-shortcuts", help="List configured shortcuts")
    pl.set_defaults(func=cmd_list_shortcuts)

    # delete-shortcut
    pd = sub.add_parser("delete-shortcut", help="Delete a shortcut")
    pd.add_argument("name", help="Shortcut name")
    pd.set_defaults(func=cmd_delete_shortcut)

    # create-shortcut
    pcs = sub.add_parser("create-shortcut", help="Create or update a shortcut")
    pcs.add_argument("name", help="Shortcut name")
    pcs.add_argument("--id", help="Mountpoint id (defaults to shortcut name)")
    pcs.add_argument("--remote-path", required=True, help="Remote path on the host (e.g. /home/user/files)")
    pcs.add_argument("--user", help="Default user for this shortcut")
    pcs.add_argument("--port", type=int, help="SSH port")
    pcs.add_argument("--fixed-host", help="Pin a specific host/IP so mount can omit the target")
    pcs.add_argument("--prefer-password", action="store_true", help="Prefer password auth")
    pcs.add_argument("--disable-pubkey", action="store_true", help="Disable pubkey auth")
    pcs.add_argument("--insecure-hostkey", action="store_true", help="Disable hostkey checking")
    pcs.add_argument("--extra-sshfs-opt", action="append", help="Extra sshfs -o option (repeatable)")
    pcs.set_defaults(func=cmd_create_shortcut)

    # set-default-subnet
    pds = sub.add_parser("set-default-subnet", help="Set defaults.default_subnet (three octets)")
    pds.add_argument("subnet", help="Example: 10.0.20")
    pds.set_defaults(func=cmd_set_default_subnet)

    # list-mounted
    plm = sub.add_parser("list-mounted", help="List sshfs mounts under mount_root")
    plm.add_argument("--all", action="store_true", help="List all sshfs mounts (ignore mount_root)")
    plm.set_defaults(func=cmd_list_mounted)

    # debug-config
    pdc = sub.add_parser("debug-config", help="Print resolved config and mount diagnostics")
    pdc.set_defaults(func=cmd_debug_config)

    # unmount-all
    pua = sub.add_parser("unmount-all", help="Unmount all sshfs mounts under mount_root")
    pua.add_argument("--keep-dir", action="store_true", help="Do not prune empty mountpoint dirs")
    pua.set_defaults(func=cmd_unmount_all)

    return p


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    p = build_parser()
    args = p.parse_args(argv)

    cfg_path = config_path(args.config)
    cfg = load_config(cfg_path)

    try:
        return int(args.func(args, cfg_path, cfg))
    except BrokenPipeError:
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
