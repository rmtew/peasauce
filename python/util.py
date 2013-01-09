"""
    Peasauce - interactive disassembler
    Copyright (C) 2012, 2013 Richard Tew

    This program is free software: you can redistribute it and/or modify
    it under the terms of the GNU General Public License as published by
    the Free Software Foundation, either version 3 of the License, or
    (at your option) any later version.

    This program is distributed in the hope that it will be useful,
    but WITHOUT ANY WARRANTY; without even the implied warranty of
    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
    GNU General Public License for more details.

    You should have received a copy of the GNU General Public License
    along with this program.  If not, see <http://www.gnu.org/licenses/>.
"""

import hashlib
import os


def calculate_file_checksum(input_file):
    input_file.seek(0, os.SEEK_SET)
    hasher = hashlib.md5()
    data = input_file.read(256 * 1024)
    while len(data) > 0:
        hasher.update(data)
        data = input_file.read(256 * 1024)
    return hasher.digest()
