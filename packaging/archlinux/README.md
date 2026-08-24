# Arch Linux package

Build and install with makepkg:

```sh
cd packaging/archlinux
makepkg -si
```

The PKGBUILD is a VCS package that pulls the source from the `feat-cli`
branch of the GitHub fork, so `pkgver` reflects the tracked commit.
