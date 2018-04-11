
#!/usr/bin/env python
# -*- coding: utf-8 -*-
#
#  features.py
#
#  Copyright © 2013-2017 Antergos
#
#  This file is part of Cnchi.
#
#  Cnchi is free software; you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation; either version 3 of the License, or
#  (at your option) any later version.
#
#  Cnchi is distributed in the hope that it will be useful,
#  but WITHOUT ANY WARRANTY; without even the implied warranty of
#  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#  GNU General Public License for more details.
#
#  The following additional terms are in effect as per Section 7 of the license:
#
#  The preservation of all legal notices and author attributions in
#  the material or in the Appropriate Legal Notices displayed
#  by works containing it is required.
#
#  You should have received a copy of the GNU General Public License
#  along with Cnchi; If not, see <http://www.gnu.org/licenses/>.


""" Features screen """
import gi
gi.require_version('Gtk', '3.0')
from gi.repository import Gtk

import subprocess
import logging
import desktop_info
import features_info

import misc.extra as misc

from gtkbasebox import GtkBaseBox


class Graphics(object):
    def nvidia(self):
        from hardware.modules.nvidia import Nvidia
        if Nvidia().detect():
            return True
        from hardware.modules.nvidia_340xx import Nvidia340xx
        if Nvidia340xx().detect():
            return True
        from hardware.modules.nvidia_304xx import Nvidia304xx
        if Nvidia304xx().detect():
            return True
        return False

    def amd(self):
        from hardware.modules.catalyst import Catalyst
        return Catalyst().detect()

    def i915(self):
        from hardware.modules.i915 import Intel915
        return Intel915().detect()

    def bumblebee(self):
        return self.nvidia() and self.i915()


class Features(GtkBaseBox):
    """ Features screen class """

    COL_TITLE = 1
    COL_DESCRIPTION = 2
    COL_SWITCH = 3

    def __init__(self, params, prev_page="desktop", next_page="mirrors"):
        """ Initializes features ui """
        super().__init__(self, params, "features", prev_page, next_page)

        self.detect = Graphics()

        self.listbox_rows = {}

        self.a11y = params['a11y']

        # Set up list box
        self.listbox = self.ui.get_object("listbox")
        self.listbox.set_selection_mode(Gtk.SelectionMode.NONE)
        self.listbox.set_sort_func(self.listbox_sort_by_name, None)

        # self.listbox.set_selection_mode(Gtk.SelectionMode.BROWSE)
        # self.listbox.connect("row-selected", self.on_listbox_row_selected)

        # This is initialized each time this screen is shown in prepare()
        self.features = None

        # Only show ufw rules and aur disclaimer info once
        self.info_already_shown = {"ufw": False, "aur": False}

        # Only load defaults for each DE the first time this screen is shown
        self.defaults_loaded = False

    @staticmethod
    def on_listbox_row_selected(listbox, listbox_row):
        """ Someone selected a different row of the listbox
            WARNING: IF LIST LAYOUT IS CHANGED THEN THIS SHOULD BE CHANGED ACCORDINGLY. """
        if listbox_row is not None:
            for vbox in listbox_row:
                switch = vbox.get_children()[2]
                if switch:
                    switch.set_active(not switch.get_active())

    def add_feature_icon(self, feature, box):
        """ Adds feature icon to listbox row box """
        if feature in features_info.ICON_NAMES:
            icon_name = features_info.ICON_NAMES[feature]
        else:
            logging.debug("No icon found for feature %s", feature)
            icon_name = "missing"

        image = Gtk.Image.new_from_icon_name(icon_name, Gtk.IconSize.DND)
        object_name = "image_" + feature
        image.set_name(object_name)
        image.set_property('margin_start', 10)
        self.listbox_rows[feature].append(image)
        box.pack_start(image, False, False, 0)

    def add_feature_label(self, feature, box):
        """ Adds feature title and label to listbox row box """
        text_box = Gtk.VBox()

        object_name = "label_title_" + feature
        label_title = Gtk.Label.new()
        label_title.set_halign(Gtk.Align.START)
        label_title.set_justify(Gtk.Justification.LEFT)
        label_title.set_name(object_name)
        self.listbox_rows[feature].append(label_title)
        text_box.pack_start(label_title, False, True, 0)

        object_name = "label_" + feature
        label = Gtk.Label.new()
        label.set_halign(Gtk.Align.START)
        label.set_justify(Gtk.Justification.LEFT)
        label.set_name(object_name)
        self.listbox_rows[feature].append(label)
        text_box.pack_start(label, False, False, 0)
        box.pack_start(text_box, False, False, 0)

    def on_switch_activated(self, switch, gparam):
        for feature in self.features:
            row = self.listbox_rows[feature]
            if row[Features.COL_SWITCH] == switch:
                is_active = switch.get_active()
                self.settings.set("feature_" + feature, is_active)

    def add_feature_switch(self, feature, box):
        object_name = "switch_" + feature
        switch = Gtk.Switch.new()
        switch.set_name(object_name)
        switch.set_property('margin_top', 10)
        switch.set_property('margin_bottom', 10)
        switch.set_property('margin_end', 10)
        switch.connect("notify::active", self.on_switch_activated)
        self.listbox_rows[feature].append(switch)
        box.pack_end(switch, False, False, 0)

    def fill_listbox(self):
        for listbox_row in self.listbox.get_children():
            listbox_row.destroy()

        self.listbox_rows = {}

        # Only add graphic-driver feature if an AMD or Nvidia is detected
        if "graphic_drivers" in self.features:
            allow = False
            if self.detect.amd():
                allow = True
            if self.detect.nvidia() and not self.detect.bumblebee():
                allow = True
            if not allow:
                logging.debug("Removing proprietary graphic drivers feature.")
                self.features.remove("graphic_drivers")

        for feature in self.features:
            box = Gtk.Box(spacing=20)
            box.set_name(feature + "-row")

            self.listbox_rows[feature] = []

            self.add_feature_icon(feature, box)
            self.add_feature_label(feature, box)
            self.add_feature_switch(feature, box)
            # Add row to our gtklist
            self.listbox.add(box)

        self.listbox.show_all()

    @staticmethod
    def listbox_sort_by_name(row1, row2, user_data):
        """ Sort function for listbox
            Returns : < 0 if row1 should be before row2, 0 if they are equal and > 0 otherwise
            WARNING: IF LAYOUT IS CHANGED IN fill_listbox THEN THIS SHOULD BE
            CHANGED ACCORDINGLY. """
        box1 = row1.get_child()
        txt_box1 = box1.get_children()[1]
        label1 = txt_box1.get_children()[0]

        box2 = row2.get_child()
        txt_box2 = box2.get_children()[1]
        label2 = txt_box2.get_children()[0]

        text = [label1.get_text(), label2.get_text()]
        # sorted_text = misc.sort_list(text, self.settings.get("locale"))
        sorted_text = misc.sort_list(text)

        # If strings are already well sorted return < 0
        if text[0] == sorted_text[0]:
            return -1

        # Strings must be swaped, return > 0
        return 1

    def set_row_text(self, feature, title, desc, tooltip):
        """ Set translated text to our listbox feature row """
        if feature in self.listbox_rows:
            title = "<span weight='bold' size='large'>{0}</span>".format(title)
            desc = "<span size='small'>{0}</span>".format(desc)
            row = self.listbox_rows[feature]
            row[Features.COL_TITLE].set_markup(title)
            row[Features.COL_DESCRIPTION].set_markup(desc)
            for widget in row:
                widget.set_tooltip_markup(tooltip)

    def translate_ui(self):
        """ Translates all ui elements """

        desktop = self.settings.get('desktop')
        txt = desktop_info.NAMES[desktop] + " - " + _("Feature Selection")
        self.header.set_subtitle(txt)

        for feature in self.features:
            title = _(features_info.TITLES[feature])
            desc = _(features_info.DESCRIPTIONS[feature])
            tooltip = _(features_info.TOOLTIPS[feature])
            self.set_row_text(feature, title, desc, tooltip)

        # Sort listbox items
        self.listbox.invalidate_sort()

    def switch_defaults_on(self):
        """ Enable some features by default """

        if 'bluetooth' in self.features:
            try:
                process1 = subprocess.Popen(["lsusb"], stdout=subprocess.PIPE)
                process2 = subprocess.Popen(
                    ["grep", "-i", "bluetooth"],
                    stdin=process1.stdout,
                    stdout=subprocess.PIPE)
                process1.stdout.close()
                out, process_error = process2.communicate()
                if out.decode() is not '':
                    row = self.listbox_rows['bluetooth']
                    row[Features.COL_SWITCH].set_active(True)
            except subprocess.CalledProcessError as err:
                logging.warning(
                    "Error checking bluetooth presence. Command %s failed: %s",
                    err.cmd,
                    err.output)

        if 'cups' in self.features:
            row = self.listbox_rows['cups']
            row[Features.COL_SWITCH].set_active(True)

        if 'visual' in self.features:
            row = self.listbox_rows['visual']
            row[Features.COL_SWITCH].set_active(True)

        if 'chromium' in self.features:
            row = self.listbox_rows['chromium']
            row[Features.COL_SWITCH].set_active(True)

        if 'aur' in self.features:
            row = self.listbox_rows['aur']
            row[Features.COL_SWITCH].set_active(True)

        if 'flash' in self.features:
            row = self.listbox_rows['flash']
            row[Features.COL_SWITCH].set_active(True)

        if 'lts' in self.features:
            row = self.listbox_rows['lts']
            row[Features.COL_SWITCH].set_active(True)

        if 'a11y' in self.features and self.a11y:
            row = self.listbox_rows['a11y']
            row[Features.COL_SWITCH].set_active(True)

        if 'firewall' in self.features:
            row = self.listbox_rows['firewall']
            row[Features.COL_SWITCH].set_active(True)

    def show_disclaimer_messages(self):
        """ Show ufw and AUR warning messages if necessary """
        # Show ufw info message if ufw is selected (show it only once)
        if self.settings.get("feature_firewall") and not self.info_already_shown["ufw"]:
            self.show_info_dialog("ufw")
            self.info_already_shown["ufw"] = True

        # Show AUR disclaimer if AUR is selected (show it only once)
        if self.settings.get("feature_aur") and not self.info_already_shown["aur"]:
            self.show_info_dialog("aur")
            self.info_already_shown["aur"] = True

    def show_info_dialog(self, feature):
        """ Some features show an information dialog when this screen is accepted """
        if feature == "aur":
            # Aur disclaimer
            txt1 = _("Arch User Repository - Disclaimer")
            txt2 = _("The Arch User Repository is a collection of user-submitted PKGBUILDs\n"
                     "that supplement software available from the official repositories.\n\n"
                     "The AUR is community driven and NOT supported by Arch or Reborn OS.\n")
        elif feature == "ufw":
            # Ufw rules info
            txt1 = _("Uncomplicated Firewall will be installed with these rules:")
            toallow = misc.get_network()
            txt2 = _("ufw default deny\nufw allow from {0}\nufw allow Transmission\n"
                     "ufw allow SSH").format(toallow)
        else:
            # No message
            return

        txt1 = "<big>{0}</big>".format(txt1)
        txt2 = "<i>{0}</i>".format(txt2)

        info = Gtk.MessageDialog(
            transient_for=self.get_main_window(),
            modal=True,
            destroy_with_parent=True,
            message_type=Gtk.MessageType.INFO,
            buttons=Gtk.ButtonsType.CLOSE)
        info.set_markup(txt1)
        info.format_secondary_markup(txt2)
        info.run()
        info.destroy()

    def ask_nginx(self):
        """ LAMP: Ask user if he wants Apache or Nginx """
        if self.settings.get("feature_lamp"):
            info = Gtk.MessageDialog(
                transient_for=self.get_main_window(),
                modal=True,
                destroy_with_parent=True,
                message_type=Gtk.MessageType.INFO,
                buttons=Gtk.ButtonsType.YES_NO)
            info.set_markup("LAMP / LEMP")
            msg = _(
                "Do you want to install the Nginx server instead of the Apache server?")
            info.format_secondary_markup(msg)
            response = info.run()
            info.destroy()
            if response == Gtk.ResponseType.YES:
                self.settings.set("feature_lemp", True)
            else:
                self.settings.set("feature_lemp", False)

    def store_switches(self):
        """ Store current feature selections """
        for feature in self.features:
            row = self.listbox_rows[feature]
            is_active = row[Features.COL_SWITCH].get_active()
            self.settings.set("feature_" + feature, is_active)
            if is_active:
                logging.debug("Feature '%s' has been selected", feature)

    def store_values(self):
        """ Go to next screen, but first save changes """

        self.store_switches()
        self.show_disclaimer_messages()
        self.ask_nginx()

        self.listbox_rows = {}

        return True

    def prepare(self, direction):
        """ Prepare features screen to get ready to show itself """
        # Each desktop has its own features
        desktop = self.settings.get('desktop')
        self.features = list(
            set(desktop_info.ALL_FEATURES) -
            set(desktop_info.EXCLUDED_FEATURES[desktop]))
        self.fill_listbox()
        self.translate_ui()
        self.show_all()
        if not self.defaults_loaded:
            self.switch_defaults_on()
            # Only load defaults once
            self.defaults_loaded = True
        else:
            # Load values user has chosen when this screen is shown again
            self.load_values()

    def load_values(self):
        """ Get previous selected switches values """
        for feature in self.features:
            row = self.listbox_rows[feature]
            is_active = self.settings.get("feature_" + feature)
            if row[Features.COL_SWITCH] is not None and is_active is not None:
                row[Features.COL_SWITCH].set_active(is_active)


# When testing, no _() is available
try:
    _("")
except NameError as err:
    def _(message):
        return message

if __name__ == '__main__':
    from test_screen import _, run

    run('Features')
