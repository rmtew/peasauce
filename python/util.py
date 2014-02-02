"""
    Peasauce - interactive disassembler
    Copyright (C) 2012, 2013, 2014 Richard Tew
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
