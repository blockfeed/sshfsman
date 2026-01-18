# sshfsman

CLI wrapper around `sshfs`/FUSE that mounts remotes under:

- `/mnt/sshfs/<id>` (default)

It is intentionally CLI-first and auditable. I really love **sftpman**, but I wanted a tiny tool
that is:

- straightforward to script
- friendly to devices whose IP changes often (e.g. Android phones using MAC privacy/randomization)
- able to mount by "shortcut name + last IP octet"

## Features

- `mount`, `unmount`, `status`
- safe mountpoint creation on mount
- safe mountpoint pruning on unmount (only if unmounted + empty)
- XDG config: `~/.config/sshfsman/config.toml` (or `$XDG_CONFIG_HOME/...`)
- shortcuts with default subnet expansion
- shortcut management:
  - `list-shortcuts`
  - `create-shortcut`
  - `delete-shortcut`
  - `mount ... --create-shortcut NAME` (create/clobber on successful mount)
- bulk ops:
  - `list-mounted`
  - `unmount-all`

## Install

### Option A: pipx (recommended)

```bash
pipx install git+https://github.com/<you>/sshfsman.git
sshfsman --help
```

### Option B: run from a git checkout

```bash
./sshfsman.py --help
```

## Requirements

- `sshfs`
- `fuse3` (provides `fusermount3` on most distros)
- optional: `sshpass` (only for non-interactive password auth)

## Configuration (XDG)

Config is loaded from:

1. `$XDG_CONFIG_HOME/sshfsman/config.toml`
2. `~/.config/sshfsman/config.toml`

Start from the example:

```bash
mkdir -p ~/.config/sshfsman
cp config.example.toml ~/.config/sshfsman/config.toml
```

Example (`config.toml`):

```toml
[defaults]
mount_root = "/mnt/sshfs"
default_port = 22
default_subnet = "10.0.20"
default_user = "user"

[shortcuts.my-phone]
id = "my-phone"
remote_path = "/home/user/files"
port = 2222
prefer_password = true
# disable_pubkey = true
# insecure_hostkey = true
```

## Usage

### Simple mount

```bash
sshfsman mount --id phone --remote user@192.0.2.10:/sdcard
```

### Password auth

Interactive prompt:

```bash
sshfsman mount --id phone --remote user@192.0.2.10:/sdcard --password
```

Non-interactive (requires `sshpass`):

```bash
SSHFSMAN_PASSWORD='...' sshfsman mount --id phone --remote user@192.0.2.10:/sdcard --password --non-interactive
```

### Shortcuts (dynamic IP by last octet)

Mount using a shortcut name + last octet in `defaults.default_subnet`:

```bash
sshfsman mount --shortcut my-phone 138
```

Unmount using a shortcut:

```bash
sshfsman unmount --shortcut my-phone
```

List shortcuts:

```bash
sshfsman list-shortcuts
```

### Create a shortcut from a successful mount

This does **not** require `--id`. If omitted, `id` defaults to the shortcut name.

```bash
sshfsman mount \
  --remote user@192.0.2.10:/home/user/files \
  --port 2222 \
  --create-shortcut my-phone
```

Later, mount it at a different host in the configured subnet:

```bash
sshfsman mount --shortcut my-phone 138
```

### Explicitly manage shortcuts

Create/update:

```bash
sshfsman create-shortcut my-phone \
  --id my-phone \
  --remote-path /home/user/files \
  --port 2222 \
  --prefer-password
```

Delete:

```bash
sshfsman delete-shortcut my-phone
```

### Set defaults.default_subnet

```bash
sshfsman set-default-subnet 10.0.20
```

### List mounted sshfs under mount_root

```bash
sshfsman list-mounted
```

### Unmount all sshfs under mount_root

```bash
sshfsman unmount-all
```

## Safety model

- Never deletes remote content (sshfs client-side only)
- Pruning uses `rmdir()` only and only when:
  - the mount is gone
  - the directory is empty
  - the path is inside `mount_root`

## License

GPL-3.0-only. See `LICENSE`.
