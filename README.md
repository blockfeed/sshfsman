# sshfsman

sshfsman is a command-line utility for managing sshfs mounts.

It is intended for workflows where remote filesystems are mounted repeatedly, connection parameters may change over time, and mounts must be created and removed in a predictable way.

---

## Usage

    sshfsman <command> [options]

Run any command with `--help` to see detailed usage and examples.

---

## Common commands

Mount a configured shortcut:

    sshfsman mount phone

Mount the same shortcut using a different address within the configured subnet:

    sshfsman mount phone 138

Create or update a shortcut:

    sshfsman create-shortcut phone --remote user@192.0.2.10:/path

Unmount all sshfs mounts under the configured mount root:

    sshfsman unmount-all

---

## Description

sshfsman manages sshfs mounts under a single mount root (default: /mnt/sshfs).  
Shortcut definitions allow the exact sshfs invocation to be stored and reused.

The tool is designed to avoid implicit behavior. All mounts are created explicitly, detected reliably, and removed safely.

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

Example configuration:

    [config]
    mount_root = "/mnt/sshfs"
    default_subnet = "192.0.2"

    [shortcuts]

    [shortcuts."phone"]
    remote = "user@192.0.2.10:/path"
    mount_dir = "SDCard"

---

## Shortcuts

A shortcut defines how a remote filesystem should be mounted.

Shortcuts may include:
- remote path
- SSH port
- identity file
- sshfs options
- reconnect behavior

Command-line options override stored values.

Create or replace a shortcut:

    sshfsman create-shortcut phone --remote user@192.0.2.10:/path

Mount a shortcut:

    sshfsman mount phone

---

## Subnet-based address override

When mounting a shortcut, an optional numeric argument may be provided:

    sshfsman mount phone 138

If `default_subnet` is configured, the numeric value is treated as the final IPv4 octet and combined with that subnet.

This is intended for hosts that are frequently readdressed within the same network.

---

## sshfs options and SSH options

sshfs options and SSH client options are separate.

sshfs options affect filesystem behavior and are passed directly:

    sshfsman mount phone -o allow_other

SSH client options must be passed via `ssh_command`:

    sshfsman mount phone \
      -o "ssh_command=ssh -o KexAlgorithms=+diffie-hellman-group14-sha1"

Passing raw SSH options directly to sshfs will result in an error.

---

## Listing mounts

List sshfs mounts under the configured mount root:

    sshfsman list-mounts

List all sshfs mounts on the system:

    sshfsman list-mounts --all

---

## Unmounting

Unmount all sshfs mounts under the configured mount root:

    sshfsman unmount-all

Unmount all sshfs mounts on the system:

    sshfsman unmount-all --all

The `--all` flag ignores the configured mount root and should be used with care.

---

## Help

All commands provide usage information and examples via `--help`.

The `--help` output is intended to be sufficient documentation for pipx-installed usage.

---

## License

GPL-3.0-only
