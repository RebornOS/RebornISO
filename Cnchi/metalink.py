#!/usr/bin/env python
# -*- coding: utf-8 -*-
#
#  metalink.py
#
#  Code from pm2ml Copyright (C) 2012-2013 Xyne
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


""" Operations with metalinks """

import logging
import tempfile
import os

import xml.dom.minidom as minidom
import hashlib
import re
import argparse

from collections import deque

import pyalpm

try:
    import xml.etree.cElementTree as eTree
except ImportError:
    import xml.etree.ElementTree as eTree

MAX_URLS = 15


def get_info(metalink):
    """ Reads metalink xml info and returns it """

    # tag = "{urn:ietf:params:xml:ns:metalink}"

    temp_file = tempfile.NamedTemporaryFile(delete=False)
    temp_file.write(str(metalink).encode('UTF-8'))
    temp_file.close()

    metalink_info = {}
    element = {}

    for event, elem in eTree.iterparse(temp_file.name, events=('start', 'end')):
        if event == "start":
            if elem.tag.endswith("file"):
                element['filename'] = elem.attrib['name']
            elif elem.tag.endswith("identity"):
                element['identity'] = elem.text
            elif elem.tag.endswith("size"):
                element['size'] = elem.text
            elif elem.tag.endswith("version"):
                element['version'] = elem.text
            elif elem.tag.endswith("description"):
                element['description'] = elem.text
            elif elem.tag.endswith("hash"):
                element['hash'] = elem.text
            elif elem.tag.endswith("url"):
                try:
                    element['urls'].append(elem.text)
                except KeyError:
                    element['urls'] = [elem.text]
        if event == "end":
            if elem.tag.endswith("file"):
                # Limit to MAX_URLS for file
                if len(element['urls']) > MAX_URLS:
                    element['urls'] = element['urls'][:MAX_URLS]
                key = element['identity']
                metalink_info[key] = element.copy()
                element.clear()
                elem.clear()

    if os.path.exists(temp_file.name):
        os.remove(temp_file.name)

    return metalink_info


def create(alpm, package_name, pacman_conf_file):
    """ Creates a metalink to download package_name and its dependencies """

    # options = ["--conf", pacman_conf_file, "--noconfirm", "--all-deps", "--needed"]
    options = ["--conf", pacman_conf_file, "--noconfirm", "--all-deps"]

    if package_name is "databases":
        options.append("--refresh")
    else:
        options.append(package_name)

    try:
        download_queue, not_found, missing_deps = build_download_queue(
            alpm, args=options)
    except Exception as ex:
        template = "Unable to create download queue for package {0}. An exception of type {1} occured. Arguments:\n{2!r}"
        message = template.format(package_name, type(ex).__name__, ex.args)
        logging.error(message)
        return None

    if not_found:
        msg = "Can't find these packages: "
        for pkg_not_found in sorted(not_found):
            msg = msg + pkg_not_found + " "
        logging.error(msg)
        return None

    if missing_deps:
        msg = "Can't resolve these dependencies: "
        for missing in sorted(missing_deps):
            msg = msg + missing + " "
        logging.error(msg)
        return None

    metalink = download_queue_to_metalink(download_queue)

    return metalink


""" From here comes modified code from pm2ml
    pm2ml is Copyright (C) 2012-2013 Xyne
    More info: http://xyne.archlinux.ca/projects/pm2ml """


def download_queue_to_metalink(download_queue):
    """ Converts a download_queue object to a metalink """
    metalink = Metalink()

    for database, sigs in download_queue.dbs:
        metalink.add_db(database, sigs)

    for pkg, urls, sigs in download_queue.sync_pkgs:
        metalink.add_sync_pkg(pkg, urls, sigs)

    return metalink


class Metalink(object):
    """ Metalink class """

    def __init__(self):
        self.doc = minidom.getDOMImplementation().createDocument(None, "metalink", None)
        self.doc.documentElement.setAttribute(
            'xmlns', "urn:ietf:params:xml:ns:metalink")
        self.files = self.doc.documentElement

    # def __del__(self):
    #    self.doc.unlink()

    def __str__(self):
        """ Get a string representation of a metalink """
        return re.sub(
            r'(?<=>)\n\s*([^\s<].*?)\s*\n\s*',
            r'\1',
            self.doc.toprettyxml(indent=' ')
        )

    def add_urls(self, element, urls):
        """Add URL elements to the given element."""
        for url in urls:
            url_tag = self.doc.createElement('url')
            element.appendChild(url_tag)
            url_val = self.doc.createTextNode(url)
            url_tag.appendChild(url_val)

    def add_sync_pkg(self, pkg, urls, sigs=False):
        """Add a sync db package."""
        file_ = self.doc.createElement("file")
        file_.setAttribute("name", pkg.filename)
        self.files.appendChild(file_)
        for tag, db_attr, attrs in (
                ('identity', 'name', ()),
                ('size', 'size', ()),
                ('version', 'version', ()),
                ('description', 'desc', ()),
                ('hash', 'sha256sum', (('type', 'sha256'),)),
                ('hash', 'md5sum', (('type', 'md5'),))):
            tag = self.doc.createElement(tag)
            file_.appendChild(tag)
            val = self.doc.createTextNode(str(getattr(pkg, db_attr)))
            tag.appendChild(val)
            for key, val in attrs:
                tag.setAttribute(key, val)
        urls = list(urls)
        self.add_urls(file_, urls)
        if sigs:
            self.add_file(pkg.filename + '.sig', (u + '.sig' for u in urls))

    def add_file(self, name, urls):
        """Add a signature file."""
        file_ = self.doc.createElement("file")
        file_.setAttribute("name", name)
        self.files.appendChild(file_)
        self.add_urls(file_, urls)

    def add_db(self, db, sigs=False):
        """Add a sync db."""
        file_ = self.doc.createElement("file")
        name = db.name + '.db'
        file_.setAttribute("name", name)
        self.files.appendChild(file_)
        urls = list(os.path.join(url, db.name + '.db') for url in db.servers)
        self.add_urls(file_, urls)
        if sigs:
            self.add_file(name + '.sig', (u + '.sig' for u in urls))


class PkgSet(object):
    """ Represents a set of packages """

    def __init__(self, pkgs=None):
        """ Init our internal self.pkgs dict with all given packages in pkgs """

        self.pkgs = dict()
        if pkgs:
            for pkg in pkgs:
                self.pkgs[pkg.name] = pkg

    def __repr__(self):
        return 'PkgSet({0})'.format(repr(self.pkgs))

    def add(self, pkg):
        self.pkgs[pkg.name] = pkg

    def __and__(self, other):
        new = PkgSet(set(self.pkgs.values()) & set(other.pkgs.values()))
        return new

    def __iand__(self, other):
        self.pkgs = self.__and__(other).pkgs
        return self

    def __or__(self, other):
        copy = PkgSet(list(self.pkgs.values()))
        return copy.__ior__(other)

    def __ior__(self, other):
        self.pkgs.update(other.pkgs)
        return self

    def __contains__(self, pkg):
        return pkg.name in self.pkgs

    def __iter__(self):
        for v in self.pkgs.values():
            yield v

    def __len__(self):
        return len(self.pkgs)


class DownloadQueue(object):
    """ Represents a download queue """

    def __init__(self):
        self.dbs = list()
        self.sync_pkgs = list()

    def __bool__(self):
        return bool(self.dbs or self.sync_pkgs)

    def __nonzero__(self):
        return self.dbs or self.sync_pkgs

    def add_db(self, db, sigs=False):
        self.dbs.append((db, sigs))

    def add_sync_pkg(self, pkg, urls, sigs=False):
        self.sync_pkgs.append((pkg, urls, sigs))


def parse_args(args):
    parser = argparse.ArgumentParser()

    parser.add_argument('pkgs', nargs='*', default=[], metavar='<pkgname>',
                        help='Packages or groups to download.')
    parser.add_argument('--all-deps', action='store_true', dest='alldeps',
                        help='Include all dependencies even if they are already installed.')
    parser.add_argument('-c', '--conf', metavar='<path>', default='/etc/pacman.conf', dest='conf',
                        help='Use a different pacman.conf file.')
    parser.add_argument('--noconfirm', action='store_true', dest='noconfirm',
                        help='Suppress user prompts.')
    parser.add_argument('-d', '--nodeps', action='store_true', dest='nodeps',
                        help='Skip dependencies.')
    parser.add_argument('--needed', action='store_true', dest='needed',
                        help='Skip packages if they already exist in the cache.')
    help_msg = '''Include signature files for repos with optional and required SigLevels.
        Pass this flag twice to attempt to download signature for all databases and packages.'''
    parser.add_argument('-s', '--sigs', action='count', default=0, dest='sigs',
                        help=help_msg)
    parser.add_argument('-y', '--databases', '--refresh', action='store_true', dest='db',
                        help='Download databases.')

    return parser.parse_args(args)


def build_download_queue(alpm, args=None):
    """ Function to build a download queue.
        Needs a pkgname in args """

    pargs = parse_args(args)

    '''
    try:
        conf_file = pargs.conf
        alpm = pac.Pac(conf_path=conf_file, callback_queue=None)
    except Exception as ex:
        logging.error("Can't initialize pyalpm: %s", ex)
        return None, None, None
    '''

    handle = alpm.get_handle()
    conf = alpm.get_config()

    requested = set(pargs.pkgs)
    other = PkgSet()
    missing_deps = list()
    found = set()

    one_repo_groups = ['cinnamon', 'mate', 'mate-extra']
    antdb = [db for db in handle.get_syncdbs() if 'antergos' == db.name]
    antdb = antdb[0]
    one_repo_groups = [antdb.read_grp(one_repo_group)
                       for one_repo_group in one_repo_groups]
    one_repo_groups[0] = ['None', []]
    one_repo_pkgs = {pkg for one_repo_group in one_repo_groups
                     for pkg in one_repo_group[1] if one_repo_group}

    # foreign_names = set()
    # not_found = set()

    for pkg in requested:
        other_grp = PkgSet()
        for db in handle.get_syncdbs():
            if pkg in one_repo_pkgs and 'antergos' != db.name:
                # pkg should be sourced from the antergos repo only.
                db = antdb

            syncpkg = db.get_pkg(pkg)

            if syncpkg:
                other.add(syncpkg)
                break
            else:
                syncgrp = db.read_grp(pkg)
                if syncgrp:
                    found.add(pkg)
                    other_grp |= PkgSet(syncgrp[1])
                    break
        else:
            other |= other_grp

    # foreign_names = requested - set(x.name for x in other)

    # Resolve dependencies.
    if other and not pargs.nodeps:
        queue = deque(other)
        local_cache = handle.get_localdb().pkgcache
        syncdbs = handle.get_syncdbs()
        seen = set(queue)
        while queue:
            pkg = queue.popleft()
            for dep in pkg.depends:
                if pyalpm.find_satisfier(local_cache, dep) is None or pargs.alldeps:
                    for db in syncdbs:
                        prov = pyalpm.find_satisfier(db.pkgcache, dep)
                        if prov is not None:
                            other.add(prov)
                            if prov.name not in seen:
                                seen.add(prov.name)
                                queue.append(prov)
                            break
                    else:
                        missing_deps.append(dep)

    found |= set(other.pkgs)
    not_found = requested - found
    if pargs.needed:
        other = PkgSet(list(check_cache(conf, other)))

    download_queue = DownloadQueue()

    if pargs.db:
        for db in handle.get_syncdbs():
            try:
                siglevel = conf[db.name]['SigLevel'].split()[0]
            except KeyError:
                siglevel = None
            download_sig = needs_sig(siglevel, pargs.sigs, 'Database')
            download_queue.add_db(db, download_sig)

    for pkg in other:
        try:
            siglevel = conf[pkg.db.name]['SigLevel'].split()[0]
        except KeyError:
            siglevel = None
        download_sig = needs_sig(siglevel, pargs.sigs, 'Package')
        urls = set(os.path.join(url, pkg.filename) for url in pkg.db.servers)
        # Limit to MAX_URLS url
        while len(urls) > MAX_URLS:
            urls.pop()
        download_queue.add_sync_pkg(pkg, urls, download_sig)

    return download_queue, not_found, missing_deps


def get_checksum(path, typ):
    """ Returns checksum of a file """
    new_hash = hashlib.new(typ)
    block_size = new_hash.block_size
    try:
        with open(path, 'rb') as f:
            buf = f.read(block_size)
            while buf:
                new_hash.update(buf)
                buf = f.read(block_size)
        return new_hash.hexdigest()
    except FileNotFoundError:
        return -1
    except IOError as io_error:
        logging.error(io_error)


def check_cache(conf, pkgs):
    """ Checks package checksum in cache """
    for pkg in pkgs:
        for cache in conf.options['CacheDir']:
            fpath = os.path.join(cache, pkg.filename)
            for checksum in ('sha256', 'md5'):
                real_checksum = get_checksum(fpath, checksum)
                correct_checksum = getattr(pkg, checksum + 'sum')
                if real_checksum is None or real_checksum != correct_checksum:
                    yield pkg
                    break
            else:
                continue
            break


def needs_sig(siglevel, insistence, prefix):
    """ Determines if a signature should be downloaded.
        The siglevel is the pacman.conf SigLevel for the given repo.
        The insistence is an integer. Anything below 1 will return false,
        anything above 1 will return true, and 1 will check if the
        siglevel is required or optional.
        The prefix is either "Database" or "Package". """

    if insistence > 1:
        return True
    elif insistence == 1 and siglevel:
        for sl_type in ('Required', 'Optional'):
            if siglevel == sl_type or siglevel == prefix + sl_type:
                return True
    return False


def test():
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

    import gc
    import pprint
    import cnchi.pacman.pac as pac

    try:
        pacman = pac.Pac(
            conf_path="/etc/pacman.conf",
            callback_queue=None)

        for index in range(1, 10000):
            print("Creating metalink...")
            meta4 = create(
                alpm=pacman,
                package_name="gnome",
                pacman_conf_file="/etc/pacman.conf")
            print(get_info(meta4))
            meta4 = None
            objects = gc.collect()
            print("Unreachable objects: ", objects)
            print("Remaining garbage: ", pprint.pprint(gc.garbage))

        pacman.release()
        del pacman
    except Exception as ex:
        template = "Can't initialize pyalpm. An exception of type {0} occured. Arguments:\n{1!r}"
        message = template.format(type(ex).__name__, ex.args)
        logging.error(message)


''' Test case '''
if __name__ == '__main__':
    test()
