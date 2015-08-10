import os.path
from pymomo.mib.descriptor import MIBDescriptor
import unittest
from nose.tools import *
from pymomo.exceptions import *
import hashlib

import pyparsing

def _load_mib(filename):
	path = os.path.join(os.path.dirname(__file__), filename)
	return MIBDescriptor(path, include_dirs=[os.path.dirname(__file__)])

@raises(pyparsing.ParseException)
def test_syntax_error():
	_load_mib("syntax_error.mib")

@raises(DataError)
def test_incomplete():
	desc = _load_mib("incomplete.mib")

def test_complete():
	desc = _load_mib("complete.mib")

	api = desc.variables['APIVersion']
	mod = desc.variables['ModuleVersion']

	assert api[0] == 1
	assert api[1] == 2

	assert mod[0] == 1
	assert mod[1] == 2
	assert mod[2] == 3

	assert len(desc.variables['ModuleName']) == 6
	assert desc.variables['ModuleName'] == 'test12'

def test_extend_name():
	desc = _load_mib("short_name.mib")

	assert len(desc.variables['ModuleName']) == 6
	assert desc.variables['ModuleName'] == 'test  '

def test_hexvalues():
	desc = _load_mib("hexvalues.mib")

	assert desc.variables['RandomVariable'] == 0x100
	assert 0x12ab in desc.commands
	assert 64000 in desc.commands

def test_parse_configs():
	desc = _load_mib("configvariables.mib")

	assert 'testvar1' in desc.configs
	assert 'testvar2' in desc.configs
	assert 'testvar3' in desc.configs
	assert 'testvar4' in desc.configs

	testvar1 = desc.configs['testvar1']
	assert testvar1['required'] == True
	assert testvar1['type'] == 'uint8_t'
	assert testvar1['total_size'] == 1
	assert testvar1['array'] == False


@raises(pyparsing.ParseException)
def test_parse_badconfig1():
	desc = _load_mib("badconfig1.mib")


@raises(pyparsing.ParseException)
def test_parse_badconfig2():
	desc = _load_mib("badconfig2.mib")

@raises(DataError)
def test_long_name():
	desc = _load_mib("long_name.mib")

@raises(ArgumentError)
def test_include_nonexistent():
	desc = _load_mib("invalid_include.mib")

def test_good_include():
	desc = _load_mib("valid_include.mib")

	api = desc.variables['APIVersion']
	mod = desc.variables['ModuleVersion']

	assert api[0] == 1
	assert api[1] == 2

	assert mod[0] == 1
	assert mod[1] == 2
	assert mod[2] == 3

	assert len(desc.variables['ModuleName']) == 6
	assert desc.variables['ModuleName'] == 'test12'

def test_block_generation():
	desc = _load_mib("complete.mib")

	block = desc.get_block()

	assert block.api_version[0] == 1
	assert block.api_version[1] == 2

	assert block.module_version[0] == 1
	assert block.module_version[1] == 2
	assert block.module_version[2] == 3

	assert len(block.name) == 6
	assert block.name == 'test12'

	str_rep = str(block)
	print str_rep
