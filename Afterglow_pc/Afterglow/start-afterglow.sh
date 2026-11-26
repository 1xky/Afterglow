#!/bin/sh
set -eu
cd "$(dirname "$0")"

for python in python3 python; do
    if command -v "$python" >/dev/null 2>&1 &&
        "$python" -c 'import sys; sys.exit(sys.version_info < (3, 10))'
    then
        exec "$python" -B afterglow.py "$@"
    fi
done

printf '%s\n' 'Afterglow needs Python 3.10 or later. Install it and run this launcher again.' >&2
exit 1
