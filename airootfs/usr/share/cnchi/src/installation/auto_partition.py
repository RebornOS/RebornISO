#!/usr/bin/env python
# -*- coding: utf-8 -*-
#
# auto_partition.py
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

""" Used by automatic installation """

import os
import subprocess
import logging
import math

from misc.extra import InstallError
from misc.run_cmd import call, popen
import parted3.fs_module as fs

from installation import wrapper

'''
NOTE: Exceptions in this file

On a warning situation, Cnchi should try to continue, so we need to catch the exception here.
If we don't catch the exception here, it will be caught in process.py and managed as a fatal error.
On the other hand, if we want to clarify the exception message we can catch it here
and then raise an InstallError exception.
'''

""" AutoPartition module """

# Partition sizes are in MiB
MAX_ROOT_SIZE = 30000

# KDE (with all features) needs 8 GB for its files (including pacman cache xz files).
# Vbox, by default, creates disks of 8GB. We should limit to this so vbox installations do not fail
# (if installing kde and not enough free space is available is their fault, not ours)
MIN_ROOT_SIZE = 8000


def printk(enable):
    """ Enables / disables printing kernel messages to console """
    with open("/proc/sys/kernel/printk", "w") as fpk:
        if enable:
            fpk.write("4")
        else:
            fpk.write("0")


def unmount(directory):
    """ Unmount """
    logging.debug("Unmounting %s", directory)
    call(["umount", "-l", directory])


def unmount_all_in_directory(dest_dir):
    """ Unmounts all devices that are mounted inside dest_dir """

    # Unmount all swap devices
    cmd = ["swapon", "--show=NAME", "--noheadings"]
    swaps = call(cmd)
    if swaps:
        swaps = swaps.split("\n")
        for name in filter(None, swaps):
            if "/dev/zram" not in name:
                call(["swapoff", name])

    # Get all mounted devices
    mount_result = call(["mount"]).split("\n")

    # Umount all devices mounted inside dest_dir (if any)
    dirs = []
    for mount in mount_result:
        if dest_dir in mount:
            try:
                directory = mount.split()[2]
                # Do not unmount dest_dir now (we will do it later)
                if directory != dest_dir:
                    dirs.append(directory)
            except IndexError:
                pass

    for directory in dirs:
        unmount(directory)

    # Now is the time to unmount the device that is mounted in dest_dir (if any)
    unmount(dest_dir)


def unmount_all_in_device(device):
    """ Unmounts all partitions from device """

    # Unmount all swap
    cmd = ["swapon", "--show=NAME", "--noheadings"]
    swaps = call(cmd)
    swaps = swaps.split("\n")
    for name in filter(None, swaps):
        if "/dev/zram" not in name:
            call(["swapoff", name])

    # Get all mounted devices
    mount_result = call(["mount"])
    mount_result = mount_result.split("\n")

    # Umount all partitions of device
    dirs = []
    for mount in mount_result:
        if device in mount:
            try:
                directory = mount.split()[0]
                dirs.append(directory)
            except IndexError:
                pass

    for directory in dirs:
        unmount(directory)


def remove_lvm(device):
    """ Remove all previous LVM volumes
    (it may have been left created due to a previous failed installation) """

    err_msg = "Can't delete existent LVM volumes in device {0}".format(device)

    cmd = ["lvs", "-o", "lv_name,vg_name,devices", "--noheadings"]
    lvolumes = call(cmd, msg=err_msg)
    if lvolumes:
        lvolumes = lvolumes.split("\n")
        for lvolume in lvolumes:
            if len(lvolume) > 0:
                (lvolume, vgroup, ldevice) = lvolume.split()
                if device in ldevice:
                    lvdev = "/dev/" + vgroup + "/" + lvolume
                    call(["wipefs", "-a", lvdev], msg=err_msg)
                    call(["lvremove", "-f", lvdev], msg=err_msg)

    cmd = ["vgs", "-o", "vg_name,devices", "--noheadings"]
    vgnames = call(cmd, msg=err_msg)
    if vgnames:
        vgnames = vgnames.split("\n")
        for vgname in vgnames:
            (vgname, vgdevice) = vgname.split()
            if len(vgname) > 0 and device in vgdevice:
                call(["vgremove", "-f", vgname], msg=err_msg)

    cmd = ["pvs", "-o", "pv_name", "--noheadings"]
    pvolumes = call(cmd, msg=err_msg)
    if pvolumes:
        pvolumes = pvolumes.split("\n")
        for pvolume in pvolumes:
            pvolume = pvolume.strip()
            if device in pvolume:
                cmd = ["pvremove", "-ff", "-y", pvolume]
                call(cmd, msg=err_msg)


def close_reborn_luks_devices():
    """ Close LUKS devices (they may have been left open because of a previous
    failed installation) """

    volumes = ["/dev/mapper/cryptReborn", "/dev/mapper/cryptRebornHome"]

    err_msg = "Can't close already opened LUKS devices"

    for volume in volumes:
        if os.path.exists(volume):
            cmd = ["cryptsetup", "luksClose", volume]
            call(cmd, msg=err_msg)


def setup_luks(luks_device, luks_name, luks_pass=None, luks_key=None):
    """ Setups a luks device """

    if (luks_pass is None or luks_pass == "") and luks_key is None:
        txt = "Can't setup LUKS in device {0}. A password or a key file are needed".format(
            luks_device)
        logging.error(txt)
        return

    # For now, we we'll use the same password for root and /home
    # If instead user wants to use a key file, we'll have two different key files.

    logging.debug("Cnchi will setup LUKS on device %s", luks_device)

    # Wipe LUKS header (just in case we're installing on a pre LUKS setup)
    # For 512 bit key length the header is 2MiB
    # If in doubt, just be generous and overwrite the first 10MiB or so
    wrapper.dd("/dev/zero", luks_device, bs=512, count=20480)

    err_msg = "Can't format and open the LUKS device {0}".format(luks_device)

    if luks_pass is None or luks_pass == "":
        # No key password given, let's create a random keyfile
        wrapper.dd("/dev/urandom", luks_key, bs=1024, count=4)

        # Set up luks with a keyfile
        cmd = [
            "cryptsetup", "luksFormat", "-q", "-c", "aes-xts-plain",
            "-s", "512", luks_device, luks_key]
        call(cmd, msg=err_msg, fatal=True)

        cmd = [
            "cryptsetup", "luksOpen", luks_device, luks_name, "-q",
            "--key-file", luks_key]
        call(cmd, msg=err_msg, fatal=True)
    else:
        # Set up luks with a password key

        luks_pass_bytes = bytes(luks_pass, 'UTF-8')

        # https://code.google.com/p/cryptsetup/wiki/Cryptsetup160
        # aes-xts-plain
        # aes-cbc-essiv:sha256
        cmd = [
            "cryptsetup", "luksFormat", "-q", "-c", "aes-xts-plain64",
            "-s", "512", "--key-file=-", luks_device]
        proc = popen(cmd, msg=err_msg, fatal=True)
        proc.communicate(input=luks_pass_bytes)

        cmd = [
            "cryptsetup", "luksOpen", luks_device, luks_name, "-q",
            "--key-file=-"]
        proc = popen(cmd, msg=err_msg, fatal=True)
        proc.communicate(input=luks_pass_bytes)


class AutoPartition(object):
    """ Class used by the automatic installation method """

    def __init__(self, dest_dir, auto_device, use_luks, luks_password, use_lvm, use_home, bootloader, callback_queue):
        """ Class initialization """
        self.dest_dir = dest_dir
        self.auto_device = auto_device
        self.luks_password = luks_password
        # Use LUKS encryption
        self.luks = use_luks
        # Use LVM
        self.lvm = use_lvm
        # Make home a different partition or if using LVM, a different volume
        self.home = use_home

        self.bootloader = bootloader.lower()

        # Will use these queue to show progress info to the user
        self.callback_queue = callback_queue
        self.last_event = {}
        self.percent = 0

        if os.path.exists("/sys/firmware/efi"):
            # If UEFI use GPT
            self.uefi = True
            self.gpt = True
        else:
            # If BIOS, use MBR
            self.uefi = False
            self.gpt = False

    def queue_event(self, event_type, event_text=""):
        """ Adds an event to Cnchi event queue """

        if self.callback_queue is None:
            if event_type != "percent":
                logging.debug("{0}:{1}".format(event_type, event_text))
            return

        if event_type in self.last_event:
            if self.last_event[event_type] == event_text:
                # do not repeat same event
                return

        self.last_event[event_type] = event_text

        try:
            # Add the event
            self.callback_queue.put_nowait((event_type, event_text))
        except queue.Full:
            pass

    def mkfs(self, device, fs_type, mount_point, label_name, fs_options="", btrfs_devices=""):
        """ We have two main cases: "swap" and everything else. """
        logging.debug("Will format device %s as %s", device, fs_type)
        if fs_type == "swap":
            err_msg = "Can't activate swap in {0}".format(device)
            swap_devices = call(["swapon", "-s"], msg=err_msg)
            if device in swap_devices:
                call(["swapoff", device], msg=err_msg)
            cmd = ["mkswap", "-L", label_name, device]
            call(cmd, msg=err_msg)
            cmd = ["swapon", device]
            call(cmd, msg=err_msg)
        else:
            mkfs = {"xfs": "mkfs.xfs {0} -L {1} -f {2}".format(fs_options, label_name, device),
                    "jfs": "yes | mkfs.jfs {0} -L {1} {2}".format(fs_options, label_name, device),
                    "reiserfs": "yes | mkreiserfs {0} -l {1} {2}".format(fs_options, label_name, device),
                    "ext2": "mkfs.ext2 -q {0} -F -L {1} {2}".format(fs_options, label_name, device),
                    "ext3": "mkfs.ext3 -q {0} -F -L {1} {2}".format(fs_options, label_name, device),
                    "ext4": "mkfs.ext4 -q {0} -F -L {1} {2}".format(fs_options, label_name, device),
                    "btrfs": "mkfs.btrfs {0} -L {1} {2}".format(fs_options, label_name, btrfs_devices),
                    "nilfs2": "mkfs.nilfs2 {0} -L {1} {2}".format(fs_options, label_name, device),
                    "ntfs-3g": "mkfs.ntfs {0} -L {1} {2}".format(fs_options, label_name, device),
                    "vfat": "mkfs.vfat {0} -n {1} {2}".format(fs_options, label_name, device),
                    "fat32": "mkfs.vfat {0} -n {1} {2}".format(fs_options, label_name, device),
                    "f2fs": "mkfs.f2fs {0} -l {1} {2}".format(fs_options, label_name, device)}

            # Make sure the fs type is one we can handle
            if fs_type not in mkfs.keys():
                txt = _("Unknown filesystem type {0}").format(fs_type)
                raise InstallError(txt)

            command = mkfs[fs_type]

            err_msg = "Can't create filesystem {0}".format(fs_type)
            call(command.split(), msg=err_msg, fatal=True)

            # Flush filesystem buffers
            call(["sync"])

            # Create our mount directory
            path = self.dest_dir + mount_point
            os.makedirs(path, mode=0o755, exist_ok=True)

            # Mount our new filesystem

            mopts = "rw,relatime"
            if fs_type == "ext4":
                mopts = "rw,relatime,data=ordered"
            elif fs_type == "btrfs":
                mopts = 'rw,relatime,space_cache,autodefrag,inode_cache'

            err_msg = "Error trying to mount {0} in {1}".format(device, path)
            cmd = ["mount", "-t", fs_type, "-o", mopts, device, path]
            call(cmd, msg=err_msg, fatal=True)

            # Change permission of base directories to avoid btrfs issues
            if mount_point == "/tmp":
                mode = 0o1777
            elif mount_point == "/root":
                mode = 0o750
            else:
                mode = 0o755
            os.chmod(path, mode)

        fs_uuid = fs.get_uuid(device)
        fs_label = fs.get_label(device)
        msg = "Device details: %s UUID=%s LABEL=%s"
        logging.debug(msg, device, fs_uuid, fs_label)

    @staticmethod
    def get_partition_path(device, part_num):
        """ This is awful and prone to fail. We should do some
            type of test here """

        # Remove /dev/
        path = device.replace('/dev/', '')
        partials = [
            'rd/', 'ida/', 'cciss/', 'sx8/', 'mapper/', 'mmcblk', 'md', 'nvme']
        found = [p for p in partials if path.startswith(p)]
        if found:
            return "{0}p{1}".format(device, part_num)
        else:
            return "{0}{1}".format(device, part_num)

    def get_devices(self):
        """ Set (and return) all partitions on the device """
        devices = {}
        device = self.auto_device
        logging.debug(device)

        # device is of type /dev/sdX or /dev/hdX or /dev/mmcblkX

        if self.gpt:
            if not self.uefi:
                # Skip BIOS Boot Partition
                # We'll never get here as we use UEFI+GPT or BIOS+MBR
                part_num = 2
            else:
                part_num = 1

            if self.bootloader == "grub2":
                devices['efi'] = self.get_partition_path(device, part_num)
                part_num += 1

            devices['boot'] = self.get_partition_path(device, part_num)
            part_num += 1
            devices['root'] = self.get_partition_path(device, part_num)
            part_num += 1
            if self.home:
                devices['home'] = self.get_partition_path(device, part_num)
                part_num += 1
            devices['swap'] = self.get_partition_path(device, part_num)
        else:
            devices['boot'] = self.get_partition_path(device, 1)
            devices['root'] = self.get_partition_path(device, 2)
            if self.home:
                devices['home'] = self.get_partition_path(device, 3)
            devices['swap'] = self.get_partition_path(device, 5)

        if self.luks:
            if self.lvm:
                # LUKS and LVM
                devices['luks_root'] = devices['root']
                devices['lvm'] = "/dev/mapper/cryptReborn"
            else:
                # LUKS and no LVM
                devices['luks_root'] = devices['root']
                devices['root'] = "/dev/mapper/cryptReborn"
                if self.home:
                    # In this case we'll have two LUKS devices, one for root
                    # and the other one for /home
                    devices['luks_home'] = devices['home']
                    devices['home'] = "/dev/mapper/cryptRebornHome"
        elif self.lvm:
            # No LUKS but using LVM
            devices['lvm'] = devices['root']

        if self.lvm:
            devices['root'] = "/dev/RebornVG/RebornRoot"
            devices['swap'] = "/dev/RebornVG/RebornSwap"
            if self.home:
                devices['home'] = "/dev/RebornVG/RebornHome"

        return devices

    def get_mount_devices(self):
        """ Specify for each mount point which device we must mount there """

        devices = self.get_devices()
        mount_devices = {}

        if self.gpt and self.bootloader == "grub2":
            mount_devices['/boot/efi'] = devices['efi']

        mount_devices['/boot'] = devices['boot']
        mount_devices['/'] = devices['root']

        if self.home:
            mount_devices['/home'] = devices['home']

        if self.luks:
            mount_devices['/'] = devices['luks_root']
            if self.home and not self.lvm:
                mount_devices['/home'] = devices['luks_home']

        mount_devices['swap'] = devices['swap']

        for mount_device in mount_devices:
            logging.debug(
                "%s assigned to be mounted in %s",
                mount_devices[mount_device],
                mount_device)

        return mount_devices

    def get_fs_devices(self):
        """ Return which filesystem is in a selected device """

        devices = self.get_devices()

        fs_devices = {}

        if self.gpt:
            if self.bootloader == "grub2":
                fs_devices[devices['efi']] = "vfat"
                fs_devices[devices['boot']] = "ext4"
            elif self.bootloader in ["systemd-boot", "refind"]:
                fs_devices[devices['boot']] = "vfat"
        else:
            if self.uefi:
                fs_devices[devices['boot']] = "vfat"
            else:
                fs_devices[devices['boot']] = "ext4"

        fs_devices[devices['swap']] = "swap"
        fs_devices[devices['root']] = "ext4"

        if self.home:
            fs_devices[devices['home']] = "ext4"

        if self.luks:
            fs_devices[devices['luks_root']] = "ext4"
            if self.home:
                if self.lvm:
                    # luks, lvm, home
                    fs_devices[devices['home']] = "ext4"
                else:
                    # luks, home
                    fs_devices[devices['luks_home']] = "ext4"

        for device in fs_devices:
            logging.debug("Device %s will have a %s filesystem",
                          device, fs_devices[device])

        return fs_devices

    def get_part_sizes(self, disk_size, start_part_sizes=1):
        part_sizes = {'disk': disk_size, 'boot': 256, 'efi': 0}

        if self.gpt and self.bootloader == "grub2":
            part_sizes['efi'] = 200

        cmd = ["grep", "MemTotal", "/proc/meminfo"]
        mem_total = call(cmd)
        mem_total = int(mem_total.split()[1])
        mem = mem_total / 1024

        # Suggested sizes from Anaconda installer
        if mem < 2048:
            part_sizes['swap'] = 2 * mem
        elif 2048 <= mem < 8192:
            part_sizes['swap'] = mem
        elif 8192 <= mem < 65536:
            part_sizes['swap'] = mem // 2
        else:
            part_sizes['swap'] = 4096

        # Max swap size is 10% of all available disk size
        max_swap = disk_size * 0.1
        if part_sizes['swap'] > max_swap:
            part_sizes['swap'] = max_swap

        part_sizes['swap'] = math.ceil(part_sizes['swap'])

        other_than_root_size = start_part_sizes + \
            part_sizes['efi'] + part_sizes['boot'] + part_sizes['swap']
        part_sizes['root'] = disk_size - other_than_root_size

        if self.home:
            # Decide how much we leave to root and how much we leave to /home
            # Question: why 5?
            new_root_part_size = part_sizes['root'] // 5
            if new_root_part_size > MAX_ROOT_SIZE:
                new_root_part_size = MAX_ROOT_SIZE
            elif new_root_part_size < MIN_ROOT_SIZE:
                new_root_part_size = MIN_ROOT_SIZE

            if new_root_part_size >= part_sizes['root']:
                # new_root_part_size can't be bigger than part_sizes['root'] !
                # this could happen if new_root_part_size == MIN_ROOT_SIZE but
                # our harddisk is smaller (detected using vbox)
                # Should we fail here or install without a separated /home partition?
                logging.warning(
                    "There's not enough free space to have a separate /home partition")
                self.home = False
                part_sizes['home'] = 0
            else:
                part_sizes['home'] = part_sizes['root'] - new_root_part_size
                part_sizes['root'] = new_root_part_size
        else:
            part_sizes['home'] = 0

        part_sizes['lvm_pv'] = part_sizes['swap'] + \
            part_sizes['root'] + part_sizes['home']

        for part in part_sizes:
            part_sizes[part] = int(part_sizes[part])

        return part_sizes

    def log_part_sizes(self, part_sizes):
        logging.debug("Total disk size: %dMiB", part_sizes['disk'])
        if self.gpt and self.bootloader == "grub2":
            logging.debug(
                "EFI System Partition (ESP) size: %dMiB", part_sizes['efi'])
        logging.debug("Boot partition size: %dMiB", part_sizes['boot'])

        if self.lvm:
            logging.debug("LVM physical volume size: %dMiB",
                          part_sizes['lvm_pv'])

        logging.debug("Swap partition size: %dMiB", part_sizes['swap'])
        logging.debug("Root partition size: %dMiB", part_sizes['root'])

        if self.home:
            logging.debug("Home partition size: %dMiB", part_sizes['home'])

    def run(self):
        key_files = ["/tmp/.keyfile-root", "/tmp/.keyfile-home"]

        # Partition sizes are expressed in MiB
        # Get just the disk size in MiB
        device = self.auto_device
        device_name = os.path.split(device)[1]
        size_path = os.path.join("/sys/block", device_name, 'size')
        base_path = os.path.split(size_path)[0]
        if os.path.exists(size_path):
            logical_path = os.path.join(base_path, "queue/logical_block_size")
            with open(logical_path, 'r') as f:
                logical_block_size = int(f.read())
            with open(size_path, 'r') as f:
                size = int(f.read())
            disk_size = ((logical_block_size * (size - 68)) / 1024) / 1024
        else:
            logging.error("Cannot detect %s device size", device)
            txt = _("Setup cannot detect size of your device, please use advanced "
                    "installation routine for partitioning and mounting devices.")
            raise InstallError(txt)

        start_part_sizes = 1

        part_sizes = self.get_part_sizes(disk_size, start_part_sizes)
        self.log_part_sizes(part_sizes)

        # Disable swap and unmount all partitions inside dest_dir
        unmount_all_in_directory(self.dest_dir)
        # Disable swap and unmount all partitions of device
        unmount_all_in_device(device)
        # Remove lvm in destination device
        remove_lvm(device)
        # Close luks devices in destination device
        close_reborn_luks_devices()

        printk(False)

        # WARNING:
        # Our computed sizes are all in mebibytes (MiB) i.e. powers of 1024, not metric megabytes.
        # These are 'M' in sgdisk and 'MiB' in parted.
        # If you use 'M' in parted you'll get MB instead of MiB, and you're gonna have a bad time.

        if self.gpt:
            # Clean partition table to avoid issues!
            wrapper.sgdisk("zap-all", device)

            # Clear all magic strings/signatures - mdadm, lvm, partition tables etc.
            wrapper.dd("/dev/zero", device, bs=512, count=2048)
            wrapper.wipefs(device)

            # Create fresh GPT
            wrapper.sgdisk("clear", device)
            wrapper.parted_mklabel(device, "gpt")

            # Inform the kernel of the partition change. Needed if the hard disk had a MBR partition table.
            err_msg = "Error informing the kernel of the partition change."
            call(["partprobe", device], msg=err_msg, fatal=True)

            part_num = 1

            if not self.uefi:
                # We don't allow BIOS+GPT right now, so this code will be never executed
                # We leave here just for future reference
                # Create BIOS Boot Partition
                # GPT GUID: 21686148-6449-6E6F-744E-656564454649
                # This partition is not required if the system is UEFI based,
                # as there is no such embedding of the second-stage code in that case
                wrapper.sgdisk_new(device, part_num, "BIOS_BOOT", 2, "EF02")
                part_num += 1

            if self.bootloader == "grub2":
                # Create EFI System Partition (ESP)
                # GPT GUID: C12A7328-F81F-11D2-BA4B-00A0C93EC93B
                wrapper.sgdisk_new(
                    device, part_num, "UEFI_SYSTEM", part_sizes['efi'], "EF00")
                part_num += 1

            # Create Boot partition
            if self.bootloader in ["systemd-boot", "refind"]:
                wrapper.sgdisk_new(
                    device, part_num, "REBORN_BOOT", part_sizes['boot'], "EF00")
            else:
                wrapper.sgdisk_new(
                    device, part_num, "REBORN_BOOT", part_sizes['boot'], "8300")
            part_num += 1

            if self.lvm:
                # Create partition for lvm (will store root, swap and home (if desired) logical volumes)
                wrapper.sgdisk_new(
                    device, part_num, "REBORN_LVM", part_sizes['lvm_pv'], "8E00")
                part_num += 1
            else:
                wrapper.sgdisk_new(
                    device, part_num, "REBORN_ROOT", part_sizes['root'], "8300")
                part_num += 1
                if self.home:
                    wrapper.sgdisk_new(
                        device, part_num, "REBORN_HOME", part_sizes['home'], "8302")
                    part_num += 1
                wrapper.sgdisk_new(
                    device, part_num, "REBORN_SWAP", 0, "8200")

            output = call(["sgdisk", "--print", device])
            logging.debug(output)
        else:
            # DOS MBR partition table
            # Start at sector 1 for 4k drive compatibility and correct alignment
            # Clean partitiontable to avoid issues!
            wrapper.dd("/dev/zero", device, bs=512, count=2048)
            wrapper.wipefs(device)

            # Create DOS MBR
            wrapper.parted_mklabel(device, "msdos")

            # Create boot partition (all sizes are in MiB)
            # if start is -1 wrapper.parted_mkpart assumes that our partition starts at 1 (first partition in disk)
            start = -1
            end = part_sizes['boot']
            wrapper.parted_mkpart(device, "primary", start, end)

            # Set boot partition as bootable
            wrapper.parted_set(device, "1", "boot", "on")

            if self.lvm:
                # Create partition for lvm (will store root, home (if desired), and swap logical volumes)
                start = end
                # end = start + part_sizes['lvm_pv']
                end = "-1s"
                wrapper.parted_mkpart(device, "primary", start, end)

                # Set lvm flag
                wrapper.parted_set(device, "2", "lvm", "on")
            else:
                # Create root partition
                start = end
                end = start + part_sizes['root']
                wrapper.parted_mkpart(device, "primary", start, end)

                if self.home:
                    # Create home partition
                    start = end
                    end = start + part_sizes['home']
                    wrapper.parted_mkpart(device, "primary", start, end)

                # Create an extended partition where we will put our swap partition
                start = end
                # end = start + part_sizes['swap']
                end = "-1s"
                wrapper.parted_mkpart(device, "extended", start, end)

                # Now create a logical swap partition
                start += 1
                end = "-1s"
                wrapper.parted_mkpart(
                    device, "logical", start, end, "linux-swap")

        printk(True)

        # Wait until /dev initialized correct devices
        call(["udevadm", "settle"])

        devices = self.get_devices()

        if self.gpt and self.bootloader == "grub2":
            logging.debug("EFI: %s", devices['efi'])

        logging.debug("Boot: %s", devices['boot'])
        logging.debug("Root: %s", devices['root'])

        if self.home:
            logging.debug("Home: %s", devices['home'])

        logging.debug("Swap: %s", devices['swap'])

        if self.luks:
            setup_luks(devices['luks_root'], "cryptReborn",
                       self.luks_password, key_files[0])
            if self.home and not self.lvm:
                setup_luks(devices['luks_home'], "cryptRebornHome",
                           self.luks_password, key_files[1])

        if self.lvm:
            logging.debug("Cnchi will setup LVM on device %s", devices['lvm'])

            err_msg = "Error creating LVM physical volume in device {0}"
            err_msg = err_msg.format(devices['lvm'])
            cmd = ["pvcreate", "-f", "-y", devices['lvm']]
            call(cmd, msg=err_msg, fatal=True)

            err_msg = "Error creating LVM volume group in device {0}"
            err_msg = err_msg.format(devices['lvm'])
            cmd = ["vgcreate", "-f", "-y", "RebornVG", devices['lvm']]
            call(cmd, msg=err_msg, fatal=True)

            # Fix issue 180
            # Check space we have now for creating logical volumes
            cmd = ["vgdisplay", "-c", "RebornVG"]
            vg_info = call(cmd, fatal=True)
            # Get column number 12: Size of volume group in kilobytes
            vg_size = int(vg_info.split(":")[11]) / 1024
            if part_sizes['lvm_pv'] > vg_size:
                logging.debug(
                    "Real RebornVG volume group size: %d MiB", vg_size)
                logging.debug("Reajusting logical volume sizes")
                diff_size = part_sizes['lvm_pv'] - vg_size
                part_sizes = self.get_part_sizes(
                    disk_size - diff_size, start_part_sizes)
                self.log_part_sizes(part_sizes)

            # Create LVM volumes
            err_msg = "Error creating LVM logical volume"

            size = str(int(part_sizes['root']))
            cmd = ["lvcreate", "--name", "RebornRoot",
                   "--size", size, "RebornVG"]
            call(cmd, msg=err_msg, fatal=True)

            if not self.home:
                # Use the remainig space for our swap volume
                cmd = ["lvcreate", "--name", "RebornSwap",
                       "--extents", "100%FREE", "RebornVG"]
                call(cmd, msg=err_msg, fatal=True)
            else:
                size = str(int(part_sizes['swap']))
                cmd = ["lvcreate", "--name", "RebornSwap",
                       "--size", size, "RebornVG"]
                call(cmd, msg=err_msg, fatal=True)
                # Use the remaining space for our home volume
                cmd = ["lvcreate", "--name", "RebornHome",
                       "--extents", "100%FREE", "RebornVG"]
                call(cmd, msg=err_msg, fatal=True)

        # We have all partitions and volumes created. Let's create its filesystems with mkfs.

        mount_points = {
            'efi': '/boot/efi',
            'boot': '/boot',
            'root': '/',
            'home': '/home',
            'swap': ''}

        labels = {
            'efi': 'UEFI_SYSTEM',
            'boot': 'RebornBoot',
            'root': 'RebornRoot',
            'home': 'RebornHome',
            'swap': 'RebornSwap'}

        fs_devices = self.get_fs_devices()

        # Note: Make sure the "root" partition is defined first!
        self.mkfs(devices['root'], fs_devices[devices['root']],
                  mount_points['root'], labels['root'])
        self.mkfs(devices['swap'], fs_devices[devices['swap']],
                  mount_points['swap'], labels['swap'])

        if self.gpt and self.bootloader in ["refind", "systemd-boot"]:
            # Format EFI System Partition (ESP) with vfat (fat32)
            self.mkfs(devices['boot'], fs_devices[devices['boot']],
                      mount_points['boot'], labels['boot'], "-F 32")
        else:
            self.mkfs(devices['boot'], fs_devices[devices['boot']],
                      mount_points['boot'], labels['boot'])

        # Note: Make sure the "boot" partition is defined before the "efi" one!
        if self.gpt and self.bootloader == "grub2":
            # Format EFI System Partition (ESP) with vfat (fat32)
            self.mkfs(devices['efi'], fs_devices[devices['efi']],
                      mount_points['efi'], labels['efi'], "-F 32")

        if self.home:
            self.mkfs(devices['home'], fs_devices[devices['home']],
                      mount_points['home'], labels['home'])

        # NOTE: encrypted and/or lvm2 hooks will be added to mkinitcpio.conf in process.py if necessary
        # NOTE: /etc/default/grub, /etc/stab and /etc/crypttab will be modified in process.py, too.

        if self.luks and self.luks_password == "":
            # Copy root keyfile to boot partition and home keyfile to root partition
            # user will choose what to do with it
            # THIS IS NONSENSE (BIG SECURITY HOLE), BUT WE TRUST THE USER TO FIX THIS
            # User shouldn't store the keyfiles unencrypted unless the medium itself is reasonably safe
            # (boot partition is not)

            err_msg = "Can't copy LUKS keyfile to the installation device."
            os.chmod(key_files[0], 0o400)
            boot_path = os.path.join(self.dest_dir, "boot")
            cmd = ['mv', key_files[0], boot_path]
            call(cmd, msg=err_msg)
            if self.home and not self.lvm:
                os.chmod(key_files[1], 0o400)
                luks_dir = os.path.join(self.dest_dir, 'etc/luks-keys')
                os.makedirs(luks_dir, mode=0o755, exist_ok=True)
                cmd = ['mv', key_files[1], luks_dir]
                call(cmd, msg=err_msg)


if __name__ == '__main__':
    import gettext

    _ = gettext.gettext

    logging.basicConfig(
        filename="/tmp/cnchi-autopartition.log", level=logging.DEBUG)

    auto = AutoPartition(
        dest_dir="/install",
        auto_device="/dev/sdb",
        use_luks=True,
        luks_password="luks",
        use_lvm=True,
        use_home=True,
        bootloader="grub2",
        callback_queue=None)
    auto.run()
