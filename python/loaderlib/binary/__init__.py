"""
    Peasauce - interactive disassembler
    Copyright (C) 2012-2016 Richard Tew
    Licensed using the MIT license.
"""

import os


class System(object):
    big_endian = True
    
    arch_name = None

    def get_arch_name(self):
        return self.arch_name

    def set_arch_name(self, arch_name):
        self.arch_name = arch_name

    def load_input_file(self, input_file, file_info, data_types, f_offset=0, f_length=None):
        if file_info.loader_options is None or not file_info.loader_options.is_binary_file:
            return False
        self.set_arch_name(file_info.loader_options.dis_name)
        
        if f_length is None:
            file_offset2 = input_file.tell()
            input_file.seek(0, os.SEEK_END)
            f_length = input_file.tell()
            input_file.seek(file_offset2, os.SEEK_SET)

        file_size = f_length
        relocations = []
        symbols = []
        file_info.add_code_segment(0, file_size, file_size, relocations, symbols)
        return True

    def identify_input_file(self, input_file, file_info, data_types, f_offset=0, f_length=None):
        """ User selected files should not be identified as binary. """
        return None

    def load_project_data(self, f):
        return None

    def save_project_data(self, f, data):
        return None

    def print_summary(self, file_info):
        pass

    def has_segment_headers(self):
        return False

    def get_segment_header(self, file_info, segment_id):
        return "this section header should never be seen"

    def get_data_instruction_string(self, is_bss_segment, with_file_data):
        if is_bss_segment:
            return "DS"
        return "DC"
