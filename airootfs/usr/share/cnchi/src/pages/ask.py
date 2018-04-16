#!/usr/bin/env python
# -*- coding: utf-8 -*-
#
# ask.py
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


""" Asks which type of installation the user wants to perform """

import os
import sys
import queue
import time
import logging
import subprocess

import bootinfo

import gi
gi.require_version('Gtk', '3.0')
from gi.repository import Gtk

from pages.gtkbasebox import GtkBaseBox

import misc.extra as misc

if __debug__:
    def _(x): return x


def check_alongside_disk_layout():
    """ Alongside can only work if user has followed the recommended
        BIOS-Based Disk-Partition Configurations shown in
        http://technet.microsoft.com/en-us/library/dd744364(v=ws.10).aspx """

    # TODO: Add more scenarios where alongside could work

    partitions = misc.get_partitions()
    # logging.debug(partitions)
    extended = False
    for partition in partitions:
        if misc.is_partition_extended(partition):
            extended = True

    if extended:
        return False

    # We just seek for sda partitions
    partitions_sda = []
    for partition in partitions:
        if "sda" in partition:
            partitions_sda.append(partition)

    # There's no extended partition, so all partitions must be primary
    if len(partitions_sda) < 4:
        return True

    return False


def load_zfs():
    cmd = ["modprobe", "zfs"]
    try:
        with misc.raised_privileges() as __:
            subprocess.check_output(cmd, stderr=subprocess.STDOUT)
        logging.debug("ZFS kernel module loaded successfully.")
    except subprocess.CalledProcessError as err:
        logging.debug(
            "Can't load ZFS kernel module: %s",
            err.output.decode())
        return False
    return True


class InstallationAsk(GtkBaseBox):
    def __init__(self, params, prev_page="mirrors", next_page=None):
        super().__init__(self, params, "ask", prev_page, next_page)

        data_dir = self.settings.get("data")

        partitioner_dir = os.path.join(
            data_dir,
            "images",
            "partitioner",
            "small")

        image = self.ui.get_object("automatic_image")
        path = os.path.join(partitioner_dir, "automatic.png")
        image.set_from_file(path)

        # image = self.ui.get_object("alongside_image")
        # path = os.path.join(partitioner_dir, "alongside.png")
        # image.set_from_file(path)

        image = self.ui.get_object("advanced_image")
        path = os.path.join(partitioner_dir, "advanced.png")
        image.set_from_file(path)

        self.other_oses = []

        # DISABLE ALONGSIDE INSTALLATION. IT'S NOT READY YET
        # enable_alongside = self.check_alongside()
        enable_alongside = False
        self.settings.set('enable_alongside', enable_alongside)
        '''
        if enable_alongside:
            msg = "Cnchi will enable the 'alongside' installation mode."
        else:
            msg = "Cnchi will NOT enable the 'alongside' installation mode."
        logging.debug(msg)
        '''
        # By default, select automatic installation
        self.next_page = "installation_automatic"
        self.settings.set("partition_mode", "automatic")

        self.is_zfs_available = load_zfs()

        self.enable_automatic_options(True)

        btn_label = _(
            "I need help with a Reborn OS / Windows(tm) dual boot setup!")
        self.alongside_wiki_btn = Gtk.Button.new_with_label(btn_label)
        self.alongside_wiki_btn.connect(
            'clicked', self.on_alongside_wiki_button_clicked)
        ask_box = self.ui.get_object("ask")
        ask_box.pack_start(self.alongside_wiki_btn, True, False, 0)

    def on_alongside_wiki_button_clicked(self, widget, data=None):
        try:
            from browser_window import BrowserWindow
            self.browser = BrowserWindow("Reborn OS Forum")
            url = "http://rebornos.freeforums.net/"
            self.browser.load_url(url)
        except Exception as err:
            logging.warning("Could not show Reborn OS Forum: ", err)

    def check_alongside(self):
        """ Check if alongside installation type must be enabled.
        Alongside only works when Windows is installed on sda  """

        enable_alongside = False

        # FIXME: Alongside does not work in UEFI systems
        if os.path.exists("/sys/firmware/efi"):
            msg = "The 'alongside' installation mode does not work in UEFI systems"
            logging.debug(msg)
            enable_alongside = False
        else:
            oses = bootinfo.get_os_dict()
            self.other_oses = []
            for key in oses:
                # We only check the first hard disk
                non_valid = ["unknown", "Swap",
                             "Data or Swap", self.other_oses]
                if "sda" in key and oses[key] not in non_valid:
                    self.other_oses.append(oses[key])

            if self.other_oses:
                for detected_os in self.other_oses:
                    if "windows" in detected_os.lower():
                        logging.debug("Windows(tm) OS detected.")
                        enable_alongside = True
                if not enable_alongside:
                    logging.debug("Windows(tm) OS not detected.")
                    enable_alongside = False
            else:
                logging.debug("Can't detect any OS in device sda.")
                enable_alongside = False

            if not check_alongside_disk_layout():
                msg = "Unsuported disk layout for the 'alongside' installation mode"
                logging.debug(msg)
                enable_alongside = False

        return enable_alongside

    def enable_automatic_options(self, status):
        """ Enables or disables automatic installation options """
        names = [
            "encrypt_checkbutton",
            "encrypt_label",
            "lvm_checkbutton",
            "lvm_label",
            "home_checkbutton",
            "home_label"]

        for name in names:
            obj = self.ui.get_object(name)
            obj.set_sensitive(status)

        names = ["zfs_checkbutton", "zfs_label"]
        for name in names:
            obj = self.ui.get_object(name)
            obj.set_sensitive(status and self.is_zfs_available)

    def prepare(self, direction):
        """ Prepares screen """
        # Read options and set widgets accordingly
        widgets_settings = {
            ('use_luks', 'encrypt_checkbutton'), ('use_lvm', 'lvm_checkbutton'),
            ('use_zfs', 'zfs_checkbutton'), ('use_home', 'home_checkbutton')}

        for (setting, widget) in widgets_settings:
            w = self.ui.get_object(widget)
            s = self.settings.get(setting)
            w.set_active(s)

        self.translate_ui()
        self.show_all()

        if not self.settings.get('enable_alongside'):
            self.hide_option("alongside")

        self.forward_button.set_sensitive(True)

    def hide_option(self, option):
        """ Hides widgets """
        widgets = []
        if option == "alongside":
            widgets = [
                "alongside_radiobutton",
                "alongside_description",
                "alongside_image"]

        for name in widgets:
            widget = self.ui.get_object(name)
            if widget is not None:
                widget.hide()

    def get_os_list_str(self):
        """ Get string with the detected os names """
        os_str = ""
        len_other_oses = len(self.other_oses)
        if len_other_oses > 0:
            if len_other_oses > 1:
                if len_other_oses == 2:
                    os_str = _(" and ").join(self.other_oses)
                else:
                    os_str = ", ".join(self.other_oses)
            else:
                os_str = self.other_oses[0]

        # Truncate string if it's too large
        if len(os_str) > 40:
            os_str = os_str[:40] + "..."

        return os_str

    def translate_ui(self):
        """ Translates screen before showing it """
        self.header.set_subtitle(_("Installation Type"))

        self.forward_button.set_always_show_image(True)
        self.forward_button.set_sensitive(True)

        description_style = '<span style="italic">{0}</span>'
        bold_style = '<span weight="bold">{0}</span>'

        oses_str = self.get_os_list_str()

        max_width_chars = 80

        # Automatic Install
        radio = self.ui.get_object("automatic_radiobutton")
        if len(oses_str) > 0:
            txt = _("Replace {0} with Reborn OS").format(oses_str)
        else:
            txt = _("Erase disk and install Reborn OS")
        radio.set_label(txt)
        radio.set_name('auto_radio_btn')

        label = self.ui.get_object("automatic_description")
        txt = _("Warning: This will erase ALL data on your disk.")
        # txt = description_style.format(txt)
        label.set_text(txt)
        label.set_name("automatic_desc")
        label.set_hexpand(False)
        label.set_line_wrap(True)
        label.set_max_width_chars(max_width_chars)

        button = self.ui.get_object("encrypt_checkbutton")
        txt = _("Encrypt this installation for increased security.")
        button.set_label(txt)
        button.set_name("enc_btn")
        button.set_hexpand(False)
        # button.set_line_wrap(True)
        # button.set_max_width_chars(max_width_chars)

        label = self.ui.get_object("encrypt_label")
        txt = _("You will be asked to create an encryption password in the "
                "next step.")
        # txt = description_style.format(txt)
        label.set_text(txt)
        label.set_name("enc_label")
        label.set_hexpand(False)
        label.set_line_wrap(True)
        label.set_max_width_chars(max_width_chars)

        button = self.ui.get_object("lvm_checkbutton")
        txt = _("Use LVM with this installation.")
        button.set_label(txt)
        button.set_name("lvm_btn")
        button.set_hexpand(False)
        # button.set_line_wrap(True)
        # button.set_max_width_chars(max_width_chars)

        label = self.ui.get_object("lvm_label")
        txt = _("This will setup LVM and allow you to easily manage "
                "partitions and create snapshots.")
        # txt = description_style.format(txt)
        label.set_text(txt)
        label.set_name("lvm_label")
        label.set_hexpand(False)
        label.set_line_wrap(True)
        label.set_max_width_chars(max_width_chars)

        button = self.ui.get_object("zfs_checkbutton")
        txt = _("Use ZFS with this installation.")
        button.set_label(txt)
        button.set_name("zfs_btn")
        button.set_hexpand(False)
        # button.set_line_wrap(True)
        # button.set_max_width_chars(max_width_chars)

        label = self.ui.get_object("zfs_label")
        txt = _("This will setup ZFS on your drive(s).")
        # txt = description_style.format(txt)
        label.set_text(txt)
        label.set_name("zfs_label")
        label.set_hexpand(False)
        label.set_line_wrap(True)
        label.set_max_width_chars(max_width_chars)

        button = self.ui.get_object("home_checkbutton")
        txt = _("Set your Home in a different partition/volume")
        button.set_label(txt)
        button.set_name("home_btn")
        button.set_hexpand(False)
        # button.set_line_wrap(True)
        # button.set_max_width_chars(max_width_chars)

        label = self.ui.get_object("home_label")
        txt = _("This will setup your /home directory in a different "
                "partition or volume.")
        # txt = description_style.format(txt)
        label.set_text(txt)
        label.set_name("home_label")
        label.set_hexpand(False)
        label.set_line_wrap(True)
        label.set_max_width_chars(max_width_chars)

        # Alongside Install (For now, only works with Windows)
        # if len(oses_str) > 0:
        #     txt = _("Install Reborn OS alongside {0}").format(oses_str)
        #     radio = self.ui.get_object("alongside_radiobutton")
        #     radio.set_label(txt)
        #
        #     label = self.ui.get_object("alongside_description")
        #     txt = _("Installs Reborn OS without removing {0}").format(oses_str)
        #     txt = description_style.format(txt)
        #     label.set_markup(txt)
        #     label.set_line_wrap(True)
        #
        #     intro_txt = _("This computer has {0} installed.").format(oses_str)
        #     intro_txt = intro_txt + "\n" + _("What do you want to do?")
        # else:
        intro_txt = _("How would you like to proceed?")

        intro_label = self.ui.get_object("introduction")
        # intro_txt = bold_style.format(intro_txt)
        intro_label.set_text(intro_txt)
        intro_label.set_name("intro_label")
        intro_label.set_hexpand(False)
        intro_label.set_line_wrap(True)
        intro_label.set_max_width_chars(max_width_chars)

        # Advanced Install
        radio = self.ui.get_object("advanced_radiobutton")
        radio.set_label(
            _("Choose exactly where Reborn OS should be installed."))
        radio.set_name("advanced_radio_btn")

        label = self.ui.get_object("advanced_description")
        txt = _("Edit partition table and choose mount points.")
        # txt = description_style.format(txt)
        label.set_text(txt)
        label.set_name("adv_desc_label")
        label.set_hexpand(False)
        label.set_line_wrap(True)
        label.set_max_width_chars(max_width_chars)

    def store_values(self):
        """ Store selected values """
        check = self.ui.get_object("encrypt_checkbutton")
        use_luks = check.get_active()

        check = self.ui.get_object("lvm_checkbutton")
        use_lvm = check.get_active()

        check = self.ui.get_object("zfs_checkbutton")
        use_zfs = check.get_active()

        check = self.ui.get_object("home_checkbutton")
        use_home = check.get_active()

        self.settings.set('use_lvm', use_lvm)
        self.settings.set('use_luks', use_luks)
        self.settings.set('use_luks_in_root', True)
        self.settings.set('luks_root_volume', 'cryptReborn')
        self.settings.set('use_zfs', use_zfs)
        self.settings.set('use_home', use_home)

        if not self.settings.get('use_zfs'):
            if self.settings.get('use_luks'):
                logging.info(
                    "Reborn OS installation will be encrypted using LUKS")
            if self.settings.get('use_lvm'):
                logging.info("Reborn OS will be installed using LVM volumes")
                if self.settings.get('use_home'):
                    logging.info(
                        "Reborn OS will be installed using a separate /home volume.")
            elif self.settings.get('use_home'):
                logging.info(
                    "Reborn OS will be installed using a separate /home partition.")
        else:
            logging.info("Reborn OS will be installed using ZFS")
            if self.settings.get('use_luks'):
                logging.info("Reborn OS ZFS installation will be encrypted")
            if self.settings.get('use_home'):
                logging.info(
                    "Reborn OS will be installed using a separate /home volume.")

        if self.next_page == "installation_alongside":
            self.settings.set('partition_mode', 'alongside')
        elif self.next_page == "installation_advanced":
            self.settings.set('partition_mode', 'advanced')
        elif self.next_page == "installation_automatic":
            self.settings.set('partition_mode', 'automatic')
        elif self.next_page == "installation_zfs":
            self.settings.set('partition_mode', 'zfs')

        # Get sure other modules will know if zfs is activated or not
        self.settings.set("zfs", use_zfs)

        # Check if there are still processes running...
        self.wait()

        return True

    def wait(self):
        """ Check if there are still processes running and
            waits for them to finish """
        must_wait = False
        for proc in self.process_list:
            if proc.is_alive():
                must_wait = True
                break

        if not must_wait:
            return

        txt1 = _("Ranking mirrors")
        txt1 = "<big>{0}</big>".format(txt1)

        txt2 = _("Cnchi is still updating and optimizing your mirror lists.")
        txt2 += "\n\n"
        txt2 += _("Please be patient...")
        txt2 = "<i>{0}</i>".format(txt2)

        wait_ui = Gtk.Builder()
        ui_file = os.path.join(self.ui_dir, "wait.ui")
        wait_ui.add_from_file(ui_file)

        lbl1 = wait_ui.get_object("label1")
        lbl1.set_markup(txt1)

        lbl2 = wait_ui.get_object("label2")
        lbl2.set_markup(txt2)

        progress_bar = wait_ui.get_object("progressbar")

        wait_window = wait_ui.get_object("wait_window")
        wait_window.set_modal(True)
        wait_window.set_transient_for(self.get_main_window())
        wait_window.set_default_size(320, 240)
        wait_window.set_position(Gtk.WindowPosition.CENTER)
        wait_window.show_all()

        ask_box = self.ui.get_object("ask")
        if ask_box:
            ask_box.set_sensitive(False)

        logging.debug("Waiting for all external processes to finish...")
        while must_wait:
            must_wait = False
            for proc in self.process_list:
                # This waits until process finishes, no matter the time.
                if proc.is_alive():
                    must_wait = True
            # Just wait...
            time.sleep(0.1)
            # Update our progressbar dialog
            progress_bar.pulse()
            while Gtk.events_pending():
                Gtk.main_iteration()
        logging.debug(
            "All external processes are finished. Installation can go on")
        wait_window.hide()

        if ask_box:
            ask_box.set_sensitive(True)

    def get_next_page(self):
        return self.next_page

    def on_automatic_radiobutton_toggled(self, widget):
        """ Automatic selected, enable all options """
        if widget.get_active():
            check = self.ui.get_object("zfs_checkbutton")
            if check.get_active():
                self.next_page = "installation_zfs"
            else:
                self.next_page = "installation_automatic"
            # Enable all options
            self.enable_automatic_options(True)

    def on_automatic_lvm_checkbutton_toggled(self, widget):
        if widget.get_active():
            self.next_page = "installation_automatic"
            check = self.ui.get_object("zfs_checkbutton")
            if check.get_active():
                check.set_active(False)

    def on_automatic_zfs_checkbutton_toggled(self, widget):
        if widget.get_active():
            self.next_page = "installation_zfs"
            check = self.ui.get_object("lvm_checkbutton")
            if check.get_active():
                check.set_active(False)
        else:
            self.next_page = "installation_automatic"

    def on_alongside_radiobutton_toggled(self, widget):
        """ Alongside selected, disable all automatic options """
        if widget.get_active():
            self.next_page = "installation_alongside"
            self.enable_automatic_options(False)

    def on_advanced_radiobutton_toggled(self, widget):
        """ Advanced selected, disable all automatic options """
        if widget.get_active():
            self.next_page = "installation_advanced"
            self.enable_automatic_options(False)


if __name__ == '__main__':
    from test_screen import _, run

    run('InstallationAsk')
