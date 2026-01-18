# sshfsman

A deterministic CLI for managing `sshfs` mounts under a single mount root (default: `/mnt/sshfs`).

Config lives at:

- `~/.config/sshfsman/config.toml`

## Ground truth mount detection (single source)

A path is considered mounted **only** if:

- `findmnt -T <path>` reports `FSTYPE` exactly `fuse.sshfs`

This is the only mount detection used by:

- mount guard
- unmount
- unmount-all
- list-mounts
- status

No directory-exists checks. No `mountpoint -q`. No `/proc/mounts` scraping.

## Requirements

- Linux
- `sshfs` + `fuse3`
- `findmnt` (util-linux)

## Install (repo)

```bash
python -m venv .venv
. .venv/bin/activate
python -m pip install -U pip
pip install -e .
```

Run via wrapper:

```bash
./sshfsman.py --help
```

## Shortcut invocation is saved (port, options, identity)

When you create a shortcut via `mount --create-shortcut NAME` or `create-shortcut`, sshfsman saves the mount invocation parameters into the shortcut:

- `port`
- `identity`
- `options` (sshfs `-o` values)
- `readonly`
- `no_reconnect_defaults`

When you later run `sshfsman mount --shortcut NAME ...`, those saved parameters are applied automatically. CLI flags override saved values.

## Config

Example `~/.config/sshfsman/config.toml`:

```toml
[config]
mount_root = "/mnt/sshfs"
default_subnet = "192.0.2"

[shortcuts]

[shortcuts."phone"]
id = "phone"
remote = "user@192.0.2.10:/path"
mount_dir = "phone"
port = 2222
identity = "/home/user/.ssh/id_ed25519"
options = [
  "allow_other",
]
readonly = false
no_reconnect_defaults = false
```

## Commands

### mount

Mount by remote and create or overwrite a shortcut named `phone` (port saved):

```bash
sshfsman mount --remote user@192.0.2.10:/path --port 2222 --create-shortcut phone
```

Mount using that shortcut (port reused automatically), overriding the last octet:

```bash
sshfsman mount --shortcut phone 138
```

Rules:

- `--create-shortcut NAME` does **not** require `--id`.
- It always sets `id = NAME`.
- It overwrites an existing shortcut with the same name.
- Mounting is **not** blocked by an existing directory; only an actual `fuse.sshfs` mount blocks mounting.

Useful options:

```bash
sshfsman mount --remote user@192.0.2.10:/path --mount-dir phone --readonly
sshfsman mount --remote user@192.0.2.10:/path -p 2222 -i ~/.ssh/id_ed25519
sshfsman mount --remote user@192.0.2.10:/path -o allow_other -o Compression=no
```

### list-mounts

List current `fuse.sshfs` mounts under `mount_root`:

```bash
sshfsman list-mounts
```

List all system `fuse.sshfs` mounts:

```bash
sshfsman list-mounts --all
```

Emit JSON:

```bash
sshfsman list-mounts --json
```

### unmount

Unmount by path:

```bash
sshfsman unmount --path /mnt/sshfs/phone
```

Or by shortcut name:

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

Also unmount `fuse.sshfs` mounts outside `mount_root`:

```bash
sshfsman unmount-all --all
```

### status

Check a single shortcut:

```bash
sshfsman status --shortcut phone
```

Check a path:

```bash
sshfsman status --path /mnt/sshfs/phone
```

List all shortcuts with status:

```bash
sshfsman status
```

### list-shortcuts

```bash
sshfsman list-shortcuts
sshfsman list-shortcuts --json
```

### create-shortcut

Create or overwrite a shortcut explicitly (including port/options):

```bash
sshfsman create-shortcut phone --remote user@192.0.2.10:/path --port 2222 -o allow_other
```

### delete-shortcut

```bash
sshfsman delete-shortcut phone
```

### set-default-subnet

```bash
sshfsman set-default-subnet 192.0.2
```

### debug-config

Print resolved config and mount diagnostics under `mount_root`:

```bash
sshfsman debug-config
```

## License

GPL-3.0-only
