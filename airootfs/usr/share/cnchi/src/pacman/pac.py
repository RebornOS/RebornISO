#!/usr/bin/env python
# -*- coding: utf-8 -*-
#
#  pac.py
#
#  This code is based on previous work by Rémy Oudompheng <remy@archlinux.org>
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


""" Module interface to pyalpm """

import sys
import math
import logging
import os
import queue
import inspect
import traceback
from collections import OrderedDict

try:
    _("x")
except NameError:
    import gettext
    _ = gettext.gettext

import pacman.alpm_events as alpm
import pacman.pkginfo as pkginfo
import pacman.pacman_conf as config

try:
    import pyalpm
except ImportError as err:
    # This is already logged elsewhere
    # logging.error(err)
    pass

_DEFAULT_ROOT_DIR = "/"
_DEFAULT_DB_PATH = "/var/lib/pacman"


class Pac(object):
    """ Communicates with libalpm using pyalpm """

    def __init__(self, conf_path="/etc/pacman.conf", callback_queue=None):
        self.callback_queue = callback_queue

        self.conflict_to_remove = None

        self.handle = None

        self.logger = None
        self.setup_logger()

        # Some download indicators (used in cb_dl callback)
        self.last_dl_filename = None
        self.last_dl_progress = 0
        self.last_dl_total_size = 0

        # Total packages to download
        self.total_packages_to_download = 0
        self.downloaded_packages = 0

        # Store package total download size
        self.total_download_size = 0

        self.last_event = {}

        if not os.path.exists(conf_path):
            raise pyalpm.error

        if conf_path is not None and os.path.exists(conf_path):
            self.config = config.PacmanConfig(conf_path)
            self.initialize_alpm()
            logging.debug('ALPM repository database order is: %s',
                          self.config.repo_order)
        else:
            raise pyalpm.error

    def get_handle(self):
        """ Return alpm handle """
        return self.handle

    def get_config(self):
        """ Get pacman.conf config """
        return self.config

    def initialize_alpm(self):
        """ Set alpm setup """
        if self.config is not None:
            root_dir = self.config.options["RootDir"]
            db_path = self.config.options["DBPath"]
        else:
            root_dir = _DEFAULT_ROOT_DIR
            db_path = _DEFAULT_DB_PATH

        self.handle = pyalpm.Handle(root_dir, db_path)

        logging.debug(
            "ALPM initialised with root dir %s and db path %s", root_dir, db_path)

        if self.handle is None:
            raise pyalpm.error

        if self.config is not None:
            self.config.apply(self.handle)

        # Set callback functions
        # Callback used for logging
        self.handle.logcb = self.cb_log
        # Callback used to report download progress
        self.handle.dlcb = self.cb_dl
        # Callback used to report total download size
        self.handle.totaldlcb = self.cb_totaldl
        # Callback used for events
        self.handle.eventcb = self.cb_event
        # Callback used for questions
        self.handle.questioncb = self.cb_question
        # Callback used for operation progress
        self.handle.progresscb = self.cb_progress
        # Downloading callback
        self.handle.fetchcb = None

    def release(self):
        """ Release alpm handle """
        if self.handle is not None:
            del self.handle
            self.handle = None

    @staticmethod
    def finalize_transaction(transaction):
        """ Commit a transaction """
        all_ok = False
        try:
            logging.debug("Prepare alpm transaction...")
            transaction.prepare()
            logging.debug("Commit alpm transaction...")
            transaction.commit()
            all_ok = True
        except pyalpm.error as pyalpm_error:
            msg = _("Can't finalize alpm transaction: %s")
            logging.error(msg, pyalpm_error)
            traceback.print_exc()
        finally:
            logging.debug("Releasing alpm transaction...")
            transaction.release()
            logging.debug("Alpm transaction done.")
        return all_ok

    def init_transaction(self, options=None):
        """ Transaction initialization """
        if options is None:
            options = {}

        transaction = None

        try:
            transaction = self.handle.init_transaction(
                nodeps=options.get('nodeps', False),
                dbonly=options.get('dbonly', False),
                force=options.get('force', False),
                needed=options.get('needed', False),
                alldeps=(options.get('mode', None) ==
                         pyalpm.PKG_REASON_DEPEND),
                allexplicit=(options.get('mode', None) ==
                             pyalpm.PKG_REASON_EXPLICIT),
                cascade=options.get('cascade', False),
                nosave=options.get('nosave', False),
                recurse=(options.get('recursive', 0) > 0),
                recurseall=(options.get('recursive', 0) > 1),
                unneeded=options.get('unneeded', False),
                downloadonly=options.get('downloadonly', False))
        except pyalpm.error as pyalpm_error:
            logging.error("Can't init alpm transaction: %s", pyalpm_error)
        return transaction

    def remove(self, pkg_names, options=None):
        """ Removes a list of package names """

        if not options:
            options = {}

        # Prepare target list
        targets = []
        database = self.handle.get_localdb()
        for pkg_name in pkg_names:
            pkg = database.get_pkg(pkg_name)
            if pkg is None:
                logging.error("Target %s not found", pkg_name)
                return False
            targets.append(pkg)

        transaction = self.init_transaction(options)

        if transaction is None:
            logging.error("Can't init transaction")
            return False

        for pkg in targets:
            logging.debug(
                "Adding package '%s' to remove transaction", pkg.name)
            transaction.remove_pkg(pkg)

        return self.finalize_transaction(transaction)

    def refresh(self):
        """ Sync databases like pacman -Sy """
        if self.handle is None:
            logging.error("alpm is not initialised")
            raise pyalpm.error

        force = True
        res = True
        for database in self.handle.get_syncdbs():
            transaction = self.init_transaction()
            if transaction:
                database.update(force)
                transaction.release()
            else:
                res = False
        return res

    def install(self, pkgs, conflicts=None, options=None):
        """ Install a list of packages like pacman -S """

        if not conflicts:
            conflicts = []

        if not options:
            options = {}

        if self.handle is None:
            logging.error("alpm is not initialised")
            raise pyalpm.error

        if len(pkgs) == 0:
            logging.error("Package list is empty")
            raise pyalpm.error

        # Discard duplicates
        pkgs = list(set(pkgs))

        # `alpm.handle.get_syncdbs()` returns a list (the order is important) so we
        # have to ensure we don't clobber the priority of the repos.
        repos = OrderedDict()
        repo_order = []
        one_repo_groups = ['cinnamon', 'mate', 'mate-extra']
        db_match = [db for db in self.handle.get_syncdbs()
                    if 'antergos' == db.name]
        antdb = OrderedDict()
        antdb['antergos'] = db_match[0]
        one_repo_groups = [antdb['antergos'].read_grp(one_repo_group)
                           for one_repo_group in one_repo_groups]
        one_repo_pkgs = {pkg for one_repo_group in one_repo_groups
                         for pkg in one_repo_group[1] if one_repo_group}

        for syncdb in self.handle.get_syncdbs():
            repo_order.append(syncdb)
            repos[syncdb.name] = syncdb

        targets = []
        logging.debug('REPO DB ORDER IS: %s', repo_order)

        for name in pkgs:
            _repos = repos

            if name in one_repo_pkgs:
                # pkg should be sourced from the antergos repo only.
                _repos = antdb

            result_ok, pkg = self.find_sync_package(name, _repos)

            if result_ok:
                # Check that added package is not in our conflicts list
                if pkg.name not in conflicts:
                    targets.append(pkg.name)
            else:
                # Couldn't find the package, check if it's a group
                group_pkgs = self.get_group_pkgs(name)
                if group_pkgs is not None:
                    # It's a group
                    for group_pkg in group_pkgs:
                        # Check that added package is not in our conflicts list
                        # Ex: connman conflicts with netctl(openresolv),
                        # which is installed by default with base group
                        if group_pkg.name not in conflicts:
                            targets.append(group_pkg.name)
                else:
                    # No, it wasn't neither a package nor a group. As we don't
                    # know if this error is fatal or not, we'll register it and
                    # we'll allow to continue.
                    logging.error(
                        "Can't find a package or group called '%s'", name)

        # Discard duplicates
        targets = list(set(targets))
        logging.debug(targets)

        if len(targets) == 0:
            logging.error("No targets found")
            return False

        num_targets = len(targets)
        logging.debug("%d target(s) found", num_targets)

        # Maybe not all this packages will be downloaded, but it's
        # how many have to be there before starting the installation
        self.total_packages_to_download = num_targets

        transaction = self.init_transaction(options)

        if transaction is None:
            logging.error("Can't initialize alpm transaction")
            return False

        for i in range(0, num_targets):
            result_ok, pkg = self.find_sync_package(targets.pop(), repos)
            if result_ok:
                transaction.add_pkg(pkg)
            else:
                logging.warning(pkg)

        return self.finalize_transaction(transaction)

    def upgrade(self, pkgs, conflicts=None, options=None):
        """ Install a list package tarballs like pacman -U """

        conflicts = conflicts if conflicts else []
        options = options if options else {}

        if self.handle is None:
            logging.error("alpm is not initialised")
            raise pyalpm.error

        if len(pkgs) == 0:
            logging.error("Package list is empty")
            raise pyalpm.error

        # Discard duplicates
        pkgs = list(set(pkgs))

        self.handle.get_localdb()

        # Prepare targets list
        targets = []
        for tarball in pkgs:
            pkg = self.handle.load_pkg(tarball)
            targets.append(pkg)

        transaction = self.init_transaction(options)

        if transaction is None:
            logging.error("Can't initialize alpm transaction")
            return False

        for pkg in targets:
            transaction.add_pkg(pkg)

        return self.finalize_transaction(transaction)

    @staticmethod
    def find_sync_package(pkgname, syncdbs):
        """ Finds a package name in a list of DBs
        :rtype : tuple (True/False, package or error message)
        """
        for database in syncdbs.values():
            pkg = database.get_pkg(pkgname)
            if pkg is not None:
                return True, pkg
        return False, "Package '{0}' was not found.".format(pkgname)

    def get_group_pkgs(self, group):
        """ Get group's packages """
        for repo in self.handle.get_syncdbs():
            grp = repo.read_grp(group)
            if grp is not None:
                name, pkgs = grp
                return pkgs
        return None

    def get_packages_info(self, pkg_names=None):
        """ Get information about packages like pacman -Si """
        if not pkg_names:
            pkg_names = []
        packages_info = {}
        if len(pkg_names) == 0:
            # Store info from all packages from all repos
            for repo in self.handle.get_syncdbs():
                for pkg in repo.pkgcache:
                    packages_info[pkg.name] = pkginfo.get_pkginfo(
                        pkg,
                        level=2,
                        style='sync')
        else:
            repos = OrderedDict((database.name, database)
                                for database in self.handle.get_syncdbs())
            for pkg_name in pkg_names:
                result_ok, pkg = self.find_sync_package(pkg_name, repos)
                if result_ok:
                    packages_info[pkg_name] = pkginfo.get_pkginfo(
                        pkg,
                        level=2,
                        style='sync')
                else:
                    packages_info = {}
                    logging.error(pkg)
        return packages_info

    def get_package_info(self, pkg_name):
        """ Get information about packages like pacman -Si """
        repos = OrderedDict((database.name, database)
                            for database in self.handle.get_syncdbs())
        result_ok, pkg = self.find_sync_package(pkg_name, repos)
        if result_ok:
            info = pkginfo.get_pkginfo(pkg, level=2, style='sync')
        else:
            logging.error(pkg)
            info = {}
        return info

    def queue_event(self, event_type, event_text=""):
        """ Queues events to the event list in the GUI thread """

        if event_type == "percent":
            # Limit percent to two decimal
            event_text = "{0:.2f}".format(event_text)

        if event_type in self.last_event:
            if self.last_event[event_type] == event_text:
                # Do not enqueue the same event twice
                return

        self.last_event[event_type] = event_text

        if event_type == "error":
            # Format message to show file, function, and line where the
            # error was issued
            # Get the previous frame in the stack, otherwise it would be
            # this function
            func = inspect.currentframe().f_back.f_code
            # Dump the message + the name of this function to the log.
            event_text = "{0}: {1} in {2}:{3}".format(
                event_text,
                func.co_name,
                func.co_filename,
                func.co_firstlineno)

        if self.callback_queue is None:
            if event_type == "error":
                logging.error(event_text)
                sys.exit(1)
            else:
                logging.debug(event_text)
        else:
            try:
                self.callback_queue.put_nowait((event_type, event_text))
            except queue.Full:
                logging.warning("Callback queue is full")

            if event_type == "error":
                # We've queued a fatal event so we must exit installer_process
                # process wait until queue is empty (is emptied in slides.py,
                # in the GUI thread), then exit
                self.callback_queue.join()
                sys.exit(1)

    # Callback functions

    @staticmethod
    def cb_question(*args):
        """ Called to get user input """
        pass

    def cb_totaldl(self, total_size):
        """ Stores total download size for use in cb_progress """
        self.total_download_size = total_size

    def cb_event(self, event_type, event_txt):
        """ Converts action ID to descriptive text and enqueues it to the events queue """

        if event_type is alpm.ALPM_EVENT_CHECKDEPS_START:
            action = _('Checking dependencies...')
        elif event_type is alpm.ALPM_EVENT_FILECONFLICTS_START:
            action = _('Checking file conflicts...')
        elif event_type is alpm.ALPM_EVENT_RESOLVEDEPS_START:
            action = _('Resolving dependencies...')
        elif event_type is alpm.ALPM_EVENT_INTERCONFLICTS_START:
            action = _('Checking inter conflicts...')
        elif event_type is alpm.ALPM_EVENT_PACKAGE_OPERATION_START:
            # Shown in cb_progress
            action = ""
        elif event_type is alpm.ALPM_EVENT_INTEGRITY_START:
            action = _('Checking integrity...')
        elif event_type is alpm.ALPM_EVENT_LOAD_START:
            action = _('Loading packages...')
        elif event_type is alpm.ALPM_EVENT_DELTA_INTEGRITY_START:
            action = _("Checking target delta's integrity...")
        elif event_type is alpm.ALPM_EVENT_DELTA_PATCHES_START:
            action = _('Applying deltas to packages...')
        elif event_type is alpm.ALPM_EVENT_DELTA_PATCH_START:
            action = _('Applying delta patch to target package...')
        elif event_type is alpm.ALPM_EVENT_RETRIEVE_START:
            action = _('Downloading files from the repository...')
        elif event_type is alpm.ALPM_EVENT_DISKSPACE_START:
            action = _('Checking disk space...')
        elif event_type is alpm.ALPM_EVENT_KEYRING_START:
            action = _('Checking keys in keyring...')
        elif event_type is alpm.ALPM_EVENT_KEY_DOWNLOAD_START:
            action = _('Downloading missing keys into the keyring...')
        else:
            action = ""

        if len(action) > 0:
            self.queue_event('info', action)

    def cb_log(self, level, line):
        """ Log pyalpm warning and error messages.
            Possible message types:
            LOG_ERROR, LOG_WARNING, LOG_DEBUG, LOG_FUNCTION """

        # Strip ending '\n'
        line = line.rstrip()

        # Log everything to cnchi-alpm.log
        self.logger.debug(line)

        ignore = False
        partials = ['error 0',
                    'error 32',
                    'extracting',
                    'error 31 from alpm_db_get_pkg',
                    'command failed to execute correctly',
                    'extract: skipping dir extraction',
                    'loading package data for']

        for partial in partials:
            if partial in line:
                ignore = True
                break

        if ignore or not level:
            return

        if level == pyalpm.LOG_ERROR:
            logging.error(line)
        elif level == pyalpm.LOG_WARNING:
            # Alpm outputs non-english log messages so we can't target certain
            # useless warnings. I think most of the warnings are useless anyway.
            # We can revisit this later if need be.
            logging.debug(line)

    def cb_progress(self, target, percent, total, current):
        """ Shows install progress """
        if target:
            msg = _("Installing {0} ({1}/{2})").format(target, current, total)
            self.queue_event('info', msg)
            percent = current / total
            self.queue_event('percent', percent)
        else:
            percent /= 100
            self.queue_event('percent', percent)

    def cb_dl(self, filename, tx, total):
        """ Shows downloading progress """
        # Check if a new file is coming
        if filename != self.last_dl_filename or self.last_dl_total_size != total:
            self.last_dl_filename = filename
            self.last_dl_total_size = total
            self.last_dl_progress = 0

            # If pacman is just updating databases total_download_size will be zero
            if self.total_download_size == 0:
                ext = ".db"
                if filename.endswith(ext):
                    filename = filename[:-len(ext)]
                text = _("Updating {0} database").format(filename)
            else:
                ext = ".pkg.tar.xz"
                if filename.endswith(ext):
                    filename = filename[:-len(ext)]
                self.downloaded_packages += 1
                # i = self.downloaded_packages
                # n = self.total_packages_to_download
                # text = _("Downloading {0}... ({1}/{2})").format(filename, i, n)
                text = _("Downloading {0}...").format(filename)

            self.queue_event('info', text)
            self.queue_event('percent', 0)
        else:
            # Compute a progress indicator
            if self.last_dl_total_size > 0:
                progress = tx / self.last_dl_total_size
            else:
                # If total is unknown, use log(kBytes)²/2
                progress = (math.log(1 + tx / 1024) ** 2 / 2) / 100

            # Update progress only if it has grown
            if progress > self.last_dl_progress:
                self.last_dl_progress = progress
                self.queue_event('percent', progress)

    def is_package_installed(self, package_name):
        """ Check if package is already installed """
        database = self.handle.get_localdb()
        pkgs = database.search(*[package_name])
        names = []
        for pkg in pkgs:
            names.append(pkg.name)
        if package_name in names:
            return True
        else:
            return False

    def setup_logger(self):
        """ Configure our logger """
        self.logger = logging.getLogger(__name__)

        self.logger.setLevel(logging.DEBUG)

        self.logger.propagate = False

        # Log format
        formatter = logging.Formatter(
            fmt="%(asctime)s [%(levelname)s] %(filename)s(%(lineno)d) %(funcName)s(): %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S")

        if not self.logger.hasHandlers():
            # File logger
            try:
                file_handler = logging.FileHandler(
                    '/tmp/cnchi-alpm.log', mode='w')
                file_handler.setLevel(logging.DEBUG)
                file_handler.setFormatter(formatter)
                self.logger.addHandler(file_handler)
            except PermissionError as permission_error:
                print("Can't open /tmp/cnchi-alpm.log : ", permission_error)


def test():
    """ Test case """
    import gettext
    _ = gettext.gettext

    formatter = logging.Formatter(
        '[%(asctime)s] [%(module)s] %(levelname)s: %(message)s',
        "%Y-%m-%d %H:%M:%S")
    logger = logging.getLogger()
    logger.setLevel(logging.DEBUG)
    stream_handler = logging.StreamHandler()
    stream_handler.setLevel(logging.DEBUG)
    stream_handler.setFormatter(formatter)
    logger.addHandler(stream_handler)

    try:
        pacman = Pac("/etc/pacman.conf")
    except Exception as ex:
        print("Can't initialize pyalpm: ", ex)
        sys.exit(1)

    try:
        pacman.do_refresh()
    except pyalpm.error as err:
        print("Can't update databases: ", err)
        sys.exit(1)

    pacman_options = {"downloadonly": True}
    # pacman.do_install(pkgs=["base"], conflicts=[], options=pacman_options)
    pacman.release()


if __name__ == "__main__":
    test()
