#! /usr/bin/env bash
set -o xtrace

OWN_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" >/dev/null 2>&1 && pwd )"


pip-compile  \
    --output-file "$OWN_DIR/build-context/requirements.lock"  \
    "$OWN_DIR/requirements.txt"
