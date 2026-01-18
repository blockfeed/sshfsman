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

# Saved invocation parameters (optional)
port = 2222
identity = "/home/user/.ssh/id_ed25519"
options = [
  "allow_other",
]
readonly = false
no_reconnect_defaults = false
```

### Config keys

- `config.mount_root`
  - Mount root for all sshfs mounts managed by sshfsman.
  - Default: `/mnt/sshfs`
- `config.default_subnet`
  - Optional, three octets (example: `192.0.2`)
  - Used only when a shortcut remote does **not** contain an IPv4 host and you pass an ID override.
- `shortcuts."<NAME>"`
  - `remote` (required): `user@host:/path`
  - `mount_dir` (optional): directory name under `mount_root`
  - Saved invocation parameters (optional): `port`, `identity`, `options`, `readonly`, `no_reconnect_defaults`

## Shortcut invocation is saved (port, options, identity)

When you create a shortcut via:

- `sshfsman mount --create-shortcut NAME ...`, or
- `sshfsman create-shortcut NAME ...`

sshfsman saves the mount invocation parameters into that shortcut:

- `port`
- `identity`
- `options` (sshfs `-o` values)
- `readonly`
- `no_reconnect_defaults`

Later, when you run:

- `sshfsman mount --shortcut NAME ...`

those saved parameters are applied automatically. CLI flags override saved values.

This avoids “works once, fails later” when the original mount used a non-default port or other options.

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

Note: `list-mounted` is removed (hard break). Use `list-mounts`.

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

## Troubleshooting

### “already mounted” when nothing is mounted

sshfsman only treats a path as mounted if `findmnt -T <path>` reports `FSTYPE=fuse.sshfs`.
Verify directly:

```bash
findmnt -T /mnt/sshfs/phone -o TARGET,FSTYPE,SOURCE
```

### “Connection reset by peer” after switching to a shortcut

If the original mount used a non-default port (or other options) and the shortcut did not save them, reconnects can fail.

Fix: recreate or overwrite the shortcut while specifying the working invocation:

```bash
sshfsman mount --remote user@192.0.2.10:/path --port 2222 --create-shortcut phone
```

Then use:

```bash
sshfsman mount --shortcut phone 138
```

## License

GPL-3.0-only
