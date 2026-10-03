# Source installation uses the distribution Python; no virtual environment.
set shell := ["bash", "-euo", "pipefail", "-c"]

default:
    @just --list

# Install distro dependencies, a local wheel, the CLI and the application launcher.
install:
    ./install.sh

# Build the same no-isolation wheel used by the installer.
build:
    /usr/bin/python3 -m build --wheel --no-isolation

# Run Mail Tray from source (requires distro dependencies).
run *args:
    /usr/bin/python3 -m mailtray {{args}}

# Run tests (pytest must be installed on the selected system Python).
test:
    /usr/bin/python3 -m pytest -q
