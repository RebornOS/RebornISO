sudo wget https://cinnamon-spices.linuxmint.com/files/applets/slingshot@jfarthing84.zip --directory-prefix=/usr/share/cinnamon/applets/
sudo unzip -d /usr/share/cinnamon/applets/ /usr/share/cinnamon/applets/slingshot@jfarthing84.zip ##unzip##

sudo wget https://cinnamon-spices.linuxmint.com/files/extensions/transparent-panels@germanfr.zip --directory-prefix=/$HOME/.local/share/cinnamon/extensions/
sudo unzip -d /$HOME/.local/share/cinnamon/extensions/ /$HOME/.local/share/cinnamon/extensions/transparent-panels@germanfr.zip

git clone https://github.com/fsvh/plank-themes.git
cd plank-themes
yes | ./install.sh
cd ..
rm -rf plank-themes

git clone https://github.com/RebornOS/elementary-theme.git
cd elementary-theme
sudo mv elementary.zip /usr/share/themes/
sudo unzip -d /usr/share/themes/ /usr/share/themes/elementary.zip
sudo rm /usr/share/themes/elementary.zip
sudo rm /$HOME/.local/share/cinnamon/extensions/transparent-panels@germanfr/settings-schema.json
sudo mv settings-schema.json /$HOME/.local/share/cinnamon/extensions/transparent-panels@germanfr/
cd ..
rm -rf elementary-theme

dconf write /org/cinnamon/desktop/wm/preferences/theme "'MacOS-Sierra'"
dconf write /org/cinnamon/theme/name "'macOS-Sierra'"
dconf write /org/cinnamon/desktop/interface/gtk-theme "'elementary'"
dconf write /org/cinnamon/desktop/interface/icon-theme "'elementary'" ##elementary-icon-theme##
dconf write /org/cinnamon/desktop/interface/gtk-decoration-layout "'close:menu,maximize'"

dconf write /org/cinnamon/alttab-switcher-style "'coverflow'"

donf write /org/cinnamon/hotcorner-layout "['expo:true:50', 'expo:false:50', 'scale:false:0', 'desktop:false:0']"

dconf write /org/cinnamon/enabled-extensions "['transparent-panels@germanfr']"

dconf write /org/cinnamon/enabled-applets "['panel1:right:0:systray@cinnamon.org:0', 'panel1:center:0:calendar@cinnamon.org:12', 'panel1:left:1:slingshot@jfarthing84:14', 'panel1:right:3:user@cinnamon.org:15', 'panel1:right:1:sound@cinnamon.org:21', 'panel1:right:2:power@cinnamon.org:22']"

dconf write /org/cinnamon/panel-launchers "['DEPRECATED']"  ##plank##

dconf write /org/cinnamon/panels-autohide "['1:intel']"

dconf write /org/cinnamon/panels-enabled "['1:0:top']"

dconf write /org/cinnamon/panels-height "['1:25']"

dconf write /org/cinnamon/show-media-keys-osd "'medium'"

dconf write /org/cinnamon/workspace-osd-duration "400"

dconf write /org/cinnamon/workspace-osd-x "50"

dconf write /org/cinnamon/workspace-osd-y "50"

dconf write /org/cinnamon/desktop-effects-maximize-effect "'scale'"

dconf write /org/cinnamon/desktop-effects-maximize-time "200"

dconf write /org/cinnamon/desktop-effects-unmaximize-effect "'scale'"

dconf write /org/cinnamon/desktop-effects-unmaximize-time "200"

dconf write /net/launchpad/plank/enabled-docks "['dock1']"

dconf write /net/launchpad/plank/docks/dock1/dock-items "['gnome-terminal.dockitem', 'nautilus.dockitem', 'pamac-manager.dockitem', 'pragha.dockitem', 'reborn-updates.dockitem']"

dconf write /net/launchpad/plank/docks/dock1/hide-mode "'intelligent'"

dconf write /net/launchpad/plank/docks/dock1/current-workspace-only true

dconf write /net/launchpad/plank/docks/dock1/icon-size "40"

dconf write /net/launchpad/plank/docks/dock1/theme "'Gtk+'"

dconf write /net/launchpad/plank/docks/dock1/zoom-enabled true

dconf write /net/launchpad/plank/docks/dock1/zoom-percent "110"
