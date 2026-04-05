{pkgs}: {
  deps = [
    pkgs.libgbm
    pkgs.dbus
    pkgs.gtk3
    pkgs.glib
    pkgs.xorg.libxcb
    pkgs.xorg.libXrandr
    pkgs.xorg.libXfixes
    pkgs.xorg.libXext
    pkgs.xorg.libXdamage
    pkgs.xorg.libXcomposite
    pkgs.xorg.libX11
    pkgs.libxkbcommon
    pkgs.alsa-lib
    pkgs.cairo
    pkgs.pango
    pkgs.mesa
    pkgs.libdrm
    pkgs.cups
    pkgs.at-spi2-atk
    pkgs.nss
    pkgs.nspr
  ];
}
