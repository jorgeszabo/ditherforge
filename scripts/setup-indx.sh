#!/bin/sh
# macOS Apple silicon setup; dependencies and downloaded app remain local where possible.
set -eu
cd "$(dirname "$0")/.."
HOMEBREW_NO_AUTO_UPDATE=1 brew install go cmake cgal pkg-config
mkdir -p .local/deps .local/runs
if [ ! -d /Applications/PrusaSlicer-3.0.0-alpha14.app ] && [ ! -d .local/deps/PrusaSlicer-3.0.0-alpha14.app ]; then
  IMAGE=.local/deps/PrusaSlicer-3.0.0-alpha14.dmg
  curl -fL https://github.com/prusa3d/PrusaSlicer/releases/download/version_3.0.0-alpha14/PrusaSlicer-3.0.0-alpha14.dmg -o "$IMAGE"
  python3 - "$IMAGE" <<'PY'
import hashlib,sys
assert hashlib.sha256(open(sys.argv[1],'rb').read()).hexdigest() == '9ae809965f0facaf868ff7ea38927b53ce6ed7da901acca5a1d99bed3446eaf1', 'Prusa download checksum mismatch'
PY
  MOUNT=$(mktemp -d /tmp/dither-prusa.XXXXXX)
  trap 'hdiutil detach "$MOUNT" >/dev/null 2>&1 || true; rmdir "$MOUNT" 2>/dev/null || true' EXIT
  hdiutil attach -readonly -nobrowse -mountpoint "$MOUNT" "$IMAGE"
  ditto "$MOUNT/PrusaSlicer-3.0.0-alpha14.app" .local/deps/PrusaSlicer-3.0.0-alpha14.app
  hdiutil detach "$MOUNT"
  rmdir "$MOUNT"
  trap - EXIT
fi
if [ ! -d .local/deps/draco-c ]; then
  git clone https://github.com/qmuntal/draco-c.git .local/deps/draco-c
  git -C .local/deps/draco-c checkout d9a4da08378b222fe51fc0712a1f096c81d41b5d
fi
test "$(git -C .local/deps/draco-c rev-parse HEAD)" = d9a4da08378b222fe51fc0712a1f096c81d41b5d
cmake -S .local/deps/draco-c -B .local/deps/draco-c/build -DCMAKE_BUILD_TYPE=Release -DDRACO_POINT_CLOUD_COMPRESSION=ON -DDRACO_MESH_COMPRESSION=ON -DDRACO_STANDARD_EDGEBREAKER=ON
cmake --build .local/deps/draco-c/build --config Release -j 4
if [ ! -d .local/deps/manifold ]; then
  git clone --depth 1 --branch v3.4.1 https://github.com/elalish/manifold.git .local/deps/manifold
fi
test "$(git -C .local/deps/manifold rev-parse HEAD)" = 31afd71d17c7a94cfaeada83f657d7b42628ead6
cmake -S .local/deps/manifold -B .local/deps/manifold/build -DCMAKE_BUILD_TYPE=Release -DBUILD_SHARED_LIBS=OFF -DMANIFOLD_CROSS_SECTION=ON -DMANIFOLD_PAR=OFF -DMANIFOLD_TEST=OFF -DMANIFOLD_CBIND=ON -DMANIFOLD_USE_BUILTIN_CLIPPER2=ON -DCMAKE_INSTALL_PREFIX="$PWD/.local/deps/manifold-install"
cmake --build .local/deps/manifold/build --config Release -j 4
cmake --install .local/deps/manifold/build
/usr/bin/libtool -static -o .local/deps/manifold-install/lib/libmanifold-combined.a .local/deps/manifold-install/lib/libmanifold.a .local/deps/manifold-install/lib/libClipper2.a
mv .local/deps/manifold-install/lib/libmanifold-combined.a .local/deps/manifold-install/lib/libmanifold.a
node scripts/refresh-indx.cjs
scripts/build-indx.sh --test
(cd frontend && npm ci --ignore-scripts && npm run check && npm run build:hybrid)
chat/dither-chat doctor
