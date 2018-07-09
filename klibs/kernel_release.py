#
# Linux Kernel release script
#
# Copyright (C) 2018 Sathya Kuppuswamy
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.
#
# @Author  : Sathya Kupppuswamy(sathyaosid@gmail.com)
# @History :
#            @v0.0 - Basic class support
# @TODO    :
#
#

import os
import logging, logging.config
import pkg_resources
import datetime
import tarfile
import tempfile
import shutil
import glob
import errno

from jsonparser import JSONParser
from decorators import format_h1
from pyshell import GitShell, PyShell
from build_kernel import is_valid_kernel

class KernelRelease(object):

    def __init__(self, src=os.getcwd(), cfg=None, logger=None):

        self.logger = logger or logging.getLogger(__name__)
        self.src = os.path.abspath(src)
        self.base = None
        self.head = None
        self.local_branch = None
        self.remote = None
        self.remote_branch = None
        self.git = GitShell(wd=self.src, logger=logger)
        self.sh = PyShell(wd=self.src, logger=logger)
        self.valid_git = False
        self.cfg = None
        self.cfgobj = None
        self.schema = pkg_resources.resource_filename('klibs', 'schemas/release-schema.json')
        self.bundle_modes = ['branch', 'diff', 'commit_count']

        self.git.dryrun(True)
        self.sh.dryrun(True)

        if not is_valid_kernel(src, logger):
            return

        self.cfgobj = JSONParser(self.schema, cfg, extend_defaults=True, os_env=True, logger=logger)
        self.cfg = self.cfgobj.get_cfg()

        if self.git.valid():
            self.valid_git = True

    def auto_release(self):
        str_none =  lambda x: None if len(x) == 0 else x
        if self.cfg is None:
            self.logger.error("Invalid config file %s", self.cfg)
            return False

        def conv_remotelist(remote_list):
            new_list = []
            for remote in remote_list:
                self.logger.info(remote)
                new_list.append((remote["name"], remote["url"], remote["branch"], remote["path"]))

            return new_list if len(new_list) > 0 else None

        def conv_taglist(tag_list):
            new_list = []
            for tag in tag_list:
                new_list.append(tag["name"], tag["msg"])

            return new_list if len(new_list) > 0 else None

        def conv_copyformat(flist):
            if "*" in flist:
                return None
            else:
                return flist

        try:
            params = self.cfg["bundle"]
            uparams = self.cfg["bundle"]["upload-params"]
            if params["enable"]:
                if not self.valid_git:
                    Exception("Kernel is not a git repo. So bundle option is not supported")

                base = params["base"]["value"]
                if params["base"]["auto"]:
                    base = self.git.cmd('describe --abbrev=0 --tags')
                base = str_none(base)

                head = params["head"]["value"]
                if params["head"]["auto"]:
                    head = self.git.head_sha()
                head = str_none(head)

                bundle = self.generate_git_bundle(params["outname"], params["mode"], str_none(params["branch"]),
                                                  head, base, params["commit_count"])
                if bundle is not None:
                    self.git_upload(bundle, None, True, None, uparams["commit-msg"],
                                    conv_remotelist(uparams["remote-list"]),
                                    uparams["use-refs"], uparams["force-push"], uparams["clean-update"],
                                    uparams["timestamp-suffix"], uparams["suffix-sep"], uparams["timestamp-format"],
                                    conv_taglist(uparams))
                else:
                    Exception("Generate bundle failed")

        except Exception as e:
            self.logger.error(e)
        else:
            self.logger.info(format_h1("Successfully created git bundle", tab=2))


        try:
            params = self.cfg["quilt"]
            uparams = self.cfg["quilt"]["upload-params"]
            if params["enable"]:
                if not self.valid_git:
                    Exception("Kernel is not a git repo. So quilt option is not supported")

                base = params["base"]["value"]
                if params["base"]["auto"]:
                    base = self.git.cmd('describe --abbrev=0 --tags')
                base = str_none(base)

                head = params["head"]["value"]
                if params["head"]["auto"]:
                    head = self.git.head_sha()
                head = str_none(head)

                if head is None or base is None:
                    Exception("Invalid base/head %s/%s", base, head)

                quilt = self.generate_quilt(str_none(params["branch"]), base, head, params['outname'],
                                            str_none(params["sed-file"]), str_none(params["audit-script"]),
                                            params['series-comment'])

                if quilt is not None:
                    ret = self.git_upload(quilt, None, uparams["new-commit"], conv_copyformat(uparams["copy-formats"]),
                                          uparams["commit-msg"], conv_remotelist(uparams["remote-list"]),
                                          uparams["use-refs"], uparams["force-push"], uparams["clean-update"],
                                          uparams["timestamp-suffix"], uparams["suffix-sep"],
                                          uparams["timestamp-format"], conv_taglist(uparams["tag-list"]))
                    if ret is None:
                        Exception("Quilt upload failed")
                else:
                    Exception("Generate quilt failed")

        except Exception as e:
            self.logger.error(e)
        else:
            self.logger.info(format_h1("Successfully created quilt series", tab=2))

        try:
            params = self.cfg["tar"]
            uparams = self.cfg["tar"]["upload-params"]
            if params["enable"]:
                tarname = self.generate_tar_gz(params["outname"], params["branch"], params["skip_files"])

                if tarname is not None:
                    ret = self.git_upload(tarname, None, uparams["new-commit"],
                                          conv_copyformat(uparams["copy-formats"]), uparams["commit-msg"],
                                          conv_remotelist(uparams["remote-list"]),
                                          uparams["use-refs"], uparams["force-push"], uparams["clean-update"],
                                          uparams["timestamp-suffix"], uparams["suffix-sep"],
                                          uparams["timestamp-format"], conv_taglist(uparams["tag-list"]))
                    if ret is None:
                        Exception("tar upload failed")
                else:
                    Exception("Create tar file failed")

        except Exception as e:
            self.logger.error(e)
        else:
            self.logger.info(format_h1("Successfully created tar file", tab=2))

        try:
            params = self.cfg["upload-kernel"]
            uparams = self.cfg["upload-kernel"]["upload-params"]
            if params["enable"]:
                ret = self.git_upload(self.src, None, uparams["new-commit"], conv_copyformat(uparams["copy-formats"]),
                                      uparams["commit-msg"], conv_remotelist(uparams["remote-list"]),
                                      uparams["use-refs"], uparams["force-push"], uparams["clean-update"],
                                      uparams["timestamp-suffix"], uparams["suffix-sep"], uparams["timestamp-format"],
                                      conv_taglist(uparams["tag-list"]))
                if ret is None:
                    Exception("Upload kernel failed")

        except Exception as e:
            self.logger.error(e)
        else:
            self.logger.info(format_h1("Successfully Uploaded Linux kernel", tab=2))

        return True

    def git_upload(self, src, uploaddir=None, new_commit=False, copy_formats=None, commit_msg="Inital commit",
                   remote_list=None, use_refs=False, force_update=False, clean_update=False,
                   timestamp_suffix=False, suffix_sep='-', timestamp_format="%m%d%Y%H%M%S",
                   tag_list = None):
        """
        Upload the kernel or tar file or quilt series to a given remote_list.
        :param src: Source dir. Either kernel, quilt or tar file.
        :param uploaddir: Directory used for uploading the new changes. If none, then temp_dir will be used.
        :param new_commit: Create new commit and then upload (True|False).
        :param copy_formats: List of glob format of the files to be added to the commit.
        :param commit_msg: Commit Message
        :param remote_list: [(Remote Name, Remote URL, Remote branch, Remote dest dir)]
        :param use_refs: Use refs/for when pushing (True | False).
        :param force_update: Force update when pushing (True | False).
        :param clean_update: Remove existing content before adding and pushing your change (True | False).
        :param timestamp_suffix: Add time stamp suffix to remotebranch before pushing.
        :param suffix_sep: $remotebranch$suffix_sep$timestamp_siffix
        :param timestamp_format: "%m%d%Y%H%M%S"
        :param tag_list: [("name", "msg")], None if no tagging support needed. Use None for no message.
        :return:
        """

        # Check for data validity.
        repo_dir = src
        # Check if the source directory is valid.
        src = os.path.abspath(src)
        if not os.path.exists(src):
            self.logger.error("Source %s does not exit", src)
            return None

        # Check the validity of tags
        if tag_list is not None:
            if not isinstance(tag_list, list):
                self.logger.error("Invalid tag type")
                return None
            for tag in tag_list:
                if not isinstance(tag, tuple) or len(tag) != 2:
                    self.logger.error("Invalid tag %s", tag)
                    return None

        # Check for validity of copyformats
        if copy_formats is not None:
            if not isinstance(copy_formats, list):
                self.logger.error("Invalid copy format %s", copy_formats)
                return None

        # Create a valid out directory
        temp_dir = tempfile.mkdtemp()
        if uploaddir is not None:
            uploaddir = os.path.abspath(uploaddir)
            if os.path.exists(uploaddir):
                shutil.rmtree(uploaddir, ignore_errors=True)
            os.makedirs(uploaddir)
        else:
            uploaddir = temp_dir

        def copyanything(src, dst):
            try:
                shutil.copytree(src, dst)
            except OSError as exc:  # python >2.5
                if exc.errno == errno.ENOTDIR:
                    shutil.copy(src, dst)
                else:
                    raise

        def empty_folder(dirname):
            for root, dirs, files in os.walk(dirname):
                for f in files:
                    os.unlink(os.path.join(root, f))
                for d in dirs:
                    shutil.rmtree(os.path.join(root, d))

        def upload_tags(remote, tag_list):
            if tag_list is not None:
                for tag in tag_list:
                    # Push the tags if required
                    if tag[0] is not None:
                        if tag[1] is not None:
                            ret = git.cmd('tag', '-a', tag[0], '-m', tag[1])[0]
                        else:
                            ret = git.cmd('tag', tag[0])[0]
                        if ret != 0:
                            Exception("git tag %s failed" % (tag[0]))

                        if git.cmd('push', remote, tag[0])[0] != 0:
                            Exception("git push tag %s to %s failed" % (tag[0], remote))

        try:
            for remote in remote_list:
                self.logger.info(remote)
                empty_folder(uploaddir)
                repo_dir = src
                if new_commit:

                    git = GitShell(wd=uploaddir, init=True, remote_list=[(remote[0], remote[1])], fetch_all=True)

                    if git.cmd("checkout", remote[0] + '/' + remote[2])[0] != 0:
                        Exception("Git checkout remote:%s branch:%s failed", remote[1], remote[2])

                    # If clean update is given, remove the contents of current repo.
                    if clean_update and git.cmd('rm *')[0] != 0:
                        Exception("git rm -r *.patch failed")

                    dest_dir = os.path.join(uploaddir, remote[3]) if remote[3] is not None else uploaddir
                    if not os.path.exists(dest_dir):
                        os.makedirs(dest_dir)

                    if copy_formats is None:
                        copyanything(src, dest_dir)
                    elif os.path.isdir(src):
                        file_list = []
                        for format in copy_formats:
                            file_list += glob.glob(os.path.join(src, format))
                        for item in file_list:
                            shutil.copyfile(item,  os.path.join(dest_dir, os.path.basename(item)))

                    if git.cmd('add *')[0] != 0:
                        Exception("git add command failed")

                    if git.cmd('commit -s -m "' + commit_msg + '"')[0]:
                        Exception("git commit failed")

                    repo_dir = uploaddir

                git = GitShell(wd=repo_dir, init=True, remote_list=[(remote[0], remote[1])], fetch_all=True)

                rbranch = remote[2]

                if timestamp_suffix:
                    self.logger.info(format_h1("Upload timestamp branch", tab=2))
                    ts = datetime.datetime.utcnow().strftime(timestamp_format)
                    rbranch = rbranch + suffix_sep + ts

                if git.push('HEAD', remote[0], rbranch, force=force_update, use_refs=use_refs)[0] != 0:
                    Exception("git push to %s %s failed" % (remote[0], rbranch))

                upload_tags(remote[0], tag_list)

        except Exception as e:
            self.logger.error(e)
            shutil.rmtree(temp_dir)
            return None
        else:
            shutil.rmtree(temp_dir)
            return repo_dir

    def generate_quilt(self, local_branch=None, base=None, head=None,
                       patch_dir='quilt',
                       sed_file=None,
                       audit_script=None,
                       series_comment=''):
        """
        Generate the quilt series for the given kernel source.
        :param local_branch: Name of the kernel branch.
        :param base: First SHA ID.
        :param head: Head SHA ID.
        :param patch_dir: Output directory for storing the quilt series. If it exists, it will be removed.
        :param sed_file: Sed format list.
        :param audit_script: Audid script. It will be called with patch_dir as input. If it return non zero value
                             then this function will exit and return None.
        :param series_comment: Comments to add on top of series file.
        :return: Return patch_dir or None
        """


        set_val = lambda x, y: y if x is None else x

        self.logger.info(format_h1("Generating quilt series", tab=2))

        if not self.valid_git:
            self.logger.error("Invalid git repo %s", self.src)
            return None

        if sed_file is not None and not os.path.exists(sed_file):
            self.logger.error("sed pattern file %s does not exist", sed_file)
            return None

        if os.path.exists(os.path.abspath(patch_dir)):
            shutil.rmtree(patch_dir, ignore_errors=True)

        os.makedirs(patch_dir)

        local_branch = set_val(local_branch, self.git.current_branch())

        if self.git.cmd('checkout', local_branch)[0] != 0:
            self.logger.error("git checkout command failed in %s", self.src)
            return None

        try:

            series_file = os.path.join(patch_dir, 'series')

            # if base SHA is not given use TAIL as base SHA
            if base is None:
                base = self.git.base_sha()
                if base is None:
                    raise Exception("git log command failed")

            # if head SHA is not given use HEAD as head SHA
            if head is None:
                head = self.git.head_sha()
                if head is None:
                    raise Exception("git fetch head SHA failed")

            # Create the list of patches 'git format-patch -C -M base..head -o patch_dir'
            ret, out, err = self.git.cmd('format-patch', '-C', '-M', base.strip() + '..' + head.strip(), '-o',
                                         patch_dir)
            if ret != 0:
                raise Exception("git format patch command failed out: %s error: %s" % (out, err))

            # Format the patches using sed
            if sed_file is not None:
                ret, out, err = self.sh.cmd('sed -i -f%s %s/*.patch' % (sed_file, patch_dir), shell=True)
                if ret != 0:
                    raise Exception("sed command failed out: %s error: %s" % (out, err))

            # Make sure the patches passes audit check.
            if audit_script is not None:
                ret, out, err = self.sh.cmd(audit_script, patch_dir, shell=True)
                if ret != 0:
                    raise Exception("Audid check failed out: %s error: %s" % (out, err))

            # Write series file comments.
            with open(series_file, 'w+') as fobj:
                fobj.write(series_comment)

            # Write the list of series file.
            ret, out, err = self.sh.cmd('ls -1 *.patch >> series', wd=patch_dir, shell=True)
            if ret != 0:
                raise Exception("Writing to patch series file failed. Out:%s Error: %s" % (out, err))

        except Exception as e:
            if os.path.exists(patch_dir):
                shutil.rmtree(patch_dir)
            self.logger.error(e)
            return None
        else:
            return patch_dir


    def generate_git_bundle(self, outfile, mode='branch', local_branch=None, head=None, base=None,
                            commit_count=0):
        """
        Create git bundle for the given kernel source. Git bundle can created in three different modes.
            1. branch - Given git branch will be bundled.
            2. commit_count - Given number of commits will be bundled.
            3. diff - Range of commits will be bundled.
        :param outfile: Name of the git bundle.
        :param mode: branch, commit_count, and diff mode.
        :param local_branch: Name of the git branch.
        :param head: Head SHA ID or Tag
        :param base: First SHA ID or Tag.
        :param commit_count: Number of commits.
        :return: Filename on success, None otherwise.
        """

        set_val = lambda x, y: y if x is None else x

        # Check the validity of bundle mode.
        if mode not in self.bundle_modes:
            self.logger.error("Invalid bundle mode %s", mode)
            return None

        # Check the validity of outfile.
        if outfile is None or outfile == "":
            self.logger.error("Invalid bundle name %s", outfile)
            return None

        # Check whether kernel source is a valid git repo.
        if not self.valid_git:
            self.logger.error("Invalid git repo %s", self.src)
            return None

        # If local branch is none, then current branch will be used.
        local_branch = set_val(local_branch, self.git.current_branch())

        # If the bundle file is already present, delete it.
        outfile = os.path.abspath(outfile)
        if os.path.exists(outfile):
            shutil.rmtree(outfile)

        self.logger.info(format_h1("Generating git bundle", tab=2))

        try:
            if self.git.cmd('checkout', local_branch)[0] != 0:
                raise Exception("Git checkout command failed in %s" % self.src)

            if mode == 'branch':
                if self.git.cmd('bundle', 'create',  outfile, local_branch)[0] != 0:
                    raise Exception("Git bundle create command failed")

            if mode == 'commit_count':
                if self.git.cmd('bundle', 'create', outfile, '-' + str(commit_count), local_branch)[0] != 0:
                    raise Exception("Git bundle create command failed")

            if mode == 'diff' and head is not None and base is not None:
                if self.git.cmd('bundle', 'create', outfile, str(base) + '..' + str(head))[0] != 0:
                    raise Exception("Git bundle create command failed")
        except Exception as e:
            self.logger.error(e)
            return None
        else:
            return outfile

    def generate_tar_gz(self, outfile, branch=None, skip_files=['.git']):
        """
        Create kernel tar file.
        :param outfile: Name of the tar file.
        :param branch: Git branch.
        :param skip_files: List of files needs to be skipped.
        :return: Filename on success, None otherwise.
        """
        self.logger.info(format_h1("Generating tar gz", tab=2))

        # Check if outfile is valid.
        if outfile is None or outfile == "":
            self.logger.error("Invalid output file %s name\n", outfile)
            return None

        # If branch option is used, then kernel soruce should be a valid git repo.
        if branch is not None and self.valid_git:
            if self.git.cmd('checkout', branch)[0] != 0:
                self.logger.error("Git checkout branch %s failed in %s", branch, self.src)
                return None

        # Select the files you want to add into the tar file.
        def valid_file(tarinfo):
            for entry in skip_files:
                if entry in tarinfo.name:
                    return None

            return tarinfo

        out = tarfile.open(outfile, mode='w:gz')
        out.add(self.src, recursive=True, filter=valid_file)

        return outfile