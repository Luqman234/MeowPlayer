# Maintainer: Luqman234
pkgname=meowplayer
pkgver=0.20.0
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

_commit='5d3b3320c6d6ebdcc3c779f2688bfdb6dec6f4f5'
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
