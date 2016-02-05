"""
    Peasauce - interactive disassembler
    Copyright (C) 2012-2016 Richard Tew
    Licensed using the MIT license.
"""

from .. import constants
from . import z80file


class System(object):
    endian_id = constants.ENDIAN_LITTLE

    def get_processor_id(self):
        return constants.PROCESSOR_Z80

    def identify_input_file(self, input_file, file_info, data_types, f_offset=0, f_length=None):
        matches = []
        for handler in (z80file,):
            match = handler.identify_input_file(input_file, file_info, data_types, f_offset, f_length)
            if match.platform_id != constants.PLATFORM_UNKNOWN:
                matches.append(match)
        return matches

    def load_input_file(self, input_file, file_info, data_types, f_offset=0, f_length=None):
        return z80file.load_input_file(input_file, file_info, data_types, f_offset, f_length)

    def load_project_data(self, f):
        return z80file.load_project_data(f)

    def save_project_data(self, f, data):
        z80file.save_project_data(f, data)

    def print_summary(self, file_info):
        z80file.print_summary(file_info)

    def has_segment_headers(self):
        return False

    def get_segment_header(self, file_info, segment_id):
        return "this section header should never be seen"

    def get_data_instruction_string(self, is_bss_segment, with_file_data):
        if is_bss_segment:
            return "DS"
        return "DC"

