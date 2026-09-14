#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PYTHON="python3"
INSTALL_DIR="$HOME/.local/share/clayfarm-control/0.3.0.dev1"
APPLY=0
while (($#)); do
  case "$1" in
    --python) PYTHON="$2"; shift 2 ;;
    --install-dir) INSTALL_DIR="$2"; shift 2 ;;
    --apply) APPLY=1; shift ;;
    -h|--help) echo 'install.sh [--python python3] [--install-dir PATH] [--apply]'; exit 0 ;;
    *) echo "Unknown option: $1" >&2; exit 2 ;;
  esac
done
"$PYTHON" -c 'import sys; assert sys.version_info >= (3,11), "Python 3.11+ is required"'
if [[ -e "$INSTALL_DIR" ]]; then echo "Refusing to overwrite existing path: $INSTALL_DIR" >&2; exit 2; fi
printf 'Source: %s\nNew isolated environment: %s\nRequires network for pip; no models or credentials are installed.\n' "$ROOT" "$INSTALL_DIR"
if [[ "$APPLY" != 1 ]]; then echo 'Plan only. Add --apply to create the environment and install.'; exit 0; fi
mkdir -p "$(dirname "$INSTALL_DIR")"
"$PYTHON" -m venv "$INSTALL_DIR"
"$INSTALL_DIR/bin/python" -m pip install "${ROOT}[test]"
"$INSTALL_DIR/bin/clayfarm" --version
printf 'Installed command: %s\n' "$INSTALL_DIR/bin/clayfarm"
printf 'Run: "%s" setup --server https://YOUR-APPROVED-SERVER --role both\n' "$INSTALL_DIR/bin/clayfarm"
