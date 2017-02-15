"""
    Peasauce - interactive disassembler
    Copyright (C) 2012-2017 Richard Tew
    Licensed using the MIT license.
"""

from .. import constants
from . import romfile


class System(object):
    endian_id = constants.ENDIAN_LITTLE

    def get_processor_id(self):
        return constants.PROCESSOR_65c816

    def identify_input_file(self, input_file, file_info, data_types, f_offset=0, f_length=None):
        matches = []
        for handler in (romfile,):
            match = handler.identify_input_file(input_file, file_info, data_types, f_offset, f_length)
            if match.platform_id != constants.PLATFORM_UNKNOWN:
                matches.append(match)
        return matches

    def load_input_file(self, input_file, file_info, data_types, f_offset=0, f_length=None):
        return romfile.load_input_file(input_file, file_info, data_types, f_offset, f_length)

    def load_project_data(self, f):
        return romfile.load_project_data(f)

    def save_project_data(self, f, data):
        romfile.save_project_data(f, data)

    def print_summary(self, file_info):
        romfile.print_summary(file_info)

    def has_segment_headers(self):
        return False

    def get_segment_header(self, file_info, segment_id):
        return "this section header should never be seen"

    def get_data_instruction_string(self, data_size, is_bss_segment, with_file_data):
        suffix_by_size = {
            constants.DATA_TYPE_DATA08: "B",
            constants.DATA_TYPE_DATA16: "W",
            constants.DATA_TYPE_DATA32: "L",
        }
        suffix = "."+ suffix_by_size[data_size]
        if is_bss_segment:
            return "DS"+ suffix
        return "DC"+ suffix

