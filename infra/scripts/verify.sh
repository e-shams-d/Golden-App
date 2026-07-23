#!/usr/bin/env sh
set -eu

script_directory=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)

sh "$script_directory/verify-native.sh"
sh "$script_directory/verify-docker.sh"
