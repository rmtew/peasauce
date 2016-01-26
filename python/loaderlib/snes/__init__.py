"""
    Peasauce - interactive disassembler
    Copyright (C) 2012-2016 Richard Tew
    Licensed using the MIT license.
"""

from . import romfile


class System(object):
    big_endian = False

    def get_arch_name(self):
        return "65c816"

    def identify_input_file(self, input_file, file_info, data_types, f_offset=0, f_length=None):
        return romfile.identify_input_file(input_file, file_info, data_types, f_offset, f_length)

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

    def get_data_instruction_string(self, is_bss_segment, with_file_data):
        if is_bss_segment:
            return "DS"
        return "DC"

