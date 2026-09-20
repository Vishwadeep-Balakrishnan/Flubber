#!/usr/bin/env bash
flubber_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
exec /bin/bash "$flubber_dir/Start_Flubber.sh"
