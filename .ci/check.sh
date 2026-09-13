#!/bin/sh
set -eu
cd "$(dirname "$0")/.."
project_root=$(pwd)
cd "$project_root/ui/admin"
npm ci --no-audit --no-fund
cd "$project_root/ui/admin"
npm test
cd "$project_root/ui/admin"
npm run build
