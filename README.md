# sshfsman

`sshfsman` is a command-line tool for managing `sshfs` mounts in a consistent, repeatable way.

It is intended for workflows where the same remote filesystems are mounted frequently, sometimes with non-default ports or options, and where reliability and clarity matter more than convenience shortcuts or implicit behavior.

---

## Motivation

I use `sftpman` regularly for interactive file access. In practice, there are times when a full filesystem mount is the better tool, for example when copying or syncing larger sets of files.

A common case is mounting storage exposed by a mobile device. Because modern devices often use randomized MAC addresses, the IP address can change between connections. Hard-coded mounts or shell aliases tend to break when that happens.

`sshfsman` exists to make these mounts explicit, repeatable, and easy to recreate even when connection details change, without relying on heuristics or manual cleanup.

---

## What sshfsman does

- Manages `sshfs` mounts under a single mount root (default: `/mnt/sshfs`)
- Provides named shortcuts for commonly used remotes
- Saves the full mount invocation with each shortcut:
  - SSH port
  - identity file
  - sshfs options
  - read-only flag
  - reconnect behavior
- Reuses those saved parameters automatically on future mounts
- Exposes explicit commands for listing, unmounting, and cleanup
- Avoids guessing about mount state

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

You can also run the tool directly from the repository:

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

---

## sshfs options vs SSH options

This distinction matters.

### sshfs options

These options are parsed directly by `sshfs` and control how the filesystem is mounted:

```bash
-o allow_other
-o ro
-o compression=no
```

Example:

```bash
sshfsman mount \
  --remote user@192.0.2.10:/path \
  -o allow_other
```

### SSH options

SSH client options control the underlying SSH connection. They **must** be passed via `sshfs` using `ssh_command`.

Correct pattern:

```bash
-o "ssh_command=ssh <ssh-options>"
```

Example using a non-default key exchange algorithm:

```bash
sshfsman mount \
  --remote user@192.0.2.10:/path \
  -o "ssh_command=ssh -o KexAlgorithms=+diffie-hellman-group14-sha1"
```

Raw SSH options such as `StrictHostKeyChecking` are **not** valid sshfs options and will fail if passed directly.

---

## Shortcuts and saved invocation

When you create a shortcut using:

```bash
sshfsman mount --create-shortcut phone --remote user@192.0.2.10:/path
```

or:

```bash
sshfsman create-shortcut phone --remote user@192.0.2.10:/path
```

sshfsman records how the mount was created, not just where it points. Those parameters are reused automatically when mounting via the shortcut.

---

## Commands

### mount

```bash
sshfsman mount \
  --remote user@192.0.2.10:/path \
  --port 2200 \
  --create-shortcut phone
```

```bash
sshfsman mount --shortcut phone
```

```bash
sshfsman mount --shortcut phone 138
```

---

### list-mounts

```bash
sshfsman list-mounts
sshfsman list-mounts --all
```

---

### unmount

```bash
sshfsman unmount --shortcut phone
sshfsman unmount --path /mnt/sshfs/SDCard
```

---

### unmount-all

```bash
sshfsman unmount-all
```

Unmounts all sshfs mounts **under the configured mount root**.  
This is the normal, safe cleanup command.

```bash
sshfsman unmount-all --all
```

Unmounts **all sshfs mounts on the system**, including those outside the mount root.

This is intended as a recovery or cleanup tool and should be used with care.

---

### status

```bash
sshfsman status --shortcut phone
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

```bash
sshfsman debug-config
```

---

## License

GPL-3.0-only
