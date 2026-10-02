# Maintainer: Luqman234
pkgname=meowplayer
pkgver=0.21.0rc1
pkgrel=1
pkgdesc="A lightweight, aggressively cat-themed terminal music player powered by mpv"
arch=('any')
url="https://github.com/Luqman234/MeowPlayer"
license=('GPL-3.0-only')

depends=(
  'python'
  'mpv'
  'yt-dlp'
  'cava'
  'playerctl'
  'python-mutagen'
  'python-dbus-next'
  'python-pillow'
  'python-watchdog'
)

makedepends=(
  'git'
  'python-build'
  'python-installer'
  'python-setuptools'
  'python-wheel'
)

_commit='00cd4323097fefdb68a13f8731fe75b5ef2e4b95'
source=("$pkgname::git+$url.git#commit=$_commit")
sha256sums=('SKIP')

build() {
  cd "$srcdir/$pkgname"
  # VCS source directories survive normal makepkg updates. Remove wheels from
  # older MeowPlayer versions so installer never receives multiple releases.
  rm -rf dist
  python -m build --wheel --no-isolation
}

check() {
  cd "$srcdir/$pkgname"
  python -m unittest discover -s tests -v
}

package() {
  cd "$srcdir/$pkgname"

  local wheels=(dist/*.whl)
  if (( ${#wheels[@]} != 1 )); then
    printf 'Expected exactly one MeowPlayer wheel, found %d\n' "${#wheels[@]}" >&2
    return 1
  fi

  python -m installer --destdir="$pkgdir" "${wheels[0]}"
  install -Dm644 LICENSE "$pkgdir/usr/share/licenses/$pkgname/LICENSE"
}
