# sshfsman

`sshfsman` is a small command-line tool for managing `sshfs` mounts in a consistent and repeatable way.

It is designed for situations where you frequently mount the same remote filesystems, sometimes with non-default options, and want a simple way to reconnect, unmount, and clean up without retyping commands or debugging why something failed.

---

## Motivation

I like `sftpman` a lot and use it regularly for interactive file access.

Sometimes, though, I just need a filesystem mount. A common example is copying files from my phone. Because modern devices use anonymized MAC addresses, the phone’s IP address can change between connections. That makes hard-coded mounts annoying.

`sshfsman` solves this by letting you define shortcuts for mounts and reuse them even when the IP changes, without guessing or silently doing the wrong thing.

---

## What sshfsman does

- Manages `sshfs` mounts under a single mount root (default: `/mnt/sshfs`)
- Lets you define named shortcuts for common remotes
- Saves the full mount invocation with the shortcut:
  - SSH port
  - identity file
  - sshfs options
  - read-only flag
  - reconnect behavior
- Reuses those saved parameters automatically on future mounts
- Provides explicit commands for listing, unmounting, and cleanup
- Avoids heuristic or filesystem-based guesses about mount state

---

## Requirements

- Linux
- `sshfs` and `fuse3`
- `findmnt` (from util-linux)

---

## Installation

### Using pipx (recommended)

```bash
pipx install .
```

From a local clone:

```bash
pipx install --editable .
```

### Using a virtual environment

```bash
python -m venv .venv
. .venv/bin/activate
pip install -e .
```

You can also run it directly from the repository:

```bash
./sshfsman.py --help
```

---

## Configuration

Configuration is stored at:

```
~/.config/sshfsman/config.toml
```

Example:

```toml
[config]
mount_root = "/mnt/sshfs"
default_subnet = "192.0.2"

[shortcuts]

[shortcuts."phone"]
id = "phone"
remote = "user@192.0.2.10:/path"
mount_dir = "SDCard"

# Saved mount invocation (optional)
port = 2200
identity = "/home/user/.ssh/id_ed25519"
options = [
  "allow_other",
]
readonly = false
no_reconnect_defaults = false
```

### Configuration notes

- `mount_root` controls where sshfsman creates mount directories.
- `default_subnet` is optional and only used when overriding an ID on a shortcut.
- For shortcuts, only `remote` is required. All other fields are optional.

---

## Shortcuts and saved invocation

When you create a shortcut using either:

```bash
sshfsman mount --create-shortcut phone --remote user@192.0.2.10:/path
```

or:

```bash
sshfsman create-shortcut phone --remote user@192.0.2.10:/path
```

sshfsman records how the mount was created, not just where it points:

- SSH port
- identity file
- sshfs options
- read-only flag
- reconnect defaults

Later, when you run:

```bash
sshfsman mount --shortcut phone
```

those saved parameters are reused automatically. Command-line options always override what is saved.

This makes reconnecting reliable when the remote host or network conditions change.

---

## Commands

### mount

Mount a remote and create or overwrite a shortcut:

```bash
sshfsman mount \
  --remote user@192.0.2.10:/path \
  --port 2200 \
  --create-shortcut phone
```

Mount using an existing shortcut:

```bash
sshfsman mount --shortcut phone
```

Override the last octet when applicable:

```bash
sshfsman mount --shortcut phone 138
```

Notes:

- Existing directories do not block mounting.
- Only an actual sshfs mount prevents remounting.

---

### list-mounts

List sshfs mounts under the mount root:

```bash
sshfsman list-mounts
```

List all sshfs mounts on the system:

```bash
sshfsman list-mounts --all
```

---

### unmount

Unmount by shortcut:

```bash
sshfsman unmount --shortcut phone
```

Unmount by path:

```bash
sshfsman unmount --path /mnt/sshfs/SDCard
```

Cleanup behavior:

- Only empty directories are removed
- Cleanup is limited to `mount_root`
- No recursive deletion

---

### unmount-all

Unmount everything under the mount root:

```bash
sshfsman unmount-all
```

Include sshfs mounts outside the mount root:

```bash
sshfsman unmount-all --all
```

---

### status

Check the status of a shortcut:

```bash
sshfsman status --shortcut phone
```

List status for all shortcuts:

```bash
sshfsman status
```

---

### list-shortcuts

```bash
sshfsman list-shortcuts
sshfsman list-shortcuts --json
```

---

### create-shortcut

Create or update a shortcut explicitly:

```bash
sshfsman create-shortcut \
  phone \
  --remote user@192.0.2.10:/path \
  --port 2200 \
  -o allow_other
```

---

### delete-shortcut

```bash
sshfsman delete-shortcut phone
```

---

### set-default-subnet

```bash
sshfsman set-default-subnet 192.0.2
```

---

### debug-config

Show the resolved configuration and detected mounts:

```bash
sshfsman debug-config
```

---

## License

GPL-3.0-only
