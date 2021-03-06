"""
TOOO: DOCSTRING
"""
"""
Copyright 2016 Baris Ungun, Anqi Fu

This file is part of CONRAD.

CONRAD is free software: you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.

CONRAD is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
GNU General Public License for more details.

You should have received a copy of the GNU General Public License
along with CONRAD.  If not, see <http://www.gnu.org/licenses/>.
"""
from conrad.io.io import CaseIO

def parsearg(list_, prefix, type_, default):
	for arg in map(str, list_):
		if arg.startswith(prefix):
			return type_(arg.lstrip(prefix))
	return default

def safe_load_yaml(filename):
	f = open(filename)
	contents = yaml.safe_load_all(f)

	# process generator returned by safe_load_all
	dictionary = {}
	for c in contents:
		if isinstance(c, dict):
			dictionary.update(c)
	f.close()

	return dictionary