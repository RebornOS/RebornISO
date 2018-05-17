gsettings set org.gnome.settings-daemon.plugins.power sleep-inactive-ac-timeout '0' && gsettings set org.gnome.settings-daemon.plugins.power sleep-inactive-battery-timeout '0'
WM=`wmctrl -m | grep Name | awk '{print $2}'`
echo $WM
LINE=$(grep -o "B" <<<"$WM" | wc -l)
echo $LINE
if [[ $LINE == 1 ]]; then
dconf write /org/gnome/desktop/background/picture-uri "'file:///usr/share/backgrounds/abstract1-reborn2.png'"
dconf write /org/gnome/desktop/interface/gtk-theme "'Evo-Pop'"
dconf write /org/gnome/desktop/interface/icon-name "'Flat-Remix'"
fi
if [ $LINE -eq "0" ]; then
dconf write /org/gnome/desktop/background/picture-uri "'file:///usr/share/backgrounds/elementary.jpg'"
dconf write /org/gnome/shell/extensions/user-theme/name "'Arctic-Apricity'"
dconf write /org/gnome/desktop/interface/gtk-theme "'Arc'"
dconf write /org/gnome/desktop/interface/icon-name "'Apricity-Icons'"
fi
wget --spider www.google.com
if [ "$?" = 0 ]; then
  sudo rm -rf /etc/pacman.d/gnupg
  sudo pacman -Syy
  sudo pacman-key --init
  sudo pacman-key --populate archlinux antergos aurarchlinux rebornos
  sudo pacman-key --refresh-keys
  sudo pacman -Syy
  reflector --verbose --latest 10 --sort rate --save /etc/pacman.d/mirrorlist
# if [ ! -z $(grep "eu" "etc/pacman.d/mirrorlist") ]; then 
# sudo cp /usr/bin/cnchi/pacman.conf /etc/
# sudo mv /usr/bin/cnchi/reborn-mirrorlist2 /etc/pacman.d/reborn-mirrorlist
# fi
else exec /usr/bin/internet.sh
fi
