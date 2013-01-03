"""
    Peasauce - interactive disassembler
    Copyright (C) 2012  Richard Tew

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

"""
This file is supposed to abstract the actions a user might perform, so that any
interface, whether a user facing GUI or separate script, might use it without
reproducing the same logic.
"""

import types
import os

import disassembly
import disassembly_persistence


ERRMSG_NOT_SUPPORTED_EXECUTABLE_FILE_FORMAT = "The file does not appear to be a supported executable file format."
ERRMSG_NO_IDENTIFIABLE_DESTINATION = "Nowhere to go."
ERRMSG_INPUT_FILE_CHECKSUM_MISMATCH = "ERRMSG_INPUT_FILE_CHECKSUM_MISMATCH"
ERRMSG_INPUT_FILE_SIZE_DIFFERS = "ERRMSG_INPUT_FILE_SIZE_DIFFERS"

ERRMSG_BUG_UNKNOWN_ADDRESS = "Unable to determine address at current line, this is a bug."
ERRMSG_BUG_NO_OPERAND_SELECTION_MECHANISM = "Too many valid operands, this is a bug."
ERRMSG_BUG_UNABLE_TO_GOTO_LINE = "Unable to go to the given line, this is a bug."

ERRMSG_TODO_BAD_STATE_FUNCTIONALITY = "TODO: Work out you can do this in the current program state."


class ClientAPI(object):
    def __init__(self, owner):
        self.owner = owner

    def request_load_file(self):
        """
        Returns the selected file name or None if no file was selected.
        .. should really return a file handle, whether local or remote.
        """
        raise NotImplementedError

    def request_code_save_file(self):
        """ Returns a file handle if the user selected a location?
            Returns None if the user canceled the process. """
        raise NotImplementedError

    def request_new_project_option_values(self, new_options):
        """ Returns the user modified options. """
        raise NotImplementedError

    def validate_new_project_option_values(self, new_options):
        """ Returns a message on error, or None on success. """
        raise NotImplementedError

    def request_save_project_option_values(self, save_options):
        """ Returns the user modified options if save chosen.
            Returns None if cancel chosen. """
        raise NotImplementedError

    def edit_label_name(self, label_name):
        """ Returns an error message on failure. """
        raise NotImplementedError

    def validate_label_name(self, label_name):
        """ Returns a message on error, or None on success. """
        raise NotImplementedError

    def reset_state(self):
        raise NotImplementedError

    def request_address(self):
        raise NotImplementedError


class EditorState(object):
    """
    TODO: How to integrate prompting for needed information mid-load?
    - GUI showing dialog with fields.
    - Command line prompting.

    List of required values with default values.
    Maybe list of possible options.
    """

    STATE_INITIAL = 0
    STATE_LOADING = 1
    STATE_LOADED = 2

    def __init__(self, client):
        self.client = client
        self.reset_state()

    def in_initial_state(self): return self.state_id == EditorState.STATE_INITIAL
    def in_loading_state(self): return self.state_id == EditorState.STATE_LOADING
    def in_loaded_state(self): return self.state_id == EditorState.STATE_LOADED

    def is_project_file(self, input_file):
        return disassembly_persistence.check_is_project_file(input_file)

    def reset_state(self):
        self.state_id = EditorState.STATE_INITIAL
        self.disassembly_data = None
        self.line_number = 0
        self.address_stack = []
        # TODO: Clear out related data.
        self.client.reset_state()

    def get_address(self):
        return disassembly.get_address_for_line_number(self.disassembly_data, self.line_number)

    def get_line_number(self):
        return self.line_number

    def _set_line_number(self, line_number):
        self.line_number = line_number

    def get_line_count(self):
        if self.disassembly_data is None:
            return 0
        return disassembly.get_line_count(self.disassembly_data)

    def get_file_line(self, row, column):
        if self.disassembly_data is None:
            return ""
        return disassembly.get_file_line(self.disassembly_data, row, column)

    def load_file(self, load_call_proxy=None):
        if load_call_proxy is None:
            def load_call_proxy(f, *args, **kwargs):
                return f(*args, **kwargs)

        # TODO: Request a file name to load.
        load_file = self.client.request_load_file()

        self.state_id = EditorState.STATE_LOADING
        is_saved_project = disassembly_persistence.check_is_project_file(load_file)

        if is_saved_project:
            result = load_call_proxy(disassembly.load_project_file, load_file)
        else:
            new_options = disassembly.get_new_project_options(self.disassembly_data)
            # TODO: Prompt for new project option values.
            new_options = self.client.request_new_project_option_values(new_options)
            # TODO: Validate all values are provided correctly.
            errmsg = self.client.validate_new_project_option_values(new_options)
            if errmsg is not None:
                self.reset_state()
                return errmsg
            result = load_call_proxy(disassembly.load_file, load_file, new_options)

        self.state_id = EditorState.STATE_LOADED
        self.disassembly_data, line_count = result

        if line_count == 0:
            self.reset_state()
            return ERRMSG_NOT_SUPPORTED_EXECUTABLE_FILE_FORMAT

        is_saved_project = disassembly_persistence.check_is_project_file(self.client.get_load_file())
        if is_saved_project:
            # User may have optionally chosen to not save the input file, as part of the project file.
            if not disassembly.is_segment_data_cached(self.disassembly_data):
                errmsg = None
                input_data_file = self.client.request_load_file()
                input_data_file.seek(0, os.SEEK_END)
                if input_data_file.tell() != self.disassembly_data.file_size:
                    errmsg = ERRMSG_INPUT_FILE_SIZE_DIFFERS
                elif disassembly.calculate_file_checksum(input_data_file) != self.disassembly_data.file_checksum:
                    errmsg = ERRMSG_INPUT_FILE_CHECKSUM_MISMATCH
                if type(errmsg) in types.StringTypes:
                    self.reset_state()
                    return errmsg
                disassembly.cache_segment_data(self.disassembly_data, input_data_file)

        entrypoint_address = disassembly.get_entrypoint_address(self.disassembly_data)
        line_number = disassembly.get_line_number_for_address(self.disassembly_data, entrypoint_address)
        self._set_line_number(line_number)
        return result

    def push_address(self):
        if self.state_id != EditorState.STATE_LOADED:
            return ERRMSG_TODO_BAD_STATE_FUNCTIONALITY

        current_address = disassembly.get_address_for_line_number(self.disassembly_data, self.line_number)
        if current_address is None:
            return ERRMSG_BUG_UNKNOWN_ADDRESS

        operand_addresses = disassembly.get_referenced_symbol_addresses_for_line_number(self.disassembly_data, self.line_number)
        if len(operand_addresses) == 1:
            next_line_number = disassembly.get_line_number_for_address(self.disassembly_data, operand_addresses[0])
            if next_line_number is None:
                return ERRMSG_BUG_UNABLE_TO_GOTO_LINE

            self._set_line_number(next_line_number)
            self.address_stack.append(current_address)
        elif len(operand_addresses) == 2:
            return ERRMSG_BUG_NO_OPERAND_SELECTION_MECHANISM

        return ERRMSG_NO_IDENTIFIABLE_DESTINATION

    def pop_address(self):
        if self.state_id != EditorState.STATE_LOADED:
            return ERRMSG_TODO_BAD_STATE_FUNCTIONALITY

        if not len(self.address_stack):
            return ERRMSG_NO_IDENTIFIABLE_DESTINATION

        address = self.address_stack.pop()
        # It is expected that if you can have pushed the address, there was a line number for it.
        line_number = disassembly.get_line_number_for_address(self.disassembly_data, address)
        self._set_line_number(line_number)

    def set_label_name(self):
        if self.state_id != EditorState.STATE_LOADED:
            return ERRMSG_TODO_BAD_STATE_FUNCTIONALITY

        current_address = disassembly.get_address_for_line_number(self.disassembly_data, self.line_number)
        symbol_name = disassembly.get_symbol_for_address(self.disassembly_data, current_address)
        # TODO: Prompt user to edit the current label, or add a new one.
        new_symbol_name = self.client.edit_label_name(symbol_name)
        if new_symbol_name is not None and new_symbol_name != symbol_name:
            # TODO: Validate that the label is valid syntactically for the given platform.
            errmsg = self.client.validate_label_name(new_symbol_name)
            if errmsg is not None:
                return errmsg
            disassembly.set_symbol_for_address(self.disassembly_data, current_address, new_symbol_name)

    def set_datatype_code(self):
        if self.state_id != EditorState.STATE_LOADED:
            return ERRMSG_TODO_BAD_STATE_FUNCTIONALITY

        address = disassembly.get_address_for_line_number(self.disassembly_data, self.line_number)
        if address is None:
            return ERRMSG_BUG_UNKNOWN_ADDRESS
        self.set_data_type(address, disassembly.DATA_TYPE_CODE)

    def set_datatype_32bit(self):
        if self.state_id != EditorState.STATE_LOADED:
            return ERRMSG_TODO_BAD_STATE_FUNCTIONALITY

        address = disassembly.get_address_for_line_number(self.disassembly_data, self.line_number)
        if address is None:
            return ERRMSG_BUG_UNKNOWN_ADDRESS
        self.set_data_type(address, disassembly.DATA_TYPE_LONGWORD)

    def set_datatype_16bit(self):
        if self.state_id != EditorState.STATE_LOADED:
            return ERRMSG_TODO_BAD_STATE_FUNCTIONALITY

        address = disassembly.get_address_for_line_number(self.disassembly_data, self.line_number)
        if address is None:
            return ERRMSG_BUG_UNKNOWN_ADDRESS
        self.set_data_type(address, disassembly.DATA_TYPE_WORD)

    def set_datatype_8bit(self):
        if self.state_id != EditorState.STATE_LOADED:
            return ERRMSG_TODO_BAD_STATE_FUNCTIONALITY

        address = disassembly.get_address_for_line_number(self.disassembly_data, self.line_number)
        if address is None:
            return ERRMSG_BUG_UNKNOWN_ADDRESS
        self.set_data_type(address, disassembly.DATA_TYPE_BYTE)

    def set_datatype_ascii(self):
        if self.state_id != EditorState.STATE_LOADED:
            return ERRMSG_TODO_BAD_STATE_FUNCTIONALITY

        address = disassembly.get_address_for_line_number(self.disassembly_data, self.line_number)
        if address is None:
            return ERRMSG_BUG_UNKNOWN_ADDRESS
        self.set_data_type(address, disassembly.DATA_TYPE_ASCII)

    def save_project(self):
        if self.state_id != EditorState.STATE_LOADED:
            return ERRMSG_TODO_BAD_STATE_FUNCTIONALITY

        save_options = disassembly.get_save_project_options(self.disassembly_data)
        # Install higher-level defined and used option attributes.
        save_options.cache_input_file = disassembly.get_project_save_count(self.disassembly_data) == 0 or disassembly.is_project_inputfile_cached(self.disassembly_data)
        # TODO: Prompt user if they want to save the source file.
        save_options = self.client.request_save_project_option_values(save_options)
        # User chose to cancel the save process.
        if save_options is None:
            return
        if save_options.cache_input_file:
            save_options.input_file = self.client.get_load_file()

        with open(save_options.save_file_path, "wb") as f:
            disassembly.save_project_file(f, self.disassembly_data, save_options)

    def export_source_code(self):
        if self.state_id != EditorState.STATE_LOADED:
            return ERRMSG_TODO_BAD_STATE_FUNCTIONALITY

        line_count = disassembly.get_line_count(self.disassembly_data)

        # TODO: Prompt for save file name.
        save_file = self.client.request_code_save_file()
        if save_file is not None:
            for i in xrange(line_count):
                label_text = disassembly.get_file_line(self.disassembly_data, i, disassembly.LI_LABEL)
                instruction_text = disassembly.get_file_line(self.disassembly_data, i, disassembly.LI_INSTRUCTION)
                operands_text = disassembly.get_file_line(self.disassembly_data, i, disassembly.LI_OPERANDS)
                if label_text:
                    save_file.write(label_text)
                if instruction_text or operands_text:
                    save_file.write("\t")
                    save_file.write(instruction_text)
                if operands_text:
                    save_file.write("\t")
                    save_file.write(operands_text)
                save_file.write("\n")
            save_file.close()

    def goto_address(self):
        address = disassembly.get_address_for_line_number(self.disassembly_data, self.line_number)
        # Current line does not have an address.
        if address is None:
            address = 0
        new_address = self.client.request_address(address)
        if new_address is None:
            return
        if type(new_address) in types.StringType:
            new_address = disassembly.get_address_for_symbol(self.disassembly_data, new_address)
        return new_address
