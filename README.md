# sshfsman

`sshfsman` is a small, CLI-first utility for managing `sshfs` mounts in a deterministic and scriptable way.

It exists to remove guesswork around sshfs state, make mounts repeatable, and avoid the usual pile of half-mounted directories and stale mountpoints.

---

## Key Principles

- Deterministic mount detection using `findmnt`
- Scoped by default under a single mount root
- No background state or daemons
- Safe-by-default unmounting

---

## Requirements

Commands required in PATH:

- sshfs
- findmnt (util-linux)
- fusermount3 (preferred) or fusermount

---

## Configuration

Default config path:

~/.config/sshfsman/config.toml

### Example (anonymized)

```toml
[config]
mount_root = "/mnt/sshfs"
default_subnet = "192.0.2"

[shortcuts."example"]
remote = "user@192.0.2.10:/home/user/project"
mount_dir = "project"
options = ["allow_other"]
```

All examples use documentation-only IP ranges and placeholder usernames.

---

## Commands

### mount

```bash
sshfsman mount <shortcut>
sshfsman mount <shortcut> <octet>
sshfsman mount --remote user@host:/path [options]
```

### list-mounts

```bash
sshfsman list-mounts [--all] [--json]
```

Human output:

```
SHORTCUT    SOURCE                           TARGET
example     user@192.0.2.10:/home/...        /mnt/sshfs/project
-           user@198.51.100.5:/srv/...       /mnt/sshfs/other
```

### unmount

```bash
sshfsman unmount <shortcut>
sshfsman unmount --path /mnt/sshfs/<dir>
```

### unmount-all

```bash
sshfsman unmount-all [--all]
```

Empty directories under mount_root are pruned after unmounting.

---

## Safety Notes

- sshfsman never modifies permissions or ownership
- directories outside mount_root are never touched

---

## License

GPLv3
