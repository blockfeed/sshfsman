# sshfsman

sshfsman is a command-line utility for managing sshfs mounts.

It is designed for workflows that require repeatable mounts and explicit handling of connection parameters that may change over time.

---

## SYNOPSIS

    sshfsman <command> [options]

---

## DESCRIPTION

sshfsman manages sshfs mounts under a single mount root (default: /mnt/sshfs) and provides a shortcut mechanism for recreating mounts in a consistent way.

It is intended for environments where:

- The same remote filesystems are mounted repeatedly
- Host addressing is not static
- Mount behavior must be explicit and reproducible
- Cleanup must be safe and predictable

---

## REQUIREMENTS

- Linux
- sshfs
- fuse3
- findmnt (util-linux)

---

## INSTALLATION

### Using pipx

    pipx install .

From a local checkout:

    pipx install --editable .

---

## CONFIGURATION

Configuration is read from:

    ~/.config/sshfsman/config.toml

Example:

    [config]
    mount_root = "/mnt/sshfs"
    default_subnet = "192.0.2"

    [shortcuts]

    [shortcuts."phone"]
    remote = "user@192.0.2.10:/path"
    mount_dir = "SDCard"

---

## SHORTCUTS

A shortcut defines how a remote filesystem should be mounted.

Create or update a shortcut:

    sshfsman create-shortcut phone --remote user@192.0.2.10:/path

Mount a shortcut:

    sshfsman mount phone

---

## SUBNET-BASED HOST OVERRIDES

When mounting a shortcut, a numeric argument may be provided:

    sshfsman mount phone 138

If default_subnet is set, the numeric value is treated as the final IPv4 octet and combined with the configured subnet.

---

## SSHFS OPTIONS VS SSH OPTIONS

sshfs options affect filesystem behavior and are passed directly:

    sshfsman mount phone -o allow_other

SSH client options must be passed via ssh_command:

    sshfsman mount phone \
      -o "ssh_command=ssh -o KexAlgorithms=+diffie-hellman-group14-sha1"

---

## COMMANDS

- mount
- list-mounts
- unmount
- unmount-all
- list-shortcuts
- create-shortcut
- delete-shortcut
- set-default-subnet
- debug-config

Each command provides usage information via --help.

---

## LICENSE

GPL-3.0-only
