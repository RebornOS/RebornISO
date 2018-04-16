#!/usr/bin/env python
# -*- coding: utf-8 -*-
#
# alongside.py
#
# Copyright © 2013-2017 Antergos
#
# This file is part of Cnchi.
#
# Cnchi is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 3 of the License, or
# (at your option) any later version.
#
# Cnchi is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# The following additional terms are in effect as per Section 7 of the license:
#
# The preservation of all legal notices and author attributions in
# the material or in the Appropriate Legal Notices displayed
# by works containing it is required.
#
# You should have received a copy of the GNU General Public License
# along with Cnchi; If not, see <http://www.gnu.org/licenses/>.


""" Alongside installation module """

# ******************* NO GPT SUPPORT, YET ***************************************

import sys
import os
import logging
import subprocess
import tempfile

import show_message as show
import bootinfo

from pages.gtkbasebox import GtkBaseBox

import misc.extra as misc
import misc.gtkwidgets as gtkwidgets

if __debug__:
    def _(x): return x


# Leave at least 6.5GB for Reborn when shrinking
MIN_ROOT_SIZE = 6500


def get_partition_size_info(partition_path, human=False):
    """ Gets partition used and available space using df command """

    min_size = "0"
    part_size = "0"

    already_mounted = False

    with open("/proc/mounts") as mounts:
        if partition_path in mounts.read():
            already_mounted = True

    tmp_dir = ""

    try:
        cmd = []
        if not already_mounted:
            tmp_dir = tempfile.mkdtemp()
            cmd = ["mount", partition_path, tmp_dir]
            subprocess.check_output(cmd)
        if human:
            cmd = ['df', '-h', partition_path]
        else:
            cmd = ['df', partition_path]
        df_out = subprocess.check_output(cmd).decode()
        if not already_mounted:
            subprocess.check_output(['umount', '-l', tmp_dir])
    except subprocess.CalledProcessError as err:
        logging.error("Error running command %s: %s", err.cmd, err.output)
        return

    if os.path.exists(tmp_dir):
        os.rmdir(tmp_dir)

    if len(df_out) > 0:
        df_out = df_out.split('\n')
        df_out = df_out[1].split()
        if human:
            part_size = df_out[1]
            min_size = df_out[2]
        else:
            part_size = float(df_out[1])
            min_size = float(df_out[2])

    return min_size, part_size


class InstallationAlongside(GtkBaseBox):
    """ Performs an automatic installation next to a previous installed OS """

    def __init__(self, params, prev_page="installation_ask", next_page="user_info"):
        super().__init__(self, params, "alongside", prev_page, next_page)

        self.label = self.ui.get_object('label_info')

        self.choose_partition_label = self.ui.get_object(
            'choose_partition_label')
        self.choose_partition_combo = self.ui.get_object(
            'choose_partition_combo')

        self.oses = bootinfo.get_os_dict()
        # print(self.oses)
        self.resize_widget = None

    @staticmethod
    def get_new_device(device_to_shrink):
        """ Get new device where Cnchi will install Reborn
            returns an empty string if no device is available """
        # TODO: Fix this for mmcblk devices
        number = int(device_to_shrink[len("/dev/sdX"):])
        disk = device_to_shrink[:len("/dev/sdX")]

        new_number = number + 1
        new_device = disk + str(new_number)

        while misc.partition_exists(new_device):
            new_number += 1
            new_device = '{0}{1}'.format(disk, new_number)

        if new_number > 4:
            # No primary partitions left
            new_device = None

        return new_device

    def set_resize_widget(self, device_to_shrink):
        new_device = self.get_new_device(device_to_shrink)

        if new_device is None:
            # No device is available
            logging.error("There are no primary partitions available")
            return

        txt = "Will shrink device {0} and create new device {1}".format(
            device_to_shrink, new_device)
        logging.debug(txt)

        (min_size, part_size) = get_partition_size_info(device_to_shrink)
        max_size = part_size - (MIN_ROOT_SIZE * 1000.0)
        if max_size < 0:
            # Full Reborn does not fit but maybe base fits... ask user.
            txt = _(
                "Cnchi recommends at least 6.5GB free to install Reborn OS.") + "\n\n"
            txt += _("New partition {0} resulting of shrinking {1} will not have enough free space for a full installation.").format(
                new_device, device_to_shrink) + "\n\n"
            txt += _("You can still install Reborn OS, but be carefull on which DE you choose as it might not fit in.") + "\n\n"
            txt += _("Install at your own risk!")
            show.warning(self.get_main_window(), txt)
            max_size = part_size

        # print(min_size, max_size, part_size)

        if self.resize_widget:
            self.resize_widget.set_property('part_size', int(part_size))
            self.resize_widget.set_property('min_size', int(min_size))
            self.resize_widget.set_property('max_size', int(max_size))
        else:
            self.resize_widget = gtkwidgets.ResizeWidget(
                part_size, min_size, max_size)
            main_box = self.ui.get_object('alongside')
            main_box.pack_start(self.resize_widget, True, False, 5)

        self.resize_widget.set_part_title(
            'existing', self.oses[device_to_shrink], device_to_shrink)
        icon_file = self.get_distributor_icon_file(self.oses[device_to_shrink])
        self.resize_widget.set_part_icon('existing', icon_file=icon_file)

        self.resize_widget.set_part_title('new', 'New Reborn OS', new_device)
        icon_file = self.get_distributor_icon_file('Reborn')
        self.resize_widget.set_part_icon('new', icon_file=icon_file)

        self.resize_widget.set_pref_size(max_size)
        self.resize_widget.show_all()

    def get_distributor_icon_file(self, os_name):
        """ Gets an icon for the installed distribution """
        os_name = os_name.lower()

        # No numix icon for Reborn, use our own.
        if "reborn" in os_name:
            icons_path = os.path.join(self.settings.get('data'), "icons/48x48")
            icon_file = os.path.join(
                icons_path, "distributor-logo-reborn.png")
            return icon_file

        icon_names = [
            "lfs", "magiea", "manjaro", "mint", "archlinux", "chakra",
            "debian", "deepin", "fedora", "gentoo", "opensuse", "siduction",
            "kubuntu", "lubuntu", "ubuntu", "windows"]
        prefix = "distributor-logo-"
        sufix = ".svg"

        icons_path = os.path.join(self.settings.get('data'), "icons/scalable")
        default = os.path.join(icons_path, "distributor-logo.svg")

        for name in icon_names:
            if name in os_name:
                return os.path.join(icons_path, prefix + name + sufix)

        return default

    def translate_ui(self):
        """ Translates all ui elements """
        txt = _("Choose the new size of your installation")
        txt = '<span size="large">{0}</span>'.format(txt)
        self.label.set_markup(txt)

        txt = _("Choose the partition that you want to shrink:")
        self.choose_partition_label.set_markup(txt)

        self.header.set_subtitle(_("Reborn OS Alongside Installation"))

    def on_choose_partition_combo_changed(self, combobox):
        txt = combobox.get_active_text()
        device = txt.split("(")[1][:-1]
        # print(device)
        self.set_resize_widget(device)

    @staticmethod
    def select_first_combobox_item(combobox):
        """ Automatically select first entry """
        tree_model = combobox.get_model()
        tree_iter = tree_model.get_iter_first()
        combobox.set_active_iter(tree_iter)

    def prepare(self, direction):
        self.translate_ui()
        self.show_all()
        self.fill_choose_partition_combo()

    def fill_choose_partition_combo(self):
        self.choose_partition_combo.remove_all()

        devices = []

        for device in sorted(self.oses.keys()):
            # if "Swap" not in self.oses[device]:
            if "windows" in self.oses[device].lower():
                devices.append(device)

        if len(devices) > 1:
            new_device_found = False
            for device in sorted(devices):
                if self.get_new_device(device):
                    new_device_found = True
                    line = "{0} ({1})".format(self.oses[device], device)
                    self.choose_partition_combo.append_text(line)
            self.select_first_combobox_item(self.choose_partition_combo)
            self.show_all()
            if not new_device_found:
                txt = _(
                    "Can't find any spare partition number.\nAlongside installation can't continue.")
                self.choose_partition_label.hide()
                self.choose_partition_combo.hide()
                self.label.set_markup(txt)
                show.error(self.get_main_window(), txt)
        elif len(devices) == 1:
            self.set_resize_widget(devices[0])
            self.show_all()
            self.choose_partition_label.hide()
            self.choose_partition_combo.hide()
        else:
            logging.warning("Can't find any installed OS")

    def store_values(self):
        self.start_installation()
        return True

    # ######################################################################################################

    def start_installation(self):
        """ Alongside method shrinks selected partition
        and creates root and swap partition in the available space """

        (existing_os, existing_device) = self.resize_widget.get_part_title_and_subtitle(
            'existing')
        (new_os, new_device) = self.resize_widget.get_part_title_and_subtitle('new')

        print("existing", existing_os, existing_device)
        print("new", new_os, new_device)

        '''
        partition_path = row[COL_DEVICE]
        otherOS = row[COL_DETECTED_OS]
        fs_type = row[COL_FILESYSTEM]

        # TODO: Fix this for mmcblk devices
        device_path = row[COL_DEVICE][:len("/dev/sdX")]

        new_size = self.new_size

        # First, shrink filesystem
        res = fs.resize(partition_path, fs_type, new_size)
        if res:
            txt = "Filesystem on {0} shrunk.".format(partition_path)
            txt = txt + "\n"
            txt = txt + "Will recreate partition now on device {0} partition {1}".format(device_path, partition_path)
            logging.debug(txt)
            # Destroy original partition and create a new resized one
            res = pm.split_partition(device_path, partition_path, new_size)
        else:
            txt = "Can't shrink {0}({1}) filesystem".format(otherOS, fs_type)
            logging.error(txt)
            show.error(self.get_main_window(), txt)
            return

        # res is either False or a parted.Geometry for the new free space
        if res is None:
            txt = "Can't shrink {0}({1}) partition".format(otherOS, fs_type)
            logging.error(txt)
            show.error(self.get_main_window(), txt)
            txt = "*** FILESYSTEM IN UNSAFE STATE ***"
            txt = txt + "\n"
            txt = txt + "Filesystem shrink succeeded but partition shrink failed."
            logging.error(txt)
            return

        txt = "Partition {0} shrink complete".format(partition_path)
        logging.debug(txt)

        devices = pm.get_devices()
        disk = devices[device_path][0]
        mount_devices = {}
        fs_devices = {}

        mem_total = subprocess.check_output(["grep", "MemTotal", "/proc/meminfo"]).decode()
        mem_total = int(mem_total.split()[1])
        mem = mem_total / 1024

        # If geometry gives us at least 7.5GB (MIN_ROOT_SIZE + 1GB) we'll create ROOT and SWAP
        no_swap = False
        if res.getLength('MB') < MIN_ROOT_SIZE + 1:
            if mem < 2048:
                # Less than 2GB RAM and no swap? No way.
                logging.error("Cannot create new swap partition. Not enough free space")
                txt = _("Cannot create new swap partition. Not enough free space")
                show.error(self.get_main_window(), txt)
                return
            else:
                no_swap = True

        if no_swap:
            npart = pm.create_partition(device_path, 0, res)
            if npart is None:
                logging.error("Cannot create new partition.")
                txt = _("Cannot create new partition.")
                show.error(self.get_main_window(), txt)
                return
            pm.finalize_changes(disk)
            mount_devices["/"] = npart.path
            fs_devices[npart.path] = "ext4"
            fs.create_fs(npart.path, 'ext4', label='ROOT')
        else:
            # We know for a fact we have at least MIN_ROOT_SIZE + 1GB of space,
            # and at least MIN_ROOT_SIZE of those must go to ROOT.

            # Suggested sizes from Anaconda installer
            if mem < 2048:
                swap_part_size = 2 * mem
            elif 2048 <= mem < 8192:
                swap_part_size = mem
            elif 8192 <= mem < 65536:
                swap_part_size = mem / 2
            else:
                swap_part_size = 4096

            # Max swap size is 10% of all available disk size
            max_swap = res.getLength('MB') * 0.1
            if swap_part_size > max_swap:
                swap_part_size = max_swap

            # Create swap partition
            units = 1000000
            sec_size = disk.device.sectorSize
            new_length = int(swap_part_size * units / sec_size)
            new_end_sector = res.start + new_length
            my_geometry = pm.geom_builder(disk, res.start, new_end_sector, swap_part_size)
            logging.debug("create_partition %s", my_geometry)
            swappart = pm.create_partition(disk, 0, my_geometry)
            if swappart is None:
                logging.error("Cannot create new swap partition.")
                txt = _("Cannot create new swap partition.")
                show.error(self.get_main_window(), txt)
                return

            # Create new partition for /
            new_size_in_mb = res.getLength('MB') - swap_part_size
            start_sector = new_end_sector + 1
            my_geometry = pm.geom_builder(disk, start_sector, res.end, new_size_in_mb)
            logging.debug("create_partition %s", my_geometry)
            npart = pm.create_partition(disk, 0, my_geometry)
            if npart is None:
                logging.error("Cannot create new partition.")
                txt = _("Cannot create new partition.")
                show.error(self.get_main_window(), txt)
                return

            pm.finalize_changes(disk)

            # Mount points
            mount_devices["swap"] = swappart.path
            fs_devices[swappart.path] = "swap"
            fs.create_fs(swappart.path, 'swap', 'SWAP')

            mount_devices["/"] = npart.path
            fs_devices[npart.path] = "ext4"
            fs.create_fs(npart.path, 'ext4', 'ROOT')

        # TODO: User should be able to choose if installing a bootloader or not (and which one)
        self.settings.set('bootloader_install', True)

        if self.settings.get('bootloader_install'):
            self.settings.set('bootloader', "grub2")
            self.settings.set('bootloader_device', device_path)
            msg = "Reborn will install the bootloader {0} in device {1}"
            msg = msg.format(self.bootloader, self.bootloader_device)
            logging.info(msg)
        else:
            logging.info("Cnchi will not install any bootloader")

        self.process = installation_process.InstallationProcess(
            self.settings,
            self.callback_queue,
            mount_devices,
            fs_devices)
        self.process.start()
        '''


if __name__ == '__main__':
    from test_screen import _, run
    run('InstallationAlongside')
