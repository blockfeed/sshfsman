# sshfsman

`sshfsman` is a small CLI I use to manage `sshfs` mounts without thinking about them too hard.

It exists because I mount the same few remote filesystems over and over, sometimes on non-default ports, sometimes with a pile of options, and I got tired of retyping commands or guessing why a reconnect failed. This tool makes those mounts repeatable, predictable, and easy to clean up.

It is intentionally boring software.

---

## What it does

- Manages `sshfs` mounts under a single mount root (default: `/mnt/sshfs`)
- Lets you define **shortcuts** for common remotes
- Saves the full mount invocation with the shortcut (port, options, identity, etc.)
- Reuses that invocation automatically on future mounts
- Provides clean unmounting and safe cleanup
- Never guesses whether something is mounted

---

## Requirements

- Linux
- `sshfs` and `fuse3`
- `findmnt` (from util-linux)

---

## Installation

### With pipx (recommended)

```bash
pipx install .
```

or from a cloned repo:

```bash
pipx install --editable .
```

### With a virtualenv

```bash
python -m venv .venv
. .venv/bin/activate
pip install -e .
```

You can also run it directly via the wrapper:

```bash
./sshfsman.py --help
```

---

## Configuration

Config lives at:

```
~/.config/sshfsman/config.toml
```

Example:

```toml
[config]
mount_root = "/mnt/sshfs"
default_subnet = "192.0.2"

[shortcuts]

[shortcuts."android"]
id = "android"
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

### Notes

- `mount_root` is where all mounts live
- `default_subnet` is optional and only used when you override an ID on a shortcut
- Everything under a shortcut is optional except `remote`

---

## Shortcuts save how you mounted things

When you create a shortcut using either:

```bash
sshfsman mount --create-shortcut android --remote user@192.0.2.10:/path
```

or:

```bash
sshfsman create-shortcut android --remote user@192.0.2.10:/path
```

`sshfsman` saves **how** you mounted it, not just where:

- SSH port
- Identity file
- sshfs `-o` options
- Read-only flag
- Reconnect behavior

Later, when you run:

```bash
sshfsman mount --shortcut android
```

you get the *same mount* again, without retyping anything.

This is the entire point of the tool.

---

## Commands

### mount

Mount a remote and create or overwrite a shortcut:

```bash
sshfsman mount \
  --remote user@192.0.2.10:/path \
  --port 2200 \
  --create-shortcut android
```

Mount using an existing shortcut:

```bash
sshfsman mount --shortcut android
```

Override the last octet when applicable:

```bash
sshfsman mount --shortcut android 138
```

Notes:

- Existing directories do **not** block mounting
- Only an actual sshfs mount blocks remounting

---

### list-mounts

List current sshfs mounts under the mount root:

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
sshfsman unmount --shortcut android
```

Or by path:

```bash
sshfsman unmount --path /mnt/sshfs/SDCard
```

Cleanup rules:

- Only empty directories are removed
- Only under `mount_root`
- Nothing recursive, nothing destructive

---

### unmount-all

Unmount everything under the mount root:

```bash
sshfsman unmount-all
```

Include mounts outside the root:

```bash
sshfsman unmount-all --all
```

---

### status

Check one shortcut:

```bash
sshfsman status --shortcut android
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
  android \
  --remote user@192.0.2.10:/path \
  --port 2200 \
  -o allow_other
```

---

### delete-shortcut

```bash
sshfsman delete-shortcut android
```

---

### set-default-subnet

```bash
sshfsman set-default-subnet 192.0.2
```

---

### debug-config

Dump resolved config and current mounts:

```bash
sshfsman debug-config
```

This is mostly here for when something feels off and you want to see exactly what the tool thinks.

---

## Why this exists

I like `sshfs`. I just don’t like babysitting it.

`sshfsman` exists to make mounts repeatable, obvious, and disposable. It does not try to be clever, magical, or universal. It just does the same thing every time and gets out of the way.

---

## Relationship to sftpman

If you’ve used **sftpman**, this should feel familiar.

`sshfsman` is the same idea applied to `sshfs` mounts instead of interactive SFTP sessions:
shortcuts, saved connection details, predictable behavior, and a refusal to guess or be clever.

`sftpman` made jumping into remote filesystems painless.
`sshfsman` exists because I wanted the *mounted* version of that workflow, with the same philosophy.


## License

GPL-3.0-only
