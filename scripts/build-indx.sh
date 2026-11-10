#!/bin/sh
set -eu
cd "$(dirname "$0")/.."
if [ ! -f .local/deps/manifold-install/lib/libmanifoldc.a ] || [ ! -f .local/deps/draco-c/build/libdraco_c.a ]; then
  echo "Run scripts/setup-indx.sh first; pinned native libraries are required." >&2
  exit 1
fi
if [ "$(git -C .local/deps/manifold rev-parse HEAD)" != 31afd71d17c7a94cfaeada83f657d7b42628ead6 ]; then
  echo "Unexpected Manifold checkout; use pinned 3.4.1." >&2
  exit 1
fi
BREW_PREFIX=$(brew --prefix)
export CGO_CFLAGS="-I$PWD/.local/deps/manifold-install/include -I$BREW_PREFIX/include"
export CGO_CXXFLAGS="-I$BREW_PREFIX/include -std=c++17"
export CGO_LDFLAGS="-L$PWD/.local/deps/manifold-install/lib -L$BREW_PREFIX/lib -L$PWD/.local/deps/draco-c/build -ldraco_c -lc++"
mkdir -p build/bin
go build -tags customenv,draco,cgal -o build/bin/ditherforge-cli ./cmd/ditherforge
if [ "${1:-}" = "--test" ]; then
  go test -tags customenv,draco,cgal -timeout 10m ./internal/export3mf ./internal/settings ./internal/pipeline
  python3 -m unittest discover -s chat -p 'test_*.py'
fi
if [ "${1:-}" = "--test-all" ]; then
  (cd frontend && npm ci --ignore-scripts && npm run check && npm run build)
  go test -tags customenv,draco,cgal -timeout 10m ./...
  python3 -m unittest discover -s chat -p 'test_*.py'
fi
