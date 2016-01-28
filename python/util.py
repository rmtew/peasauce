"""
    Peasauce - interactive disassembler
    Copyright (C) 2012-2016 Richard Tew
    Licensed using the MIT license.
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

def str_to_int(s):
    """ Takes a string provided through user input, which may be hexadecimal or an integer, and
        converts it to the actual corresponding integer.  """
    s = s.strip().lower()
    if s.startswith("$"):
        return int(s[1:], 16)
    elif s.startswith("0x"):
        return int(s[2:], 16)
    else:
        return int(s)
 