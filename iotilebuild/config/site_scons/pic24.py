# This file is adapted from python code released by WellDone International
# under the terms of the LGPLv3.  WellDone International's contact information is
# info@welldone.org
# http://welldone.org
#
# Modifications to this file from the original created at WellDone International 
# are copyright Arch Systems Inc.

from SCons.Script import *
from SCons.Environment import Environment
import sys
import os.path
from utilities import BufferedSpawn
from cfileparser import ParsedCFile
from dependencies import build_dependencies
from iotilecore.sim.simulator import Simulator

all_envs = []

def build_module(module_name, chip, postprocess_hex):
	"""
	Configure Scons to build a hex module for the pic24 chip listed in the argument.
	"""

	dirs = chip.build_dirs()
	output_name = '%s.elf' % (chip.output_name(),)
	output_hex = '%s.hex' % (chip.output_name(),)
	postproc_hex = '%s_postprocessed.hex' % (chip.output_name(),)

	VariantDir(dirs['build'], os.path.join('firmware', 'src'), duplicate=0)

	env = Environment(tools=['xc16_compiler', 'xc16_assembler', 'xc16_linker', 'ldf_compiler'], ENV = os.environ)
	env.AppendENVPath('PATH','../../tools/scripts')
	env['ARCH'] = chip
	env['OUTPUT'] = output_name
	env['OUTPUT_PATH'] = os.path.join(dirs['build'], output_name)
	env['BUILD_DIR'] = dirs['build']
	env['CPPPATH'] = chip.includes()

	dependencies = chip.property('depends', {})
	dep_nodes = build_dependencies(dependencies, env)
	env.Depends(env['OUTPUT_PATH'], dep_nodes)

	## Add in all include directories, library directories and libraries from dependencies
	dep_incs = reduce(lambda x,y:x+y, [x.include_directories() for x in env['DEPENDENCIES']], [])
	lib_dirs = reduce(lambda x,y:x+y, [x.library_directories() for x in env['DEPENDENCIES']], [])
	libs = reduce(lambda x,y:x+y, [x.libraries() for x in env['DEPENDENCIES']], [])
	env['CPPPATH'] += dep_incs
	#env['LIBPATH'] += lib_dirs
	#env['LIBS'] += libs

	Export('env')

	SConscript(os.path.join(dirs['build'], 'SConscript'))

	elffile = os.path.join(dirs['build'], output_name)
	hexfile = os.path.join(dirs['build'], output_hex)

	env.Command(hexfile, elffile, 'xc16-bin2hex %s' % elffile)

	if postprocess_hex is not None:
		finalhex = os.path.join(dirs['build'], postproc_hex)

		env.Command(finalhex, hexfile, action=env.Action(postprocess_hex, 'Postprocessing hex file'))
	else:
		finalhex = hexfile

	output = env.InstallAs(os.path.join(dirs['output'], output_hex), finalhex)
	return [output]

def build_library(name, chip):
	"""
	Build the pic24 shared library for the given chip returning an absolute
	path to the product.  
	Parameters are:
	- name: name of the shared library
	- chip: a ChipSettings object for the target chip.
	"""

	dirs = chip.build_dirs()

	builddir = dirs['build']
	outdir = dirs['output']

	output_name = '%s.a' % (chip.output_name(),)

	VariantDir(builddir, 'src', duplicate=0)

	library_env = Environment(tools=['xc16_compiler', 'xc16_assembler', 'xc16_linker', 'ldf_compiler'], ENV = os.environ)
	library_env.AppendENVPath('PATH','../../tools/scripts')
	library_env['ARCH'] = chip
	library_env['OUTPUT'] = output_name
	library_env['OUTPUT_PATH'] = os.path.join(builddir, output_name)
	library_env['BUILD_DIR'] = builddir
	library_env['CPPPATH'] = chip.includes()
	library_env['LIBPATH'] = []
	library_env['LIBS'] = []
	
	dependencies = chip.property('depends', {})
	dep_nodes = build_dependencies(dependencies, library_env)
	library_env.Depends(library_env['OUTPUT_PATH'], dep_nodes)

	## Add in all include directories, library directories and libraries from dependencies
	dep_incs = reduce(lambda x,y:x+y, [x.include_directories() for x in library_env['DEPENDENCIES']], [])
	lib_dirs = reduce(lambda x,y:x+y, [x.library_directories() for x in library_env['DEPENDENCIES']], [])
	libs = reduce(lambda x,y:x+y, [x.libraries() for x in library_env['DEPENDENCIES']], [])

	library_env['CPPPATH'] += dep_incs
	library_env['LIBPATH'] += lib_dirs
	library_env['LIBS'] += libs

	SConscript(os.path.join(builddir, 'SConscript'), exports='library_env')

	libfile = library_env.InstallAs(os.path.join(outdir, output_name), os.path.join(builddir, output_name))
	return os.path.join(outdir, output_name)

def build_moduletest(test, arch):
	"""
	Given a path to the source files, build a unit test including the unity test harness targeting
	the given architecture.
	"""

	rawlog = '#' + test.get_path('rawlog', arch)
	outlog = '#' + test.get_path('log', arch)
	statusfile = '#' + test.get_path('status', arch)
	elffile = '#' + test.get_path('elf', arch)

	build_dirs = test.build_dirs(arch)
	objdir = build_dirs['objects']

	arch = arch.retarget(add=['test'])

	unit_env = Environment(tools=['xc16_compiler', 'xc16_assembler', 'xc16_linker'], ENV = os.environ)
	tester_env = Environment(tools=['xc16_compiler' ], ENV = os.environ)
	unit_env['ARCH'] = arch
	tester_env['ARCH'] = arch
	tester_env['CPPPATH'] = arch.includes()


	unit_env['OUTPUT'] = '%s.elf' % test.name
	unit_env['BUILD_DIR'] = objdir
	unit_env['OUTPUT_PATH'] = os.path.join(objdir, unit_env['OUTPUT'])

	unit_env['CPPPATH'] = arch.includes()

	dependencies = arch.property('depends', {})
	dep_nodes = build_dependencies(dependencies, unit_env)
	dep_incs = reduce(lambda x,y:x+y, [x.include_directories() for x in unit_env['DEPENDENCIES']], [])
	tester_env['CPPPATH'] += dep_incs
	unit_env['CPPPATH'] += dep_incs

	objs = []
	for src in test.files:
		name,ext = os.path.splitext(os.path.basename(src))
		target = os.path.join(objdir, name + '.o')

		if src == test.files[0]:
			objs.append(tester_env.xc16_gcc('#' + target, src))
		else:
			objs.append(unit_env.xc16_gcc('#' + target, src))

	#Generate main.c programmatically to run the test
	main_src = '#' + os.path.join(objdir, 'main.c')
	main_target = '#' + os.path.join(objdir, 'main.o')
	unit_env.Command(main_src, test.files[0], action=unit_env.Action(build_moduletest_main, "Creating test runner"))
	objs.append(unit_env.xc16_gcc(main_target, main_src))

	#Link the test, run it and build a status file
	unit_env.xc16_ld(elffile, objs)
	unit_env.Command(outlog, elffile, action=unit_env.Action(r'momo-picunit %s "%s" "%s"' % (arch.property('simulator_model'), elffile[1:], outlog[1:]), "Running unit test")) 
	unit_env.Command(statusfile, outlog, action=unit_env.Action(process_log, 'Processing log file'))

	return statusfile

mainscript = """
int main(void)
{
	U1MODEbits.UARTEN = 1; //Enable the uart
	U1STAbits.UTXEN = 1; //Enable transmission

	UnityBegin("test/TESTNAME");

	if (TEST_PROTECT())
	{
TESTCALLS
	}

	UnityEnd();

	return 0;
}
"""

def build_moduletest_main(target, source, env):
	"""
	Given a module test file, parse it using pycparser, extract all function definitions
	that begin with test_ and then build a main.c file at target containing a test runner
	that calls those functions.
	"""

	name = os.path.basename(str(source[0]))

	srcpath = str(source[0])
	parsed = ParsedCFile(srcpath, env['ARCH'])
	funcs = parsed.defined_functions(criterion=lambda x: x.startswith('test_'))

	testcalls = ""
	testprotos = ""
	for func in funcs:
		testprotos += 'void %s(void);\n' % func
		testcalls += "\t\tRUN_TEST(%s);\n" % func

	with open(str(target[0]), "w")as f:
		f.write('#include "unity.h"\n')
		f.write('#include <xc.h>\n\n')
		f.write(testprotos)

		script = mainscript.replace('TESTNAME', name).replace('TESTCALLS', testcalls)
		f.write(script)

def process_log(target, source, env):
	import platform

	#file ends with OK followed by a newline for successful tests, but newlines are two characters on Windows
	if platform.system() == 'Windows':
		seeknum = -4
	else:
		seeknum = -3

	with open(str(source[0]), "r") as log:
		log.seek(seeknum, os.SEEK_END)
		status = log.read(2)
	
	with open(str(target[0]), "w") as statfile:
		msg = "FAILED"
		if status == "OK":
			msg = 'PASSED'

		statfile.write(msg)

