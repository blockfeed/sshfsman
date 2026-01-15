# sshfsman

Small CLI helper to mount and unmount remote paths over SSH using **sshfs (FUSE)**.

It exists because sometimes you just want:

- a predictable mountpoint: `/mnt/sshfs/<identifier>`
- a one-command mount + one-command unmount
- configurable SSH port
- key auth by default, with optional password auth when you need it

## What it does

- Creates `/mnt/sshfs/<identifier>` if missing
- Mounts a remote spec like `[user@]host:/path` using `sshfs`
- Unmounts cleanly using `fusermount3` (or falls back to `fusermount`)
- Includes `status` to check if a mountpoint is currently mounted

## Requirements

- `sshfs` (and FUSE)
- `fusermount3` (usually via `fuse3`)
- Python 3.8+

Optional (only for non-interactive password mode):

- `sshpass`

## Install dependencies

### Arch Linux

```bash
sudo pacman -S --needed sshfs fuse3
```

### Ubuntu/Debian

```bash
sudo apt-get update
sudo apt-get install -y sshfs fuse3
```

If you want **non-interactive** password mounting:

```bash
# Arch:
# sudo pacman -S --needed sshpass

# Ubuntu/Debian:
sudo apt-get install -y sshpass
```

## Usage

The tool mounts to:

```text
/mnt/sshfs/<identifier>
```

### Mount (key-based auth, default)

```bash
./sshfsman.py mount --id Android --remote user@203.0.113.10:/data
```

### Mount with a custom SSH port

```bash
./sshfsman.py mount --id Android --remote user@203.0.113.10:/data --port 2222
```

### Mount with password auth (interactive)

This will prompt on your terminal.

```bash
./sshfsman.py mount --id Android --remote user@203.0.113.10:/data --password
```

### Mount with password auth (non-interactive)

This requires `sshpass`.

```bash
SSHFSMAN_PASSWORD='your_password_here' \
  ./sshfsman.py mount --id Android --remote user@203.0.113.10:/data --password --non-interactive
```

### Unmount

```bash
./sshfsman.py unmount --id Android
```

### Status

```bash
./sshfsman.py status --id Android
```

## One-liners

Mount:

```bash
id="Android"; remote="user@203.0.113.10:/data"; port=2222; mp="/mnt/sshfs/$id"; sudo install -d "$mp" && sshfs "$remote" "$mp" -o "ssh_command=ssh -p $port" -o reconnect -o ServerAliveInterval=15 -o ServerAliveCountMax=3 -o PasswordAuthentication=yes
```

Unmount:

```bash
fusermount3 -u "/mnt/sshfs/Android" || fusermount -u "/mnt/sshfs/Android"
```

## Notes

- Mounting under `/mnt` typically requires root to create the directory. The script uses `sudo` only for creating the mountpoint directory when needed.
- Non-interactive password mode uses `sshpass`, which is convenient but not great for security. Prefer SSH keys when possible.

## License

GPL-3.0-or-later (see `LICENSE`).
