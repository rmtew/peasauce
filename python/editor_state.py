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

"""
This file is supposed to abstract the actions a user might perform, so that any
interface, whether a user facing GUI or separate script, might use it without
reproducing the same logic.
"""

import types
import os

import disassembly
import disassembly_persistence
import loaderlib
import util


TEXT_LOAD_INPUT_FILE_TITLE = "Input file not included"
TEXT_LOAD_INPUT_FILE_BODY = "The save-file cannot be loaded unless you locate and provide the input file which was originally disassembled.  Do you wish to proceed?"

TEXT_SELECT_REFERRING_ADDRESS_SHORT = "Go to which referring address?"
TEXT_SELECT_REFERRING_ADDRESS_LONG = "Select on the following and press the enter key, or click on the button, to jump to the given referring address."
TEXT_GO_TO_SELECTION = "Go to selection"

ERRMSG_NOT_SUPPORTED_EXECUTABLE_FILE_FORMAT = "The file does not appear to be a supported executable file format."
ERRMSG_NO_IDENTIFIABLE_DESTINATION = "Nowhere to go."
ERRMSG_INPUT_FILE_CHECKSUM_MISMATCH = "File does not match (checksum differs)"
ERRMSG_INPUT_FILE_SIZE_DIFFERS = "File does not match (size differs)"
ERRMSG_INVALID_LABEL_NAME = "Invalid label name"

ERRMSG_BUG_UNKNOWN_ADDRESS = "Unable to determine address at current line, this is a bug."
ERRMSG_BUG_NO_OPERAND_SELECTION_MECHANISM = "Too many valid operands, this is a bug."
ERRMSG_BUG_UNABLE_TO_GOTO_LINE = "Unable to go to the given line, this is a bug."

ERRMSG_TODO_BAD_STATE_FUNCTIONALITY = "TODO: Work out you can do this in the current program state."

import re

RE_LABEL = re.compile("([a-zA-Z_]+[a-zA-Z0-9_\.]*)$")


class ClientAPI(object):
    def __init__(self, owner):
        self.owner = owner

    def request_load_file(self):
        """
        Returns the selected file, file name or None if no file was selected.
        Returns an error message if failed.
        .. should really return a file handle, whether local or remote. ???
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

    def request_label_name(self, label_name):
        """ Returns an error message on failure. """
        raise NotImplementedError

    def reset_state(self):
        raise NotImplementedError

    def request_address(self, default_address):
        """ Prompts the user for an address (or symbol name), using the given default as the initial editable value.
            Returns None if cancel chosen.
            Returns the address as a number, if applicable.
            Returns a symbol name as a string, if applicable. """
        raise NotImplementedError

    def request_address_selection(self, title_text, body_text, button_text, address_rows, row_keys):
        """ Prompts the user with a list of addresses (strings), which they can select one of.
            Returns None if cancel chosen.
            Returns the selected address otherwise. """
        raise NotImplementedError

    def request_confirmation(self, title, text):
        """ Prompt the user to confirm a choice.
            Returns True if confirmed.
            Returns False if not confirmed. """
        raise NotImplementedError


class EditorState(object):
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

        # Clear out related data.
        self.client.reset_state()

    def _address_to_string(self, address):
        # TODO: Make it disassembly specific e.g. $address, 0xaddress
        return hex(address)

    def _convert_addresses_to_symbols_where_possible(self, addresses):
        for i, address in enumerate(addresses):
            symbol_name = disassembly.get_symbol_for_address(self.disassembly_data, address)
            if symbol_name is not None:
                addresses[i] = symbol_name
            else:
                addresses[i] = self._address_to_string(address)

    def get_data_type_for_address(self, address):
        data_type = disassembly.get_data_type_for_address(self.disassembly_data, address)
        if data_type == disassembly.DATA_TYPE_CODE:
            return "code"
        elif data_type == disassembly.DATA_TYPE_ASCII:
            return "ascii"
        elif data_type == disassembly.DATA_TYPE_BYTE:
            return "8bit"
        elif data_type == disassembly.DATA_TYPE_WORD:
            return "16bit"
        elif data_type == disassembly.DATA_TYPE_LONGWORD:
            return "32bit"

    def get_source_code_for_address(self, address):
        line_idx = disassembly.get_line_number_for_address(self.disassembly_data, address)
        return self.get_source_code_for_line_number(line_idx)

    def get_source_code_for_line_number(self, line_idx):
        code_string = disassembly.get_file_line(self.disassembly_data, line_idx, disassembly.LI_INSTRUCTION)
        operands_text = disassembly.get_file_line(self.disassembly_data, line_idx, disassembly.LI_OPERANDS)
        if len(operands_text):
            code_string += " "+ operands_text
        return code_string

    def get_row_for_line_number(self, line_idx):
        return [
            disassembly.get_file_line(self.disassembly_data, line_idx, disassembly.LI_OFFSET),
            disassembly.get_file_line(self.disassembly_data, line_idx, disassembly.LI_BYTES),
            disassembly.get_file_line(self.disassembly_data, line_idx, disassembly.LI_LABEL),
            disassembly.get_file_line(self.disassembly_data, line_idx, disassembly.LI_INSTRUCTION),
            disassembly.get_file_line(self.disassembly_data, line_idx, disassembly.LI_OPERANDS),
        ]

    def get_referring_addresses_for_address(self, address):
        return list(disassembly.get_referring_addresses(self.disassembly_data, address))

    def get_address(self):
        return disassembly.get_address_for_line_number(self.disassembly_data, self.line_number)

    def get_line_number_for_address(self, address):
        return disassembly.get_line_number_for_address(self.disassembly_data, address)

    def get_line_number(self):
        return self.line_number

    def set_line_number(self, line_number):
        if type(line_number) not in (int, long):
            raise ValueError("expected numeric type, got %s (%s)" % (line_number.__class__.__name__, line_number))
        self.line_number = line_number

    def get_line_count(self):
        if self.disassembly_data is None:
            return 0
        return disassembly.get_line_count(self.disassembly_data)

    def get_file_line(self, row, column):
        if self.disassembly_data is None:
            return ""
        return disassembly.get_file_line(self.disassembly_data, row, column)

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

            self.set_line_number(next_line_number)
            self.address_stack.append(current_address)
            return
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
        self.set_line_number(line_number)

    def goto_address(self):
        address = disassembly.get_address_for_line_number(self.disassembly_data, self.line_number)
        if address is None: # Current line does not have an address.
            address = 0
        result = self.client.request_address(address)
        if result is None: # Cancelled / aborted.
            return
        # Convert an entered symbol name to it's address.
        if type(result) in types.StringTypes:
            result = disassembly.get_address_for_symbol(self.disassembly_data, result)
            if result is None:
                return ERRMSG_NO_IDENTIFIABLE_DESTINATION
        line_number = disassembly.get_line_number_for_address(self.disassembly_data, result)
        self.set_line_number(line_number)

    def goto_referring_address(self):
        current_address = self.get_address()
        if current_address is None:
            return ERRMSG_NO_IDENTIFIABLE_DESTINATION

        addresses = list(disassembly.get_referring_addresses(self.disassembly_data, current_address))
        if not len(addresses):
            return ERRMSG_NO_IDENTIFIABLE_DESTINATION

        # Addresses appear in numerical order.
        addresses.sort()
        # Symbols appear in place of addresses where they exist.
        converted_addresses = addresses[:]
        self._convert_addresses_to_symbols_where_possible(converted_addresses)
        address_rows = []
        for i, address in enumerate(addresses):
            code_string = self.get_source_code_for_address(address)
            address_rows.append((self._address_to_string(address), converted_addresses[i], code_string))

        selected_address = self.client.request_address_selection(TEXT_SELECT_REFERRING_ADDRESS_SHORT, TEXT_SELECT_REFERRING_ADDRESS_LONG, TEXT_GO_TO_SELECTION, address_rows, addresses)
        if selected_address is None:
            return False

        next_line_number = disassembly.get_line_number_for_address(self.disassembly_data, selected_address)
        if next_line_number is None:
            return ERRMSG_BUG_UNABLE_TO_GOTO_LINE

        self.set_line_number(next_line_number)
        self.address_stack.append(current_address)
        return True

    def goto_previous_data_block(self):
        line_idx = self.get_line_number()
        new_line_idx = disassembly.get_next_data_line_number(self.disassembly_data, line_idx, -1)
        if new_line_idx is None:
            return ERRMSG_NO_IDENTIFIABLE_DESTINATION
        self.set_line_number(new_line_idx)

    def goto_next_data_block(self):
        line_idx = self.get_line_number()
        new_line_idx = disassembly.get_next_data_line_number(self.disassembly_data, line_idx, -1)
        if new_line_idx is None:
            return ERRMSG_NO_IDENTIFIABLE_DESTINATION
        self.set_line_number(new_line_idx)

    ## UNCERTAIN REFERENCES:

    def set_uncertain_reference_modification_func(self, callback):
        def callback_adaptor(data_type_from, data_type_to, address, length):
            if data_type_from == disassembly.DATA_TYPE_CODE:
                data_type_from = "CODE"
            else:
                data_type_from = "DATA"
            if data_type_to == disassembly.DATA_TYPE_CODE:
                data_type_to = "CODE"
            else:
                data_type_to = "DATA"
            return callback(data_type_from, data_type_to, address, length)
        disassembly.set_uncertain_reference_modification_func(self.disassembly_data, callback_adaptor)

    def get_uncertain_code_references(self):
        return disassembly.get_uncertain_code_references(self.disassembly_data)

    def get_uncertain_data_references(self):
        return disassembly.get_uncertain_data_references(self.disassembly_data)

    def get_uncertain_references_by_address(self, address):
        return disassembly.get_uncertain_references_by_address(self.disassembly_data, address)

    ## GENERAL:

    def set_symbol_insert_func(self, callback):
        disassembly.set_symbol_insert_func(self.disassembly_data, callback)

    def set_label_name(self):
        if self.state_id != EditorState.STATE_LOADED:
            return ERRMSG_TODO_BAD_STATE_FUNCTIONALITY

        current_address = disassembly.get_address_for_line_number(self.disassembly_data, self.line_number)
        symbol_name = disassembly.get_symbol_for_address(self.disassembly_data, current_address)
        # Prompt user to edit the current label, or add a new one.
        new_symbol_name = self.client.request_label_name(symbol_name)
        if new_symbol_name is not None and new_symbol_name != symbol_name:
            match = RE_LABEL.match(new_symbol_name)
            if match is None:
                return ERRMSG_INVALID_LABEL_NAME
            disassembly.set_symbol_for_address(self.disassembly_data, current_address, new_symbol_name)

    def set_datatype_code(self):
        if self.state_id != EditorState.STATE_LOADED:
            return ERRMSG_TODO_BAD_STATE_FUNCTIONALITY

        address = disassembly.get_address_for_line_number(self.disassembly_data, self.line_number)
        if address is None:
            return ERRMSG_BUG_UNKNOWN_ADDRESS
        self._set_data_type(address, disassembly.DATA_TYPE_CODE)

    def set_datatype_32bit(self):
        if self.state_id != EditorState.STATE_LOADED:
            return ERRMSG_TODO_BAD_STATE_FUNCTIONALITY

        address = disassembly.get_address_for_line_number(self.disassembly_data, self.line_number)
        if address is None:
            return ERRMSG_BUG_UNKNOWN_ADDRESS
        self._set_data_type(address, disassembly.DATA_TYPE_LONGWORD)

    def set_datatype_16bit(self):
        if self.state_id != EditorState.STATE_LOADED:
            return ERRMSG_TODO_BAD_STATE_FUNCTIONALITY

        address = disassembly.get_address_for_line_number(self.disassembly_data, self.line_number)
        if address is None:
            return ERRMSG_BUG_UNKNOWN_ADDRESS
        self._set_data_type(address, disassembly.DATA_TYPE_WORD)

    def set_datatype_8bit(self):
        if self.state_id != EditorState.STATE_LOADED:
            return ERRMSG_TODO_BAD_STATE_FUNCTIONALITY

        address = disassembly.get_address_for_line_number(self.disassembly_data, self.line_number)
        if address is None:
            return ERRMSG_BUG_UNKNOWN_ADDRESS
        self._set_data_type(address, disassembly.DATA_TYPE_BYTE)

    def set_datatype_ascii(self):
        if self.state_id != EditorState.STATE_LOADED:
            return ERRMSG_TODO_BAD_STATE_FUNCTIONALITY

        address = disassembly.get_address_for_line_number(self.disassembly_data, self.line_number)
        if address is None:
            return ERRMSG_BUG_UNKNOWN_ADDRESS
        self._set_data_type(address, disassembly.DATA_TYPE_ASCII)

    def _set_data_type(self, address, data_type):
        disassembly.set_data_type_at_address(self.disassembly_data, address, data_type)

    def load_file(self, load_call_proxy=None):
        if load_call_proxy is None:
            def load_call_proxy(f, *args, **kwargs):
                return f(*args, **kwargs)

        self.reset_state()

        # Request a file name to load.
        load_file, file_path = self.client.request_load_file()
        if load_file is None:
            return
        if type(load_file) in types.StringTypes:
            self.reset_state()
            return load_file

        self.state_id = EditorState.STATE_LOADING
        file_name = os.path.basename(file_path)
        is_saved_project = disassembly_persistence.check_is_project_file(load_file)

        if is_saved_project:
            result = load_call_proxy(disassembly.load_project_file, load_file, file_name)
        else:
            new_options = disassembly.get_new_project_options(self.disassembly_data)
            # Populate useful fields.
            identify_result = loaderlib.identify_file(load_file)
            if identify_result is not None:
                new_options.is_binary_file = False
                new_options.loader_load_address = loaderlib.get_load_address(identify_result[0])
                new_options.loader_entrypoint_offset = loaderlib.get_entrypoint_address(identify_result[0])
                new_options.loader_filetype = identify_result[1]["filetype"]
                new_options.loader_processor = identify_result[1]["processor"]
            else:
                new_options.is_binary_file = True
                new_options.loader_load_address = 0
                new_options.loader_entrypoint_offset = 0
                new_options.loader_filetype = ""
                new_options.loader_processor = ""
            # Prompt for new project option values.
            new_options = self.client.request_new_project_option_values(new_options)
            # Verify that all values are provided correctly.
            errmsg = self.client.validate_new_project_option_values(new_options)
            if errmsg is not None:
                self.reset_state()
                return errmsg
            result = load_call_proxy(disassembly.load_file, load_file, new_options, file_name)

        self.state_id = EditorState.STATE_LOADED
        self.disassembly_data, line_count = result

        if line_count == 0:
            self.reset_state()
            return ERRMSG_NOT_SUPPORTED_EXECUTABLE_FILE_FORMAT

        is_saved_project = disassembly_persistence.check_is_project_file(self.client.get_load_file())
        if is_saved_project:
            # User may have optionally chosen to not save the input file, as part of the project file.
            if not disassembly.is_segment_data_cached(self.disassembly_data):
                # Inform the user of the purpose of the next file dialog.
                if not self.client.request_confirmation(TEXT_LOAD_INPUT_FILE_TITLE, TEXT_LOAD_INPUT_FILE_BODY):
                    self.reset_state()
                    return None

                # Show the "locate input file" dialog.
                input_result = self.client.request_load_file()
                if input_result is None or type(input_result) in types.StringTypes:
                    self.reset_state()
                    return input_result

                input_data_file, input_data_file_path = input_result
                input_data_file.seek(0, os.SEEK_END)
                errmsg = None
                if input_data_file.tell() != self.disassembly_data.file_size:
                    errmsg = ERRMSG_INPUT_FILE_SIZE_DIFFERS
                elif util.calculate_file_checksum(input_data_file) != self.disassembly_data.file_checksum:
                    errmsg = ERRMSG_INPUT_FILE_CHECKSUM_MISMATCH
                if type(errmsg) in types.StringTypes:
                    self.reset_state()
                    return errmsg
                disassembly.cache_segment_data(self.disassembly_data, input_data_file)

        entrypoint_address = disassembly.get_entrypoint_address(self.disassembly_data)
        line_number = disassembly.get_line_number_for_address(self.disassembly_data, entrypoint_address)
        self.set_line_number(line_number)
        return result

    def save_project(self):
        if self.state_id != EditorState.STATE_LOADED:
            return ERRMSG_TODO_BAD_STATE_FUNCTIONALITY

        save_options = disassembly.get_save_project_options(self.disassembly_data)
        # Install higher-level defined and used option attributes.
        save_options.cache_input_file = disassembly.get_project_save_count(self.disassembly_data) == 0 or disassembly.is_project_inputfile_cached(self.disassembly_data)
        # Prompt user if they want to save the source file.
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

        # Prompt for save file name.
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

