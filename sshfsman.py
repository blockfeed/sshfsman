#!/usr/bin/env python3
"""sshfsman: tiny sshfs mount/unmount helper.

Goal:
  Mount a remote "[user@]host:/path" via sshfs to /mnt/sshfs/<identifier>
  with optional password auth and configurable port.

Examples:
  # key-based auth (default)
  ./sshfsman.py mount --id Android --remote user@192.168.86.50:/sdcard

  # password auth (interactive prompt)
  ./sshfsman.py mount --id Android --remote user@192.168.86.50:/sdcard --password

  # password auth (non-interactive; requires sshpass)
  SSHFSMAN_PASSWORD='supersecret' ./sshfsman.py mount --id Android --remote user@192.168.86.50:/sdcard --password --non-interactive

  # custom port
  ./sshfsman.py mount --id Android --remote user@192.168.86.50:/sdcard --port 2222

  # unmount
  ./sshfsman.py unmount --id Android

Notes:
  - This script intentionally keeps the sshfs command explicit so you can audit it.
  - For interactive password auth, sshfs/ssh will prompt on your TTY.
  - For non-interactive password auth, install sshpass.
"""

from __future__ import annotations

import argparse
import os
import re
import shlex
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path


DEFAULT_ROOT = Path("/mnt/sshfs")


@dataclass
class MountSpec:
    identifier: str
    remote: str
    port: int | None
    mount_root: Path
    allow_other: bool
    password: bool
    non_interactive: bool
    extra_opts: list[str]

    @property
    def mountpoint(self) -> Path:
        return self.mount_root / self.identifier


def die(msg: str, code: int = 2) -> None:
    print(f"error: {msg}", file=sys.stderr)
    sys.exit(code)


def run(cmd: list[str], check: bool = True) -> subprocess.CompletedProcess:
    # Print the exact command for auditability.
    print("+", " ".join(shlex.quote(c) for c in cmd), file=sys.stderr)
    return subprocess.run(cmd, check=check)


def which_any(names: list[str]) -> str | None:
    for n in names:
        p = shutil.which(n)
        if p:
            return p
    return None


def validate_identifier(s: str) -> str:
    # Keep it safe for filesystem paths.
    if not re.fullmatch(r"[A-Za-z0-9._-]+", s):
        die("--id must match [A-Za-z0-9._-]+ (example: Android, slowpoke, phone_01)")
    return s


def ensure_tools(password: bool, non_interactive: bool) -> tuple[str, str]:
    sshfs = which_any(["sshfs"])
    if not sshfs:
        die("sshfs not found. Install it (Arch: sshfs; Debian/Ubuntu: sshfs)")

    fusermount = which_any(["fusermount3", "fusermount"])
    if not fusermount:
        die("fusermount not found. Install fuse3 (often provides fusermount3)")

    if password and non_interactive and not shutil.which("sshpass"):
        die("--non-interactive requires sshpass (or drop --non-interactive for TTY prompting)")

    return sshfs, fusermount


def is_mounted(mountpoint: Path) -> bool:
    # Cheap check: /proc/mounts line contains mountpoint.
    try:
        with open("/proc/mounts", "r", encoding="utf-8") as f:
            mp = str(mountpoint)
            for line in f:
                # mountpoint is 2nd field (space separated), but may have escapes.
                if f" {mp} " in line:
                    return True
    except FileNotFoundError:
        # Non-Linux: fall back to mountpoint -q
        pass

    mp_tool = shutil.which("mountpoint")
    if mp_tool:
        r = subprocess.run([mp_tool, "-q", str(mountpoint)], check=False)
        return r.returncode == 0

    return False


def build_sshfs_cmd(sshfs: str, spec: MountSpec) -> list[str]:
    cmd: list[str] = []

    if spec.password and spec.non_interactive:
        pw = os.environ.get("SSHFSMAN_PASSWORD")
        if not pw:
            die("SSHFSMAN_PASSWORD env var is required for --non-interactive")
        cmd += ["sshpass", "-e"]  # reads password from SSHFSMAN_PASSWORD

    cmd += [sshfs, spec.remote, str(spec.mountpoint)]

    # Core options
    opts: list[str] = []
    if spec.port is not None:
        # sshfs expects -p via ssh_command
        opts += [f"ssh_command=ssh -p {spec.port}"]

    # Allow password auth if requested (ssh might still prefer keys unless you disable)
    if spec.password:
        opts += ["PasswordAuthentication=yes", "PubkeyAuthentication=no"]

    if spec.allow_other:
        opts += ["allow_other"]

    # Useful default ergonomics
    opts += [
        "reconnect",
        "ServerAliveInterval=15",
        "ServerAliveCountMax=3",
        "StrictHostKeyChecking=accept-new",
        "UserKnownHostsFile=/etc/ssh/ssh_known_hosts",  # still consult per-user known_hosts too
    ]

    # User-provided extra opts (raw strings)
    opts += spec.extra_opts

    # Expand into repeated -o args
    for o in opts:
        cmd += ["-o", o]

    return cmd


def do_mount(spec: MountSpec) -> None:
    sshfs, _ = ensure_tools(spec.password, spec.non_interactive)

    spec.mount_root.mkdir(parents=True, exist_ok=True)
    spec.mountpoint.mkdir(parents=True, exist_ok=True)

    if is_mounted(spec.mountpoint):
        die(f"already mounted: {spec.mountpoint}")

    cmd = build_sshfs_cmd(sshfs, spec)

    # Interactive password prompting requires a TTY; refuse if stdin isn't a TTY.
    if spec.password and not spec.non_interactive and not sys.stdin.isatty():
        die("password mode requires a TTY (or use --non-interactive + SSHFSMAN_PASSWORD)")

    run(cmd, check=True)

    # Verify
    if not is_mounted(spec.mountpoint):
        die(f"mount command succeeded but mount not detected at {spec.mountpoint}", code=1)


def do_unmount(mountpoint: Path) -> None:
    _, fusermount = ensure_tools(password=False, non_interactive=False)

    if not mountpoint.exists():
        die(f"mountpoint does not exist: {mountpoint}")

    if not is_mounted(mountpoint):
        die(f"not mounted: {mountpoint}")

    # Prefer fusermount(3) -u
    run([fusermount, "-u", str(mountpoint)], check=True)

    if is_mounted(mountpoint):
        die(f"unmount command succeeded but still mounted: {mountpoint}", code=1)


def main() -> None:
    p = argparse.ArgumentParser(
        prog="sshfsman",
        description="Mount/unmount sshfs targets under /mnt/sshfs/<identifier>.",
        formatter_class=argparse.RawTextHelpFormatter,
    )

    sub = p.add_subparsers(dest="cmd", required=True)

    pm = sub.add_parser("mount", help="Mount a remote via sshfs")
    pm.add_argument("--id", required=True, type=validate_identifier, help="Identifier (directory name)")
    pm.add_argument("--remote", required=True, help='Remote spec: "[user@]host:/path"')
    pm.add_argument("--port", type=int, default=None, help="SSH port (default: 22)")
    pm.add_argument("--mount-root", default=str(DEFAULT_ROOT), help=f"Mount root (default: {DEFAULT_ROOT})")
    pm.add_argument("--allow-other", action="store_true", help="Pass -o allow_other (requires user_allow_other in /etc/fuse.conf)")

    # Password auth modes
    pm.add_argument(
        "--password",
        action="store_true",
        help="Enable password authentication (interactive prompt unless --non-interactive)",
    )
    pm.add_argument(
        "--non-interactive",
        action="store_true",
        help="Use sshpass and SSHFSMAN_PASSWORD env var (no prompt)",
    )

    pm.add_argument(
        "-o",
        dest="extra_opts",
        action="append",
        default=[],
        help="Extra sshfs -o options (repeatable). Example: -o idmap=user",
    )

    pu = sub.add_parser("unmount", help="Unmount an identifier")
    pu.add_argument("--id", required=True, type=validate_identifier, help="Identifier to unmount")
    pu.add_argument("--mount-root", default=str(DEFAULT_ROOT), help=f"Mount root (default: {DEFAULT_ROOT})")

    ps = sub.add_parser("status", help="Show whether an identifier is mounted")
    ps.add_argument("--id", required=True, type=validate_identifier, help="Identifier to check")
    ps.add_argument("--mount-root", default=str(DEFAULT_ROOT), help=f"Mount root (default: {DEFAULT_ROOT})")

    args = p.parse_args()

    mount_root = Path(getattr(args, "mount_root", str(DEFAULT_ROOT)))

    if args.cmd == "mount":
        if args.non_interactive and not args.password:
            die("--non-interactive implies --password (add --password)")
        spec = MountSpec(
            identifier=args.id,
            remote=args.remote,
            port=args.port,
            mount_root=mount_root,
            allow_other=args.allow_other,
            password=args.password,
            non_interactive=args.non_interactive,
            extra_opts=args.extra_opts,
        )
        do_mount(spec)
        print(str(spec.mountpoint))
        return

    if args.cmd == "unmount":
        mp = mount_root / args.id
        do_unmount(mp)
        print(str(mp))
        return

    if args.cmd == "status":
        mp = mount_root / args.id
        print("mounted" if is_mounted(mp) else "not-mounted")
        print(str(mp))
        return


if __name__ == "__main__":
    main()
