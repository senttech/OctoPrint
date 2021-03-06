#!/bin/env python2
from __future__ import absolute_import, division, print_function

__author__ = "Gina Haeussge <osd@foosel.net>"
__license__ = 'GNU Affero General Public License http://www.gnu.org/licenses/agpl.html'
__copyright__ = "Copyright (C) 2014 The OctoPrint Project - Released under terms of the AGPLv3 License"


import errno
import sys

def _log_call(*lines):
	_log(lines, prefix=">", stream="call")


def _log_stdout(*lines):
	_log(lines, prefix=" ", stream="stdout")


def _log_stderr(*lines):
	_log(lines, prefix=" ", stream="stderr")


def _log(lines, prefix=None, stream=None):
	output_stream = sys.stdout
	if stream == "stderr":
		output_stream = sys.stderr

	for line in lines:
		print(u"{} {}".format(prefix, _to_unicode(line.rstrip(), errors="replace")), file=output_stream)


def _to_unicode(s_or_u, encoding="utf-8", errors="strict"):
	"""Make sure ``s_or_u`` is a unicode string."""
	if isinstance(s_or_u, str):
		return s_or_u.decode(encoding, errors=errors)
	else:
		return s_or_u


def _execute(command, **kwargs):
	import sarge

	if isinstance(command, (list, tuple)):
		joined_command = " ".join(command)
	else:
		joined_command = command
	_log_call(joined_command)

	kwargs.update(dict(async=True, stdout=sarge.Capture(), stderr=sarge.Capture()))

	try:
		p = sarge.run(command, **kwargs)
		p.wait_events()
	except Exception as e:
		import traceback
		exception_lines = traceback.format_exc()
		error = "Error while trying to run command {}: {}\n{}".format(joined_command, str(e), exception_lines)
		return None, "", error

	all_stdout = []
	all_stderr = []
	try:
		while p.returncode is None:
			lines = p.stderr.readlines(timeout=0.5)
			if lines:
				_log_stderr(*lines)
				all_stderr += list(lines)

			lines = p.stdout.readlines(timeout=0.5)
			if lines:
				_log_stdout(*lines)
				all_stdout += list(lines)

			p.commands[0].poll()

	finally:
		p.close()

	lines = p.stderr.readlines()
	if lines:
		_log_stderr(*lines)
		all_stderr += lines

	lines = p.stdout.readlines()
	if lines:
		_log_stdout(*lines)
		all_stdout += lines

	return p.returncode, all_stdout, all_stderr


def _get_git_executables():
	GITS = ["git"]
	if sys.platform == "win32":
		GITS = ["git.cmd", "git.exe"]
	return GITS


def _git(args, cwd, verbose=False, git_executable=None):
	if git_executable is not None:
		commands = [git_executable]
	else:
		commands = _get_git_executables()

	for c in commands:
		try:
			return _execute([c] + args, cwd=cwd)
		except EnvironmentError:
			e = sys.exc_info()[1]
			if e.errno == errno.ENOENT:
				continue
			if verbose:
				print("unable to run %s" % args[0])
				print(e)
			return None, None, None
	else:
		if verbose:
			print("unable to find command, tried %s" % (commands,))
		return None, None, None


def _python(args, cwd, python_executable, sudo=False):
	command = [python_executable] + args
	if sudo:
		command = ["sudo"] + command
	try:
		return _execute(command, cwd=cwd)
	except:
		return None, None, None


def _to_error(*lines):
	return u"".join(map(lambda x: _to_unicode(x, errors="replace"), lines))


def _rescue_changes(git_executable, folder):
	print(">>> Running: git diff --shortstat")
	returncode, stdout, stderr = _git(["diff", "--shortstat"], folder, git_executable=git_executable)
	if returncode != 0:
		raise RuntimeError("Could not update, \"git diff\" failed with returncode %d: %s" % (returncode, _to_error(*stdout)))
	if stdout and "".join(stdout).strip():
		# we got changes in the working tree, maybe from the user, so we'll now rescue those into a patch
		import time
		import os
		timestamp = time.strftime("%Y%m%d%H%M")
		patch = os.path.join(folder, "%s-preupdate.patch" % timestamp)

		print(">>> Running: git diff and saving output to %s" % timestamp)
		returncode, stdout, stderr = _git(["diff"], folder, git_executable=git_executable)
		if returncode != 0:
			raise RuntimeError("Could not update, installation directory was dirty and state could not be persisted as a patch to %s" % patch)

		with open(patch, "wb") as f:
			for line in stdout:
				f.write(line)

		return True

	return False


def update_source(git_executable, folder, target, force=False, branch=None):
	if _rescue_changes(git_executable, folder):
		print(">>> Running: git reset --hard")
		returncode, stdout, stderr = _git(["reset", "--hard"], folder, git_executable=git_executable)
		if returncode != 0:
			raise RuntimeError("Could not update, \"git reset --hard\" failed with returncode %d: %s" % (returncode, _to_error(*stdout)))

		print(">>> Running: git clean -f -d -e *-preupdate.patch")
		returncode, stdout, stderr = _git(["clean", "-f", "-d", "-e", "*-preupdate.patch"], folder, git_executable=git_executable)
		if returncode != 0:
			raise RuntimeError("Could not update, \"git clean -f\" failed with returcode %d: %s" % (returncode, _to_error(*stdout)))

	print(">>> Running: git fetch")
	returncode, stdout, stderr = _git(["fetch"], folder, git_executable=git_executable)
	if returncode != 0:
		raise RuntimeError("Could not update, \"git fetch\" failed with returncode %d: %s" % (returncode, _to_error(*stdout)))
	print(stdout)

	if branch is not None and branch.strip() != "":
		print(">>> Running: git checkout {}".format(branch))
		returncode, stdout, stderr = _git(["checkout", branch], folder, git_executable=git_executable)
		if returncode != 0:
			raise RuntimeError("Could not update, \"git checkout\" failed with returncode %d: %s" % (returncode, _to_error(*stdout)))

	print(">>> Running: git pull")
	returncode, stdout, stderr = _git(["pull"], folder, git_executable=git_executable)
	if returncode != 0:
		raise RuntimeError("Could not update, \"git pull\" failed with returncode %d: %s" % (returncode, _to_error(*stdout)))

	if force:
		reset_command = ["reset", "--hard"]
		reset_command += [target]

		print(">>> Running: git %s" % " ".join(reset_command))
		returncode, stdout, stderr = _git(reset_command, folder, git_executable=git_executable)
		if returncode != 0:
			raise RuntimeError("Error while updating, \"git %s\" failed with returncode %d: %s" % (" ".join(reset_command), returncode, _to_error(*stdout)))


def install_source(python_executable, folder, user=False, sudo=False):
	print(">>> Running: python setup.py clean")
	returncode, stdout, stderr = _python(["setup.py", "clean"], folder, python_executable)
	if returncode != 0:
		print("\"python setup.py clean\" failed with returncode %d: %s" % (returncode, stdout))
		print("Continuing anyways")

	print(">>> Running: python setup.py install")
	args = ["setup.py", "install"]
	if user:
		args.append("--user")
	returncode, stdout, stderr = _python(args, folder, python_executable, sudo=sudo)
	if returncode != 0:
		raise RuntimeError("Could not update, \"python setup.py install\" failed with returncode %d: %s" % (returncode, _to_error(*stdout)))


def parse_arguments():
	import argparse

	boolean_trues = ["true", "yes", "1"]
	boolean_falses = ["false", "no", "0"]

	parser = argparse.ArgumentParser(prog="update-octoprint.py")

	parser.add_argument("--git", action="store", type=str, dest="git_executable",
	                    help="Specify git executable to use")
	parser.add_argument("--python", action="store", type=str, dest="python_executable",
	                    help="Specify python executable to use")
	parser.add_argument("--force", action="store", type=lambda x: x in boolean_trues,
	                    dest="force", default=False,
	                    help="Set this to true to force the update to only the specified version (nothing newer, nothing older)")
	parser.add_argument("--sudo", action="store_true", dest="sudo",
	                    help="Install with sudo")
	parser.add_argument("--user", action="store_true", dest="user",
	                    help="Install to the user site directory instead of the general site directory")
	parser.add_argument("--branch", action="store", type=str, dest="branch", default=None,
	                    help="Specify the branch to make sure is checked out")
	parser.add_argument("folder", type=str,
	                    help="Specify the base folder of the OctoPrint installation to update")
	parser.add_argument("target", type=str,
	                    help="Specify the commit or tag to which to update")

	args = parser.parse_args()

	return args

def main():
	args = parse_arguments()

	git_executable = None
	if args.git_executable:
		git_executable = args.git_executable

	python_executable = sys.executable
	if args.python_executable:
		python_executable = args.python_executable
		if python_executable.startswith('"'):
			python_executable = python_executable[1:]
		if python_executable.endswith('"'):
			python_executable = python_executable[:-1]

	print("Python executable: {!r}".format(python_executable))

	folder = args.folder

	import os
	if not os.access(folder, os.W_OK):
		raise RuntimeError("Could not update, base folder is not writable")

	update_source(git_executable, folder, args.target, force=args.force, branch=args.branch)
	install_source(python_executable, folder, user=args.user, sudo=args.sudo)

if __name__ == "__main__":
	main()
