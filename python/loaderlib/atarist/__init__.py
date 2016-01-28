"""
    Peasauce - interactive disassembler
    Copyright (C) 2012-2016 Richard Tew
    Licensed using the MIT license.
"""

from . import prgfile


class System(object):
    big_endian = True

    def get_arch_name(self):
        return "m68k"

    def load_input_file(self, input_file, file_info, data_types, f_offset=0, f_length=None):
        return prgfile.load_input_file(input_file, file_info, data_types, f_offset, f_length)

    def identify_input_file(self, input_file, file_info, data_types, f_offset=0, f_length=None):
        return prgfile.identify_input_file(input_file, file_info, data_types, f_offset, f_length)

    def load_project_data(self, f):
        return prgfile.load_project_data(f)

    def save_project_data(self, f, data):
        return prgfile.save_project_data(f, data)

    def print_summary(self, file_info):
        prgfile.print_summary(file_info)

    def has_segment_headers(self):
        return False

    def get_segment_header(self, file_info, segment_id):
        return "this section header should never be seen"

    def get_data_instruction_string(self, is_bss_segment, with_file_data):
        if is_bss_segment:
            return "DS"
        return "DC"
