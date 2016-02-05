"""
    Peasauce - interactive disassembler
    Copyright (C) 2012-2016 Richard Tew
    Licensed using the MIT license.
"""

"""
This file is supposed to abstract the actions a user might perform, so that any
interface, whether a user facing GUI or separate script, might use it without
reproducing the same logic.
"""

# TODO: Look at revisiting the navigation by line numbers (see get_address commentary).

import os
import types
import threading
import time
import traceback
import weakref

import disassembly
import disassembly_data # DATA TYPES ONLY
import disassembly_persistence
import loaderlib
import util


TEXT_SELECT_REFERRING_ADDRESS_SHORT = "Go to which referring address?"
TEXT_SELECT_REFERRING_ADDRESS_LONG = "Select on the following and press the enter key, or click on the button, to jump to the given referring address."
TEXT_GO_TO_SELECTION = "Go to selection"

ERRMSG_NOT_SUPPORTED_EXECUTABLE_FILE_FORMAT = "The file does not appear to be a supported executable file format."
ERRMSG_NO_IDENTIFIABLE_DESTINATION = "Nowhere to go."
ERRMSG_INPUT_FILE_NOT_FOUND = "Input file not found."
ERRMSG_INPUT_FILE_CHECKSUM_MISMATCH = "File does not match (checksum differs)"
ERRMSG_INPUT_FILE_SIZE_DIFFERS = "File does not match (size differs)"
ERRMSG_INVALID_LABEL_NAME = "Invalid label name"

ERRMSG_BUG_UNKNOWN_ADDRESS = "Unable to determine address at current line, this is a bug."
ERRMSG_BUG_NO_OPERAND_SELECTION_MECHANISM = "Too many valid operands, this is a bug."
ERRMSG_BUG_UNABLE_TO_GOTO_LINE = "Unable to go to the given line, this is a bug."

ERRMSG_TODO_BAD_STATE_FUNCTIONALITY = "TODO: Work out you can do this in the current program state."

import re

RE_LABEL = re.compile("([\.]*[a-zA-Z_]+[a-zA-Z0-9_\.]*)$")


class ClientAPI(object):
    def __init__(self, owner):
        super(ClientAPI, self).__init__()

        self.owner_ref = weakref.ref(owner)

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

    def request_load_project_option_values(self, load_options):
        """ Returns the user modified options. """
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

    def event_tick(self, active_client):
        raise NotImplementedError

    def event_prolonged_action(self, active_client, title_msg_id, description_msg_id, can_cancel, step_count, abort_callback):
        raise NotImplementedError

    def event_prolonged_action_update(self, active_client, description_msg_id, step_number):
        raise NotImplementedError

    def event_prolonged_action_complete(self, active_client):
        raise NotImplementedError

    def event_load_start(self, active_client, file_path):
        raise NotImplementedError

    def event_load_successful(self, active_client):
        raise NotImplementedError

    def event_pre_line_change(self, active_client, line0, line_count):
        raise NotImplementedError

    def event_post_line_change(self, active_client, line0, line_count):
        raise NotImplementedError

    def event_uncertain_reference_modification(self, active_client, data_type_from, data_type_to, address, length):
        raise NotImplementedError

    def event_symbol_added(self, active_client, symbol_address, symbol_label):
        raise NotImplementedError

    def event_symbol_removed(self, active_client, symbol_address, symbol_label):
        raise NotImplementedError


class WorkState(object):
    completeness = 0.0
    description = "?"
    cancelled = False

    def get_completeness(self): return self.completeness
    def set_completeness(self, f): self.completeness = f
    def get_description(self): return self.description
    def set_description(self, s): self.description = s
    def cancel(self): self.cancelled = True
    def is_cancelled(self): return self.cancelled
    def check_exit_update(self, f, s): self.set_completeness(f); self.set_description(s); return self.cancelled


class EditorState(object):
    STATE_INITIAL = 0
    STATE_LOADING = 1
    STATE_LOADED = 2

    def __init__(self):
        self.worker_thread = WorkerThread()
        self.clients = weakref.WeakSet()
        self.reset_state(None)

    def on_app_exit(self):
        self.worker_thread.stop()

    def register_client(self, client):
        self.clients.add(client)

    def unregister_client(self, client):
        self.clients.remove(client)

    def in_initial_state(self, acting_client): return self.state_id == EditorState.STATE_INITIAL
    def in_loading_state(self, acting_client): return self.state_id == EditorState.STATE_LOADING
    def in_loaded_state(self, acting_client): return self.state_id == EditorState.STATE_LOADED

    def is_project_file(self, acting_client, input_file):
        return disassembly_persistence.check_is_project_file(input_file)

    def reset_state(self, acting_client):
        self.disassembly_data = None
        self.line_number = 0
        self.specific_address = None
        self.address_stack = []

        # Clear out related data.
        for client in self.clients:
            client.reset_state()

        # Finally, reset the state.
        self.state_id = EditorState.STATE_INITIAL

    def _prolonged_action(self, acting_client, title_msg_id, description_msg_id, f, *args, **kwargs):
        # Remove keywork arguments meant to customise the call.
        step_count = kwargs.pop("step_count", 100)
        can_cancel = kwargs.pop("can_cancel", True)

        work_state = kwargs["work_state"] = WorkState()
        def cancel_callback():
            work_state.cancel()
        # Notify clients the action is starting.
        for client in self.clients:
            client.event_prolonged_action(client is acting_client, title_msg_id, description_msg_id, can_cancel, step_count, cancel_callback)
        # Start the work and periodically check for it's completion, or cancellation.
        completed_event = self.worker_thread.add_work(f, *args, **kwargs)
        last_completeness, last_description = None, None
        while not completed_event.wait(0.1) and not work_state.is_cancelled():
            work_completeness, work_description = work_state.get_completeness(), work_state.get_description()
            for client in self.clients:
                if work_completeness != last_completeness or work_description != last_description:
                    client.event_prolonged_action_update(client is acting_client, work_description, step_count * work_completeness)
                client.event_tick(client is acting_client)
            last_completeness, last_description = work_completeness, work_description
        # Notify clients the action is completed.
        for client in self.clients:
            client.event_prolonged_action_complete(client is acting_client)
        if completed_event.is_set():
            return completed_event.result
        return None

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

    def get_data_type_for_address(self, acting_client, address):
        data_type = disassembly.get_data_type_for_address(self.disassembly_data, address)
        if data_type == disassembly_data.DATA_TYPE_CODE:
            return "code"
        elif data_type == disassembly_data.DATA_TYPE_ASCII:
            return "ascii"
        elif data_type == disassembly_data.DATA_TYPE_BYTE:
            return "8bit"
        elif data_type == disassembly_data.DATA_TYPE_WORD:
            return "16bit"
        elif data_type == disassembly_data.DATA_TYPE_LONGWORD:
            return "32bit"

    def get_source_code_for_address(self, acting_client, address):
        line_idx = disassembly.get_line_number_for_address(self.disassembly_data, address)
        return self.get_source_code_for_line_number(acting_client, line_idx)

    def get_source_code_for_line_number(self, acting_client, line_idx):
        code_string = disassembly.get_file_line(self.disassembly_data, line_idx, disassembly.LI_INSTRUCTION)
        operands_text = disassembly.get_file_line(self.disassembly_data, line_idx, disassembly.LI_OPERANDS)
        if len(operands_text):
            code_string += " "+ operands_text
        return code_string

    def get_row_for_line_number(self, acting_client, line_idx):
        return [
            disassembly.get_file_line(self.disassembly_data, line_idx, disassembly.LI_OFFSET),
            disassembly.get_file_line(self.disassembly_data, line_idx, disassembly.LI_BYTES),
            disassembly.get_file_line(self.disassembly_data, line_idx, disassembly.LI_LABEL),
            disassembly.get_file_line(self.disassembly_data, line_idx, disassembly.LI_INSTRUCTION),
            disassembly.get_file_line(self.disassembly_data, line_idx, disassembly.LI_OPERANDS),
        ]

    def get_referring_addresses_for_address(self, acting_client, address):
        return list(disassembly.get_referring_addresses(self.disassembly_data, address))

    def get_address(self, acting_client):
        # The current line number is the start of the block line which the specific address falls
        # within.  If the units are 16 bits, the line number may be for 0x10000 and the actual
        # specific user targeted address may be 0x10001.  This is a complication, and it may be
        # worth reconsidering dealing with things in terms of line numbers.  TODO.
        if self.specific_address is not None:
            return self.specific_address
        return disassembly.get_address_for_line_number(self.disassembly_data, self.line_number)

    def get_line_number_for_address(self, acting_client, address):
        return disassembly.get_line_number_for_address(self.disassembly_data, address)

    def get_line_number(self, acting_client):
        return self.line_number

    def set_line_number(self, acting_client, line_number, specific_address=None):
        if type(line_number) not in (int, long):
            raise ValueError("expected numeric type, got %s (%s)" % (line_number.__class__.__name__, line_number))
        self.line_number = line_number
        self.specific_address = specific_address

    def get_line_count(self, acting_client):
        if self.disassembly_data is None:
            return 0
        return disassembly.get_file_line_count(self.disassembly_data)

    def get_file_line(self, acting_client, row, column):
        if self.disassembly_data is None:
            return ""
        return disassembly.get_file_line(self.disassembly_data, row, column)

    def get_symbols(self, acting_client):
        return self.disassembly_data.symbols_by_address.items()

    def push_address(self, acting_client):
        if self.state_id != EditorState.STATE_LOADED:
            return ERRMSG_TODO_BAD_STATE_FUNCTIONALITY

        current_address = self.get_address(acting_client)
        if current_address is None:
            return ERRMSG_BUG_UNKNOWN_ADDRESS

        operand_addresses = disassembly.get_referenced_symbol_addresses_for_line_number(self.disassembly_data, self.line_number)
        if len(operand_addresses) == 1:
            next_line_number = disassembly.get_line_number_for_address(self.disassembly_data, operand_addresses[0])
            if next_line_number is None:
                return ERRMSG_BUG_UNABLE_TO_GOTO_LINE

            self.set_line_number(acting_client, next_line_number)
            self.address_stack.append(current_address)
            return
        elif len(operand_addresses) == 2:
            return ERRMSG_BUG_NO_OPERAND_SELECTION_MECHANISM

        return ERRMSG_NO_IDENTIFIABLE_DESTINATION

    def pop_address(self, acting_client):
        if self.state_id != EditorState.STATE_LOADED:
            return ERRMSG_TODO_BAD_STATE_FUNCTIONALITY

        if not len(self.address_stack):
            return ERRMSG_NO_IDENTIFIABLE_DESTINATION

        address = self.address_stack.pop()
        # It is expected that if you can have pushed the address, there was a line number for it.
        line_number = disassembly.get_line_number_for_address(self.disassembly_data, address)
        self.set_line_number(acting_client, line_number)

    def goto_address(self, acting_client):
        address = self.get_address(acting_client)
        if address is None: # Current line does not have an address.
            address = 0
        result = acting_client.request_address(address)
        if result is None: # Cancelled / aborted.
            return
        # Convert an entered symbol name to it's address.
        if type(result) in types.StringTypes:
            result = disassembly.get_address_for_symbol(self.disassembly_data, result)
            if result is None:
                return ERRMSG_NO_IDENTIFIABLE_DESTINATION
        line_number = disassembly.get_line_number_for_address(self.disassembly_data, result)
        self.set_line_number(acting_client, line_number, result)

    def goto_referring_address(self, acting_client):
        current_address = self.get_address(acting_client)
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
            code_string = self.get_source_code_for_address(acting_client, address)
            address_rows.append((self._address_to_string(address), converted_addresses[i], code_string))

        selected_address = acting_client.request_address_selection(TEXT_SELECT_REFERRING_ADDRESS_SHORT, TEXT_SELECT_REFERRING_ADDRESS_LONG, TEXT_GO_TO_SELECTION, address_rows, addresses)
        if selected_address is None:
            return False

        next_line_number = disassembly.get_line_number_for_address(self.disassembly_data, selected_address)
        if next_line_number is None:
            return ERRMSG_BUG_UNABLE_TO_GOTO_LINE

        self.set_line_number(acting_client, next_line_number)
        self.address_stack.append(current_address)
        return True

    def goto_previous_data_block(self, acting_client):
        line_idx = self.get_line_number(acting_client)
        new_line_idx = disassembly.get_next_data_line_number(self.disassembly_data, line_idx, -1)
        if new_line_idx is None:
            return ERRMSG_NO_IDENTIFIABLE_DESTINATION
        self.set_line_number(acting_client, new_line_idx)

    def goto_next_data_block(self, acting_client):
        line_idx = self.get_line_number(acting_client)
        new_line_idx = disassembly.get_next_data_line_number(self.disassembly_data, line_idx, 1)
        if new_line_idx is None:
            return ERRMSG_NO_IDENTIFIABLE_DESTINATION
        self.set_line_number(acting_client, new_line_idx)

    ## UNCERTAIN REFERENCES:

    def _uncertain_reference_modification_callback(self, data_type_from, data_type_to, address, length):
        if data_type_from == disassembly_data.DATA_TYPE_CODE:
            data_type_from = "CODE"
        else:
            data_type_from = "DATA"
        if data_type_to == disassembly_data.DATA_TYPE_CODE:
            data_type_to = "CODE"
        else:
            data_type_to = "DATA"

        acting_client = None # TODO: Reconsider whether this is valid.
        for client in self.clients:
            client.event_uncertain_reference_modification(client is acting_client, data_type_from, data_type_to, address, length)

    def get_uncertain_code_references(self, acting_client):
        return disassembly.get_uncertain_code_references(self.disassembly_data)

    def get_uncertain_data_references(self, acting_client):
        return disassembly.get_uncertain_data_references(self.disassembly_data)

    def get_uncertain_references_by_address(self, acting_client, address):
        return disassembly.get_uncertain_references_by_address(self.disassembly_data, address)

    ## GENERAL:

    def _symbol_insert_callback(self, symbol_address, symbol_label):
        acting_client = None # TODO: Reconsider whether this is valid.
        for client in self.clients:
            client.event_symbol_added(client is acting_client, symbol_address, symbol_label)

    def _symbol_delete_callback(self, symbol_address, symbol_label):
        acting_client = None # TODO: Reconsider whether this is valid.
        for client in self.clients:
            client.event_symbol_removed(client is acting_client, symbol_address, symbol_label)

    def set_label_name(self, acting_client):
        if self.state_id != EditorState.STATE_LOADED:
            return ERRMSG_TODO_BAD_STATE_FUNCTIONALITY

        current_address = self.get_address(acting_client)
        symbol_name = disassembly.get_symbol_for_address(self.disassembly_data, current_address)
        # Prompt user to edit the current label, or add a new one.
        new_symbol_name = acting_client.request_label_name(symbol_name)
        if new_symbol_name is not None and new_symbol_name != symbol_name:
            match = RE_LABEL.match(new_symbol_name)
            if match is None:
                return ERRMSG_INVALID_LABEL_NAME
            disassembly.set_symbol_for_address(self.disassembly_data, current_address, new_symbol_name)

    def set_datatype_code(self, acting_client):
        if self.state_id != EditorState.STATE_LOADED:
            return ERRMSG_TODO_BAD_STATE_FUNCTIONALITY

        address = self.get_address(acting_client)
        if address is None:
            return ERRMSG_BUG_UNKNOWN_ADDRESS
        self._set_data_type(acting_client, address, disassembly_data.DATA_TYPE_CODE)

    def set_datatype_32bit(self, acting_client):
        if self.state_id != EditorState.STATE_LOADED:
            return ERRMSG_TODO_BAD_STATE_FUNCTIONALITY

        address = self.get_address(acting_client)
        if address is None:
            return ERRMSG_BUG_UNKNOWN_ADDRESS
        self._set_data_type(acting_client, address, disassembly_data.DATA_TYPE_LONGWORD)

    def set_datatype_16bit(self, acting_client):
        if self.state_id != EditorState.STATE_LOADED:
            return ERRMSG_TODO_BAD_STATE_FUNCTIONALITY

        address = self.get_address(acting_client)
        if address is None:
            return ERRMSG_BUG_UNKNOWN_ADDRESS
        self._set_data_type(acting_client, address, disassembly_data.DATA_TYPE_WORD)

    def set_datatype_8bit(self, acting_client):
        if self.state_id != EditorState.STATE_LOADED:
            return ERRMSG_TODO_BAD_STATE_FUNCTIONALITY

        address = self.get_address(acting_client)
        if address is None:
            return ERRMSG_BUG_UNKNOWN_ADDRESS
        self._set_data_type(acting_client, address, disassembly_data.DATA_TYPE_BYTE)

    def set_datatype_ascii(self, acting_client):
        if self.state_id != EditorState.STATE_LOADED:
            return ERRMSG_TODO_BAD_STATE_FUNCTIONALITY

        address = self.get_address(acting_client)
        if address is None:
            return ERRMSG_BUG_UNKNOWN_ADDRESS
        self._set_data_type(acting_client, address, disassembly_data.DATA_TYPE_ASCII)

    def _set_data_type(self, acting_client, address, data_type):
        self._prolonged_action(acting_client, "TITLE_DATA_TYPE_CHANGE", "TEXT_GENERIC_PROCESSING", disassembly.set_data_type_at_address, self.disassembly_data, address, data_type, can_cancel=False)

    def load_file(self, acting_client):
        self.reset_state(acting_client)

        # Request a file name to load.
        result = acting_client.request_load_file()
        if result is None:
            return
        if type(result) in types.StringTypes:
            self.reset_state(acting_client)
            return result
        load_file, file_path = result

        self.state_id = EditorState.STATE_LOADING
        file_name = os.path.basename(file_path)
        is_saved_project = disassembly_persistence.check_is_project_file(load_file)

        for client in self.clients:
            client.event_load_start(client is acting_client, file_path)

        if is_saved_project:
            result = self._prolonged_action(acting_client, "TITLE_LOADING_PROJECT", "TEXT_GENERIC_LOADING", disassembly.load_project_file, load_file, file_name)
        else:
            new_options = disassembly.get_new_project_options(self.disassembly_data)
            identify_result = loaderlib.identify_file(load_file, file_name)
            # Parameters passed in, to help the client make up it's mind.
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
                new_options.loader_filetype = loaderlib.constants.FILE_FORMAT_UNKNOWN
                new_options.loader_processor = ""
            # Prompt for new project option values.
            new_option_result = acting_client.request_new_project_option_values(new_options)
            if new_option_result is None or type(new_option_result) in types.StringTypes:
                self.reset_state(acting_client)
                return new_option_result

            result = self._prolonged_action(acting_client, "TITLE_LOADING_FILE", "TEXT_GENERIC_LOADING", disassembly.load_file, load_file, new_option_result, file_name)

        # Loading was cancelled.
        if result is None:
            self.reset_state(acting_client)
            return

        self.state_id = EditorState.STATE_LOADED
        self.disassembly_data, line_count = result

        # Register our event dispatching callbacks.
        disassembly.set_uncertain_reference_modification_func(self.disassembly_data, self._uncertain_reference_modification_callback)
        disassembly.set_symbol_insert_func(self.disassembly_data, self._symbol_insert_callback)
        disassembly.set_symbol_delete_func(self.disassembly_data, self._symbol_delete_callback)

        if line_count == 0:
            self.reset_state(acting_client)
            return ERRMSG_NOT_SUPPORTED_EXECUTABLE_FILE_FORMAT

        is_saved_project = disassembly_persistence.check_is_project_file(acting_client.get_load_file())
        if is_saved_project:
            # User may have optionally chosen to not save the input file, as part of the project file.
            if not disassembly.is_segment_data_cached(self.disassembly_data):
                load_options = disassembly.get_new_project_options(self.disassembly_data)
                # Parameters passed in, to help the client make up it's mind.
                load_options.input_file_filesize = self.disassembly_data.file_size
                load_options.input_file_filename = self.disassembly_data.file_name
                load_options.input_file_checksum = self.disassembly_data.file_checksum
                # Parameters received out, our "return values".
                load_options.loader_file_path = None
                load_options = acting_client.request_load_project_option_values(load_options)

                if load_options.loader_file_path is None:
                    self.reset_state(acting_client)
                    return ERRMSG_INPUT_FILE_NOT_FOUND

                # Verify that the given input file is valid, or error descriptively.
                with open(load_options.loader_file_path, "rb") as input_data_file:
                    input_data_file.seek(0, os.SEEK_END)
                    errmsg = None
                    if input_data_file.tell() != self.disassembly_data.file_size:
                        errmsg = ERRMSG_INPUT_FILE_SIZE_DIFFERS
                    elif util.calculate_file_checksum(input_data_file) != self.disassembly_data.file_checksum:
                        errmsg = ERRMSG_INPUT_FILE_CHECKSUM_MISMATCH
                    if type(errmsg) in types.StringTypes:
                        self.reset_state(acting_client)
                        return errmsg
                    disassembly.cache_segment_data(self.disassembly_data, input_data_file)
                    disassembly.load_project_file_finalise(self.disassembly_data)

        entrypoint_address = disassembly.get_entrypoint_address(self.disassembly_data)
        line_number = disassembly.get_line_number_for_address(self.disassembly_data, entrypoint_address)
        self.set_line_number(acting_client, line_number)

        def _pre_line_change_callback(line0, line_count):
            for client in self.clients:
                client.event_pre_line_change(client is acting_client, line0, line_count)
        self.disassembly_data.pre_line_change_func = _pre_line_change_callback
        def _post_line_change_callback(line0, line_count):
            for client in self.clients:
                client.event_post_line_change(client is acting_client, line0, line_count)
        self.disassembly_data.post_line_change_func = _post_line_change_callback

        for client in self.clients:
            client.event_load_successful(client is acting_client)
        return result

    def save_project(self, acting_client):
        if self.state_id != EditorState.STATE_LOADED:
            return ERRMSG_TODO_BAD_STATE_FUNCTIONALITY

        save_options = disassembly.get_save_project_options(self.disassembly_data)
        # Install higher-level defined and used option attributes.
        save_options.cache_input_file = disassembly.get_project_save_count(self.disassembly_data) == 0 or disassembly.is_project_inputfile_cached(self.disassembly_data)
        # Prompt user if they want to save the source file.
        save_options = acting_client.request_save_project_option_values(save_options)
        # User chose to cancel the save process.
        if save_options is None:
            return
        if save_options.cache_input_file:
            save_options.input_file = acting_client.get_load_file()

        with open(save_options.save_file_path, "wb") as f:
            disassembly.save_project_file(f, self.disassembly_data, save_options)

    def export_source_code(self, acting_client):
        if self.state_id != EditorState.STATE_LOADED:
            return ERRMSG_TODO_BAD_STATE_FUNCTIONALITY

        line_count = disassembly.get_file_line_count(self.disassembly_data)

        # Prompt for save file name.
        save_file = acting_client.request_code_save_file()
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


class WorkerThread(threading.Thread):
    def __init__(self, *args, **kwargs):
        super(WorkerThread, self).__init__(*args, **kwargs)

        self.lock = threading.RLock()
        self.condition = threading.Condition(self.lock)

        self.quit = False
        self.work_data = []

    def stop(self):
        self.lock.acquire()
        self.quit = True
        self.work_data = []
        self.condition.notify()
        self.lock.release()
        #self.wait() # Wait until thread execution has finished.

    def add_work(self, _callable, *_args, **_kwargs):
        self.lock.acquire()
        completed_event = threading.Event()
        completed_event.result = None
        self.work_data.append((_callable, _args, _kwargs, completed_event))

        if not self.is_alive():
            self.start()
        else:
            self.condition.notify()
        self.lock.release()
        return completed_event

    def run(self):
        self.lock.acquire()
        work_data = self.work_data.pop(0)
        self.lock.release()

        while not self.quit:
            completed_event = work_data[3]
            try:
                try:
                    completed_event.result = work_data[0](*work_data[1], **work_data[2])
                    completed_event.set()
                except Exception:
                    traceback.print_stack()
                    raise
            except SystemExit:
                traceback.print_exc()
                raise
            work_data = None

            self.lock.acquire()
            # Wait for the next piece of work.
            if not len(self.work_data):
                self.condition.wait()
            if not self.quit:
                work_data = self.work_data.pop(0)
            self.lock.release()

