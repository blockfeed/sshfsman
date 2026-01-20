# sshfsman

sshfsman is a command-line utility for managing sshfs mounts.

It is intended for workflows where remote filesystems are mounted repeatedly, connection parameters may change over time, and mounts must be created and removed in a predictable way.

---

## Usage

    sshfsman <command> [options]

Run any command with `--help` for detailed usage and examples.

---

## Installation

sshfsman is typically installed using pipx.

    pipx install .

From a local checkout:

    pipx install --editable .

---

## Configuration

Configuration is read from:

    ~/.config/sshfsman/config.toml

Example:

    [config]
    mount_root = "/mnt/sshfs"
    default_subnet = "192.0.2"

    [shortcuts]
    [shortcuts."phone"]
    remote = "user@192.0.2.10:/path"
    mount_dir = "phone"

---

## Commands

### mount

Mount a configured shortcut:

    sshfsman mount phone

Mount using a subnet-based address override:

    sshfsman mount phone 138

The numeric argument is treated as the last IPv4 octet and combined with `default_subnet`.

Mount directly from a remote and save as a shortcut:

    sshfsman mount --remote user@192.0.2.10:/path --create-shortcut phone

When creating a shortcut during a remote mount, the mount directory defaults to the shortcut name unless `--mount-dir` is provided.

---

### list-mounts

List sshfs mounts under the configured mount root:

    sshfsman list-mounts

List all sshfs mounts on the system:

    sshfsman list-mounts --all

---

### unmount

Unmount a single shortcut or mount path:

    sshfsman unmount phone
    sshfsman unmount /mnt/sshfs/phone

---

### unmount-all

Unmount all sshfs mounts under the configured mount root:

    sshfsman unmount-all

Unmount all sshfs mounts on the system:

    sshfsman unmount-all --all

The `--all` flag ignores `mount_root` and should be used deliberately.

---

### status

Show sshfs mount status:

    sshfsman status
    sshfsman status phone

---

### list-shortcuts

List configured shortcuts:

    sshfsman list-shortcuts

---

### create-shortcut

Create or update a shortcut:

    sshfsman create-shortcut phone --remote user@192.0.2.10:/path

---

### delete-shortcut

Delete a shortcut:

    sshfsman delete-shortcut phone

---

### set-default-subnet

Set the default subnet used for positional mount overrides:

    sshfsman set-default-subnet 192.0.2

---

### debug-config

Print the resolved configuration and shortcuts:

    sshfsman debug-config

---

## sshfs options vs SSH options

sshfs options affect filesystem behavior and are passed directly:

    sshfsman mount phone -o allow_other

SSH client options must be passed via `ssh_command`:

    sshfsman mount phone \
      -o "ssh_command=ssh -o KexAlgorithms=+diffie-hellman-group14-sha1"

Passing raw SSH options directly to sshfs will result in an error.

---

## License

GPL-3.0-only
