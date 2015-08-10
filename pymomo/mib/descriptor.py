#descriptor.py
#Define a Domain Specific Language for specifying MIB endpoints

from pyparsing import Word, Regex, nums, hexnums, Literal, Optional, Group, oneOf, dblQuotedString
from handler import MIBHandler
import sys
import os.path
from pymomo.utilities.paths import MomoPaths
from pymomo.exceptions import *
import block

#DSL for mib definitions
#Format:
#feature <i>
#[j:] _symbol(n [ints], yes|no)
#[j+1:] _symbol2(n [ints], yes|no)
#The file should contain a list of statements beginning with a feature definition
#and followed by 1 or more command definitions.  There may be up to 128 feature definitions
#each or which may have up to 128 command definitions.  Whitespace is ignored.  Lines starting
#with # are considered comments and ignored.
symbol = Regex('[_a-zA-Z][_a-zA-Z0-9]*')
filename = Regex('[_a-zA-Z][_a-zA-Z0-9]*\.mib')
strval = Regex('"[_a-zA-Z0-9. ]+"')
number = Regex('((0x[a-fA-F0-9]+)|[0-9]+)').setParseAction(lambda s,l,t: [int(t[0], 0)]) | symbol
ints = number('num_ints') + Optional(Literal('ints') | Literal('int'))
has_buffer = (Literal('yes') | Literal('no')).setParseAction(lambda s,l,t: [t[0] == 'yes'])
comma = Literal(',').suppress()
quote = Literal('"').suppress()

left = Literal('(').suppress()
right = Literal(')').suppress()
colon = Literal(':').suppress()
leftB = Literal('[').suppress()
rightB = Literal(']').suppress()
comment = Literal('#')

valid_type = oneOf('uint8_t uint16_t uint32_t int8_t int16_t int32_t char')

assignment_def = symbol("variable") + "=" + (number('value') | strval('value')) + ';'
cmd_def = number("cmd_number") + colon + symbol("symbol") + left + ints + comma + has_buffer('has_buffer') + right + ";"
include = Literal("#include") + quote + filename("filename") + quote
interface_def = Literal('interface') + number('interface') + ';'

reqconfig = Literal('required').suppress() + Literal('config').suppress() + valid_type('type') + symbol('configvar') + Optional(leftB + number('length') + rightB) + ';'
optconfig = Literal('optional').suppress() + Literal('config').suppress() + valid_type('type') + symbol('configvar') + Optional(leftB + number('length') + rightB) + "=" + (number('value') | dblQuotedString('value')) + ';'

statement = include | cmd_def | comment | assignment_def | interface_def | reqconfig | optconfig

#Known Variable Type Lengths
type_lengths = {'uint8_t': 1, 'char': 1, 'int8_t': 1, 'uint16_t': 2, 'int16_t':2, 'uint32_t': 4, 'int32_t': 4} 

class MIBDescriptor:
	"""
	Class that parses a .mib file which contains a DSL specifying the valid MIB endpoints
	in a MIB12 module and can output an asm file containing the proper MIB command map
	for that architecture.
	"""

	def __init__(self, filename, include_dirs=[]):
		self.variables = {}
		self.commands = {}
		self.interfaces = []
		self.configs = {}

		self.include_dirs = include_dirs + [MomoPaths().config]

		self._parse_file(filename)
		self._validate_information()
	def _parse_file(self, filename):
		with open(filename, "r") as f:
			for l in f:
				line = l.lstrip().rstrip()

				if line == "":
					continue

				self._parse_line(line)

	def _find_include_file(self, filename):
		for d in self.include_dirs:
			path = os.path.join(d, filename)
			if os.path.isfile(path):
				return path

		raise ArgumentError("Could not find included mib file", filename=filename, search_dirs=self.include_dirs)

	def _add_cmd(self, num, symbol, num_ints, has_buffer):
		handler = MIBHandler.Create(symbol=symbol, ints=num_ints, has_buffer=has_buffer)
		
		if num in self.commands:
			raise DataError("Attempted to add the same command number twice", number=num, old_handler=self.commands[num], new_handler=handler)

		self.commands[num] = handler

	def _parse_cmd(self, match):
		symbol = match['symbol']

		num = self._parse_number(match['cmd_number'])
		if num < 0 or num >= 2**16:
			raise DataError("Invalid command identifier, must be a number between 0 and 2^16 - 1.", command_id=num)

		has_buffer = match['has_buffer']
		num_ints = match['num_ints']

		self._add_cmd(num, symbol, num_ints=num_ints, has_buffer=has_buffer)

	def _parse_include(self, match):
		filename = match['filename']

		path = self._find_include_file(filename)
		self._parse_file(path)

	def _parse_number(self, number):
		if isinstance(number, int):
			return number

		if number in self.variables:
			return self.variables[number]

		raise DataError("Reference to undefined variable %s" % number)

	def _parse_interface(self, match):
		interface = match['interface']
		if interface in self.interfaces:
			raise DataError("Attempted to add the same interface twice", interface=interface)

		self.interfaces.append(interface)

	def _parse_assignment(self, match):
		var = match['variable']
		val = match['value']
		if isinstance(val, basestring) and val[0] == '"':
			val = val[1:-1]
		else:
			val = self._parse_number(match['value'])

		self.variables[var] = val

	def _parse_required_configvar(self, match):
		if 'length' in match:
			array = True
			quantity = match['length']
		else:
			array = False
			quantity = 1

		if 'value' in match:
			default_value = match['value']
			required = False
		else:
			default_value = None
			required = True

		varname = match['configvar']
		vartype = match['type']

		varsize = quantity*type_lengths[vartype]

		config = {'name': varname, 'type': vartype, 'total_size': varsize, 'array': array, 'count': quantity, 'required': required}

		if varname in self.configs:
			raise DataError("Attempted to add the same config variable twice", variable_name=varname, defined_variables=self.configs.keys())
		
		self.configs[varname] = config


	def _parse_line(self, line):
		matched = statement.parseString(line)

		if 'symbol' in matched:
			self._parse_cmd(matched)
		elif 'filename' in matched:
			self._parse_include(matched)
		elif 'variable' in matched:
			self._parse_assignment(matched)
		elif 'interface' in matched:
			self._parse_interface(matched)
		elif 'configvar' in matched:
			self._parse_required_configvar(matched)

	def _validate_information(self):
		"""
		Validate that all information has been filled in
		"""

		needed_variables = ["ModuleName", "ModuleVersion", "APIVersion"]

		for var in needed_variables:
			if var not in self.variables:
				raise DataError("Needed variable was not defined in mib file.", variable=var)

		#Make sure ModuleName is <= 6 characters
		if len(self.variables["ModuleName"]) > 6:
			raise DataError("ModuleName too long, must be 6 or fewer characters.", module_name=self.variables["ModuleName"])

		if not isinstance(self.variables["ModuleVersion"], basestring):
			raise ValueError("ModuleVersion ('%s') must be a string of the form X.Y.Z" % str(self.variables['ModuleVersion']))

		if not isinstance(self.variables["APIVersion"], basestring):
			raise ValueError("APIVersion ('%s') must be a string of the form X.Y" % str(self.variables['APIVersion']))


		self.variables['ModuleVersion'] = self._convert_module_version(self.variables["ModuleVersion"])
		self.variables['APIVersion'] = self._convert_api_version(self.variables["APIVersion"])
		self.variables["ModuleName"] = self.variables["ModuleName"].ljust(6)

	def _convert_version(self, version_string):
		vals = [int(x) for x in version_string.split(".")]

		invalid = [x for x in vals if x < 0 or x > 255]
		if len(invalid) > 0:
			raise DataError("Invalid version number larger than 1 byte", number=invalid[0], version_string=version_string)

		return vals

	def _convert_module_version(self, version):
		vals = self._convert_version(version)
		if len(vals) != 3:
			raise DataError("Invalid Module Version, should be X.Y.Z", version_string=version)

		return vals

	def _convert_api_version(self, version):
		vals = self._convert_version(version)
		if len(vals) != 2:
			raise DataError("Invalid API Version, should be X.Y", version_string=version)

		return vals		

	def get_block(self):
		"""
		Create a MIB Block based on the information in this descriptor
		"""

		mib = block.MIBBlock()

		for key, val in self.commands.iteritems():
			mib.add_command(key, val)

		for interface in self.interfaces:
			mib.add_interface(interface)

		mib.set_api_version(*self.variables["APIVersion"])
		mib.set_module_version(*self.variables["ModuleVersion"])
		mib.set_name(self.variables["ModuleName"])

		return mib
