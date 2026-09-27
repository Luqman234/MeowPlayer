# Maintainer: Luqman234
pkgname=meowplayer
pkgver=0.19.1
pkgrel=3
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

_commit='eb2d459a0a2488faadf8d338ead8678ca6e83a08'
source=("$pkgname::git+$url.git#commit=$_commit")
sha256sums=('SKIP')

build() {
  cd "$srcdir/$pkgname"
  python -m build --wheel --no-isolation
}

check() {
  cd "$srcdir/$pkgname"
  python -m unittest discover -s tests -v
}

package() {
  cd "$srcdir/$pkgname"
  python -m installer --destdir="$pkgdir" dist/*.whl
  install -Dm644 LICENSE "$pkgdir/usr/share/licenses/$pkgname/LICENSE"
}
