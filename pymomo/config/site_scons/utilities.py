#utilities.py

from SCons.Script import *
from SCons.Environment import Environment
import os
import fnmatch
import json as json
import sys
import os.path
import pic12
import StringIO

sys.path.append(os.path.join(os.path.dirname(__file__), '..'))

from pymomo.utilities import build
from pymomo.utilities.paths import MomoPaths
from pymomo.mib.config12 import MIB12Processor

def find_files(dirname, pattern):
	"""
	Recursively find all files matching pattern under path dirname
	"""

	matches = []
	for root, dirnames, filenames in os.walk(dirname, followlinks=True):
		print dirnames, filenames
		for filename in fnmatch.filter(filenames, pattern):
			matches.append(os.path.join(root,filename))

	return matches

def build_includes(includes):
	if isinstance(includes, basestring):
		includes = [includes]

	return ['-I"%s"' % x for x in includes]

def build_libdirs(libdirs):
	if isinstance(libdirs, basestring):
		libdirs = [libdirs]

	return ['-L"%s"' % x for x in libdirs]

def build_staticlibs(libs, chip):
	if isinstance(libs, basestring):
		libs = [libs]

	processed = []
	for lib in libs:

		#Allow specifying absolute libraries that don't get architectures
		#appended
		if lib[0] == '#':
			processed.append(lib[1:])
		else:
			#Append chip type and suffix
			proclib = "%s_%s" % (lib, chip.arch_name())
			processed.append(proclib)

	return ['-l%s' % x for x in processed]

def process_libaries(libs, chip):
	"""
	Newer libary processing function used in ARM build system to
	create -L and -l statements for linking executables to static
	libraries.

	libs should a list of 2 tuples specifying a path relative to momo_modules/shared
	and the name of the library with an optional '#' to indicate that the libary should
	not have an architecture name appended to it.  The library name should not start
	with 'lib' (that will be prepended automatically)
	"""

	basepath = os.path.join(MomoPaths().modules, 'shared')

	processed_names = []
	processed_folders = []
	for proj, lib in libs:
		#Allow specifying absolute libraries that don't get architectures
		#appended
		if lib[0] == '#':
			lib = lib[1:]
		else:
			#Append chip type and suffix
			lib = "%s_%s" % (lib, chip.arch_name())
		
		path = os.path.join(basepath, proj, 'build', 'output')

		processed_names.append(lib)
		processed_folders.append(path)

	return processed_folders, processed_names

def process_path(path):
	"""
	Allow specifying paths relative to the MOMOPATH root rather than absolute or relative to
	a given module's root directory.
	"""

	if path[0] == '!':
		path = path[1:]

		basepaths = MomoPaths()
		return os.path.join(basepaths.base, path)

	return path

def join_path(path):
	"""
	If given a string, return it, otherwise combine a list into a string
	using os.path.join
	"""

	if isinstance(path, basestring):
		return path
	
	return os.path.join(*path)

def build_defines(defines):
	return ['-D%s=%s' % (x,str(y)) for x,y in defines.iteritems()]

def get_family(fam, modulefile=None):
	return build.ChipFamily(fam, modulefile=modulefile)

class BufferedSpawn:
	def __init__(self, env, logfile):
		self.env = env
		self.logfile = logfile

		self.stderr = StringIO.StringIO()
		self.stdout = StringIO.StringIO()

	def spawn(self, sh, escape, cmd, args, env):
		cmd_string = " ".join(args)

		print cmd_string
		self.stdout.write(cmd_string)
		
		try:
			retval = self.env['PSPAWN'](sh, escape, cmd, args, env, sys.stdout, sys.stderr)
		except OSError, x:
			if x.errno != 10:
				raise x

			print 'OSError Ignored on command: %s' % cmd_string

		return retval
