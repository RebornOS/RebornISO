#!/bin/bash
systemd-detect-virt
if [ "$?" != oracle ]; then
pkill dde-wm-chooser
exec /usr/bin/deepin-fix.sh
fi
