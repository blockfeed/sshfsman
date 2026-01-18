# sshfsman

A small, deterministic CLI for managing `sshfs` mounts under a single mount root (default: `/mnt/sshfs`), using XDG config at:

- `~/.config/sshfsman/config.toml`

## Ground truth mount detection (non-negotiable)

A path is considered mounted **only** if:

- `findmnt -T <path>` reports `FSTYPE` exactly `fuse.sshfs`

This single function is used everywhere (mount guard, unmount, unmount-all, list-mounts). Directory existence is not treated as "mounted".

## Requirements

- Linux
- `sshfs` available
- `fuse3` available
- `findmnt` available (util-linux)

## Install (repo)

```bash
python -m venv .venv
. .venv/bin/activate
python -m pip install -U pip
pip install -e .
```

Run as an installed console script (if configured) or via the thin wrapper:

```bash
./sshfsman.py --help
```

## Config

`~/.config/sshfsman/config.toml`

```toml
[config]
mount_root = "/mnt/sshfs"
default_subnet = "192.0.2"

[shortcuts]

[shortcuts."phone"]
id = "phone"
remote = "user@192.0.2.10:/path"
mount_dir = "phone"
```

- `mount_root` is where mounts are created.
- `default_subnet` is used only when a shortcut remote does not contain an IPv4 host and you pass an ID override.
- `shortcuts` map a name to a `remote` and `mount_dir`.

## Commands

### mount

Mount by remote and create/overwrite a shortcut:

```bash
sshfsman mount --remote user@192.0.2.10:/path --create-shortcut phone
```

Mount using a shortcut, overriding the last octet of the shortcut’s IPv4 host:

```bash
sshfsman mount --shortcut phone 138
```

Notes:

- `--create-shortcut NAME` does **not** require `--id`.
- It always sets `id = NAME`.
- It overwrites any existing shortcut with the same name.
- Mounting is **not** blocked by an existing directory; only an actual `fuse.sshfs` mount blocks mounting.

### list-mounts

Lists current `fuse.sshfs` mounts under `mount_root`:

```bash
sshfsman list-mounts
```

Show all system `fuse.sshfs` mounts:

```bash
sshfsman list-mounts --all
```

Emit JSON:

```bash
sshfsman list-mounts --json
```

### unmount

Unmount a single mount by path:

```bash
sshfsman unmount --path /mnt/sshfs/phone
```

Or by shortcut name (maps to its `mount_dir` under `mount_root`):

```bash
sshfsman unmount --shortcut phone
```

Safety:

- Post-unmount cleanup only removes **empty** directories under `mount_root`.
- No recursive delete.

### unmount-all

Unmount everything under `mount_root`:

```bash
sshfsman unmount-all
```

Optionally include mounts outside `mount_root`:

```bash
sshfsman unmount-all --all
```

### debug-config

Print resolved config and shortcuts:

```bash
sshfsman debug-config
```

## License

GPL-3.0-only
