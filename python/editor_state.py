"""
    Peasauce - interactive disassembler
    Copyright (C) 2012-2017 Richard Tew
    Licensed using the MIT license.
"""

"""
This file is supposed to abstract the actions a user might perform, so that any
interface, whether a user facing GUI or separate script, might use it without
reproducing the same logic.
"""

# TODO: Look at revisiting the navigation by line numbers (see get_address commentary).

import operator
import os
import types
import weakref
from typing import Any

import disassembly
import disassembly_data # DATA TYPES ONLY
import disassembly_persistence
import disassembly_util
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


class EditorState(object):
    STATE_INITIAL = 0
    STATE_LOADING = 1
    STATE_LOADED = 2

    disassembly_state = None # type: disassembly.DisassemblyApi

    def __init__(self):
        self.worker_thread = disassembly_util.WorkerThread()
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
        self.disassembly_state = None
        self.line_number = 0
        self.address_stack = []
        self.last_search_text = None
        self.last_search_direction = None

        # Clear out related data.
        for client in self.clients:
            client.reset_state()

        # Finally, reset the state.
        self.state_id = EditorState.STATE_INITIAL

    def _prolonged_action(self, acting_client, title_msg_id, description_msg_id, f, *args, **kwargs):
        # Remove keywork arguments meant to customise the call.
        step_count = kwargs.pop("step_count", 100)
        can_cancel = kwargs.pop("can_cancel", True)

        work_state = kwargs["work_state"] = disassembly_util.WorkState()
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
            symbol_name = self.disassembly_state.get_symbol_for_address(address)
            if symbol_name is not None:
                addresses[i] = symbol_name
            else:
                addresses[i] = self._address_to_string(address)

    def get_data_type_for_address(self, acting_client, address):
        data_type = self.disassembly_state.get_data_type_for_address(address)
        if data_type == disassembly_data.DATA_TYPE_CODE:
            return "code"
        elif data_type == disassembly_data.DATA_TYPE_ASCII:
            return "ascii"
        elif data_type == disassembly_data.DATA_TYPE_DATA08:
            return "8bit"
        elif data_type == disassembly_data.DATA_TYPE_DATA16:
            return "16bit"
        elif data_type == disassembly_data.DATA_TYPE_DATA32:
            return "32bit"

    def get_source_code_for_address(self, acting_client, address):
        line_idx = self.disassembly_state.get_line_number_for_address(address)
        return self.get_source_code_for_line_number(acting_client, line_idx)

    def get_source_code_for_line_number(self, acting_client, line_idx):
        code_string = self.disassembly_state.get_file_line(line_idx, disassembly.LI_INSTRUCTION)
        operands_text = self.disassembly_state.get_file_line(line_idx, disassembly.LI_OPERANDS)
        if len(operands_text):
            code_string += " "+ operands_text
        return code_string

    def get_row_for_line_number(self, acting_client, line_idx):
        return [
            self.disassembly_state.get_file_line(line_idx, disassembly.LI_OFFSET),
            self.disassembly_state.get_file_line(line_idx, disassembly.LI_BYTES),
            self.disassembly_state.get_file_line(line_idx, disassembly.LI_LABEL),
            self.disassembly_state.get_file_line(line_idx, disassembly.LI_INSTRUCTION),
            self.disassembly_state.get_file_line(line_idx, disassembly.LI_OPERANDS),
        ]

    def get_referring_addresses_for_address(self, acting_client, address):
        return list(self.disassembly_state.get_referring_addresses(address))

    def get_address(self, acting_client):
        # The current line number is the start of the block line which the specific address falls
        # within.  If the units are 16 bits, the line number may be for 0x10000 and the actual
        # specific user targeted address may be 0x10001.  This is a complication, and it may be
        # worth reconsidering dealing with things in terms of line numbers.  TODO.
        return self.disassembly_state.get_address_for_line_number(self.line_number)

    def get_address_for_line_number(self, acting_client, line_number):
        return self.disassembly_state.get_address_for_line_number(line_number)

    def get_line_number_for_address(self, acting_client, address):
        return self.disassembly_state.get_line_number_for_address(address)

    def get_line_number(self, acting_client):
        return self.line_number

    def set_line_number(self, acting_client, line_number):
        if type(line_number) not in (int, long):
            raise ValueError("expected numeric type, got %s (%s)" % (line_number.__class__.__name__, line_number))
        self.line_number = line_number

    def get_line_count(self, acting_client):
        if self.disassembly_state is None:
            return 0
        return self.disassembly_state.get_file_line_count()

    def get_file_line(self, acting_client, row, column):
        if self.disassembly_state is None:
            return ""
        return self.disassembly_state.get_file_line(row, column)

    def get_symbols(self, acting_client):
        return self.disassembly_state.get_symbols()

    def push_address(self, acting_client):
        if self.state_id != EditorState.STATE_LOADED:
            return ERRMSG_TODO_BAD_STATE_FUNCTIONALITY

        current_address = self.get_address(acting_client)
        if current_address is None:
            return ERRMSG_BUG_UNKNOWN_ADDRESS

        operand_addresses = self.disassembly_state.get_referenced_symbol_addresses_for_line_number(self.line_number)
        if len(operand_addresses) == 1:
            next_line_number = self.disassembly_state.get_line_number_for_address(operand_addresses[0])
            if next_line_number is None:
                return ERRMSG_NO_IDENTIFIABLE_DESTINATION

            self.set_line_number(acting_client, next_line_number)
            self.address_stack.append(current_address)
            return
        elif len(operand_addresses) == 2:
            return ERRMSG_BUG_NO_OPERAND_SELECTION_MECHANISM

        return ERRMSG_NO_IDENTIFIABLE_DESTINATION

    def if_uncertain_data_reference_address(self, acting_client):
        if self.state_id != EditorState.STATE_LOADED:
            return ERRMSG_TODO_BAD_STATE_FUNCTIONALITY

        current_address = self.get_address(acting_client)
        if current_address is None:
            return ERRMSG_BUG_UNKNOWN_ADDRESS

        references = self.disassembly_state.get_uncertain_references_by_address(current_address)
        for (address, value, text) in references:
            if address == current_address:
                return

        return ERRMSG_NO_IDENTIFIABLE_DESTINATION

    def pop_address(self, acting_client):
        if self.state_id != EditorState.STATE_LOADED:
            return ERRMSG_TODO_BAD_STATE_FUNCTIONALITY

        if not len(self.address_stack):
            return ERRMSG_NO_IDENTIFIABLE_DESTINATION

        address = self.address_stack.pop()
        # It is expected that if you can have pushed the address, there was a line number for it.
        line_number = self.disassembly_state.get_line_number_for_address(address)
        self.set_line_number(acting_client, line_number)

    def search_text(self, acting_client):
        result = acting_client.request_text("Find what?", "Text:", self.last_search_text or "")
        if result is None:
            return
        self.last_search_text = result
        if self.last_search_direction is None:
            self.last_search_direction = 1

        return self.goto_next_text_match(acting_client)

    def goto_address(self, acting_client):
        address = self.get_address(acting_client)
        if address is None: # Current line does not have an address.
            address = 0
        result = acting_client.request_address(address)
        if result is None: # Cancelled / aborted.
            return
        # Convert an entered symbol name to it's address.
        if type(result) in types.StringTypes:
            result = self.disassembly_state.get_address_for_symbol(result)
            if result is None:
                return ERRMSG_NO_IDENTIFIABLE_DESTINATION
        line_number = self.disassembly_state.get_line_number_for_address(result)
        if line_number is None:
            return ERRMSG_NO_IDENTIFIABLE_DESTINATION
        self.set_line_number(acting_client, line_number)

    def goto_referring_address(self, acting_client):
        current_address = self.get_address(acting_client)
        if current_address is None:
            return ERRMSG_NO_IDENTIFIABLE_DESTINATION

        addresses = list(self.disassembly_state.get_referring_addresses(current_address))
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

        next_line_number = self.disassembly_state.get_line_number_for_address(selected_address)
        if next_line_number is None:
            return ERRMSG_NO_IDENTIFIABLE_DESTINATION

        self.set_line_number(acting_client, next_line_number)
        self.address_stack.append(current_address)
        return True

    def goto_previous_code_block(self, acting_client):
        line_idx = self.get_line_number(acting_client)
        new_line_idx = self.disassembly_state.get_next_block_line_number(disassembly_data.DATA_TYPE_CODE, line_idx, -1)
        if new_line_idx is None:
            return ERRMSG_NO_IDENTIFIABLE_DESTINATION
        self.set_line_number(acting_client, new_line_idx)

    def goto_previous_data_block(self, acting_client):
        line_idx = self.get_line_number(acting_client)
        new_line_idx = self.disassembly_state.get_next_block_line_number(disassembly_data.DATA_TYPE_CODE, line_idx, -1, operator.ne)
        if new_line_idx is None:
            return ERRMSG_NO_IDENTIFIABLE_DESTINATION
        self.set_line_number(acting_client, new_line_idx)

    def goto_previous_text_match(self, acting_client):
        # If no text to search for, prompt for it.
        if self.last_search_text is None:
            self.last_search_direction = -1
            return self.search_text(acting_client)
        result = self._prolonged_action(acting_client, "TITLE_SEARCHING", "TEXT_GENERIC_PROCESSING", self._search_text, acting_client, -1)
        if type(result) in types.StringTypes:
            return result
        if result is not None:
            self.set_line_number(acting_client, result)

    def goto_next_code_block(self, acting_client):
        line_idx = self.get_line_number(acting_client)
        new_line_idx = self.disassembly_state.get_next_block_line_number(disassembly_data.DATA_TYPE_CODE, line_idx, 1)
        if new_line_idx is None:
            return ERRMSG_NO_IDENTIFIABLE_DESTINATION
        self.set_line_number(acting_client, new_line_idx)

    def goto_next_data_block(self, acting_client):
        line_idx = self.get_line_number(acting_client)
        new_line_idx = self.disassembly_state.get_next_block_line_number(disassembly_data.DATA_TYPE_CODE, line_idx, 1, operator.ne)
        if new_line_idx is None:
            return ERRMSG_NO_IDENTIFIABLE_DESTINATION
        self.set_line_number(acting_client, new_line_idx)

    def goto_next_text_match(self, acting_client):
        # If no text to search for, prompt for it.
        if self.last_search_text is None:
            return self.search_text(acting_client)
        result = self._prolonged_action(acting_client, "TITLE_SEARCHING", "TEXT_GENERIC_PROCESSING", self._search_text, acting_client, 1)
        if type(result) in types.StringTypes:
            return result
        if result is not None:
            self.set_line_number(acting_client, result)

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
        return self.disassembly_state.get_uncertain_code_references()

    def get_uncertain_data_references(self, acting_client):
        return self.disassembly_state.get_uncertain_data_references()

    def get_uncertain_references_by_address(self, acting_client, address):
        return self.disassembly_state.get_uncertain_references_by_address(address)

    def get_operand_count(self, acting_client, line_number):
        return self.disassembly_state.get_operand_count_for_line_number(line_number)

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
        symbol_name = self.disassembly_state.get_symbol_for_address(current_address)
        # Prompt user to edit the current label, or add a new one.
        new_symbol_name = acting_client.request_label_name(symbol_name)
        if new_symbol_name is not None and new_symbol_name != symbol_name:
            match = RE_LABEL.match(new_symbol_name)
            if match is None:
                return ERRMSG_INVALID_LABEL_NAME
            self.disassembly_state.set_symbol_for_address(current_address, new_symbol_name)

    def add_label_for_value(self, acting_client):
        if self.state_id != EditorState.STATE_LOADED:
            return ERRMSG_TODO_BAD_STATE_FUNCTIONALITY

        current_address = self.get_address(acting_client)
        self.disassembly_state.insert_reference_address(current_address)

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
        self._set_data_type(acting_client, address, disassembly_data.DATA_TYPE_DATA32)

    def set_datatype_16bit(self, acting_client):
        if self.state_id != EditorState.STATE_LOADED:
            return ERRMSG_TODO_BAD_STATE_FUNCTIONALITY

        address = self.get_address(acting_client)
        if address is None:
            return ERRMSG_BUG_UNKNOWN_ADDRESS
        self._set_data_type(acting_client, address, disassembly_data.DATA_TYPE_DATA16)

    def set_datatype_8bit(self, acting_client):
        if self.state_id != EditorState.STATE_LOADED:
            return ERRMSG_TODO_BAD_STATE_FUNCTIONALITY

        address = self.get_address(acting_client)
        if address is None:
            return ERRMSG_BUG_UNKNOWN_ADDRESS
        self._set_data_type(acting_client, address, disassembly_data.DATA_TYPE_DATA08)

    def set_datatype_ascii(self, acting_client):
        if self.state_id != EditorState.STATE_LOADED:
            return ERRMSG_TODO_BAD_STATE_FUNCTIONALITY

        address = self.get_address(acting_client)
        if address is None:
            return ERRMSG_BUG_UNKNOWN_ADDRESS
        self._set_data_type(acting_client, address, disassembly_data.DATA_TYPE_ASCII)

    def _set_data_type(self, acting_client, address, data_type):
        self._prolonged_action(acting_client, "TITLE_DATA_TYPE_CHANGE", "TEXT_GENERIC_PROCESSING", self.disassembly_state.set_data_type_at_address, address, data_type, can_cancel=False)

    def _search_text(self, acting_client, direction, work_state=None):
        # Start after the current line.
        line_number = self.get_line_number(acting_client) + direction
        line_count = self.get_line_count(acting_client)
        result_lower_case = self.last_search_text.lower()
        while line_number >= 0 and line_number < line_count and not work_state.is_cancelled():
            text = self.disassembly_state.get_file_line(line_number, disassembly.LI_LABEL)
            text += " "+ self.disassembly_state.get_file_line(line_number, disassembly.LI_INSTRUCTION)
            text += " "+ self.disassembly_state.get_file_line(line_number, disassembly.LI_OPERANDS)
            if disassembly.DEBUG_ANNOTATE_DISASSEMBLY:
                text += " "+ self.disassembly_state.get_file_line(line_number, disassembly.LI_ANNOTATIONS)

            if result_lower_case in text.lower():
                break
            line_number += direction
            if direction == 1:
                work_state.set_completeness(line_number / float(line_count))
            else:
                work_state.set_completeness((line_count - line_number) / float(line_count))
            work_state.set_description("Line %d" % line_number)
        else:
            return ERRMSG_NO_IDENTIFIABLE_DESTINATION
        # We broke out on a match.
        if not work_state.is_cancelled():
            return line_number

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
            disassembly_state = self._prolonged_action(acting_client, "TITLE_LOADING_PROJECT", "TEXT_GENERIC_LOADING", disassembly.load_project_file, load_file, file_name)
        else:
            new_options = disassembly.get_new_project_options()
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

            disassembly_state = self._prolonged_action(acting_client, "TITLE_LOADING_FILE", "TEXT_GENERIC_LOADING", disassembly.load_file, load_file, new_option_result, file_name)

        # Loading was cancelled.
        if disassembly_state is None:
            self.reset_state(acting_client)
            return

        self.state_id = EditorState.STATE_LOADED
        self.disassembly_state = disassembly_state

        # Register our event dispatching callbacks.
        self.disassembly_state.set_uncertain_reference_modification_func(self._uncertain_reference_modification_callback)
        self.disassembly_state.set_symbol_insert_func(self._symbol_insert_callback)
        self.disassembly_state.set_symbol_delete_func(self._symbol_delete_callback)

        line_count = self.disassembly_state.get_file_line_count()
        if line_count == 0:
            self.reset_state(acting_client)
            return ERRMSG_NOT_SUPPORTED_EXECUTABLE_FILE_FORMAT

        is_saved_project = disassembly_persistence.check_is_project_file(acting_client.get_load_file())
        if is_saved_project:
            # User may have optionally chosen to not save the input file, as part of the project file.
            if not self.disassembly_state.is_segment_data_cached():
                load_options = self.disassembly_state.get_new_project_options()
                # Parameters passed in, to help the client make up it's mind.
                load_options.input_file_filesize = self.disassembly_state.get_file_size()
                load_options.input_file_filename = self.disassembly_state.get_file_name()
                load_options.input_file_checksum = self.disassembly_state.get_file_checksum()
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
                    if input_data_file.tell() != self.disassembly_state.get_file_size():
                        errmsg = ERRMSG_INPUT_FILE_SIZE_DIFFERS
                    elif util.calculate_file_checksum(input_data_file) != self.disassembly_state.get_file_checksum():
                        errmsg = ERRMSG_INPUT_FILE_CHECKSUM_MISMATCH
                    if type(errmsg) in types.StringTypes:
                        self.reset_state(acting_client)
                        return errmsg
                    self.disassembly_state.load_project_file_finalise(input_data_file)

        entrypoint_address = self.disassembly_state.get_entrypoint_address()
        line_number = self.disassembly_state.get_line_number_for_address(entrypoint_address)
        self.set_line_number(acting_client, line_number)

        def _pre_line_change_callback(line0, line_count):
            for client in self.clients:
                client.event_pre_line_change(client is acting_client, line0, line_count)
        self.disassembly_state.set_pre_line_change_func(_pre_line_change_callback)
        def _post_line_change_callback(line0, line_count):
            for client in self.clients:
                client.event_post_line_change(client is acting_client, line0, line_count)
        self.disassembly_state.set_post_line_change_func(_post_line_change_callback)

        for client in self.clients:
            client.event_load_successful(client is acting_client)
        return result

    def save_project(self, acting_client):
        if self.state_id != EditorState.STATE_LOADED:
            return ERRMSG_TODO_BAD_STATE_FUNCTIONALITY

        save_options = self.disassembly_state.get_save_project_options()
        # Install higher-level defined and used option attributes.
        save_options.cache_input_file = self.disassembly_state.get_project_save_count() == 0 or self.disassembly_state.is_project_inputfile_cached()
        # Prompt user if they want to save the source file.
        save_options = acting_client.request_save_project_option_values(save_options)
        # User chose to cancel the save process.
        if save_options is None:
            return
        if save_options.cache_input_file:
            save_options.input_file = acting_client.get_load_file()

        with open(save_options.save_file_path, "wb") as f:
            self.disassembly_state.save_project_file(f, save_options)

    def export_source_code(self, acting_client):
        if self.state_id != EditorState.STATE_LOADED:
            return ERRMSG_TODO_BAD_STATE_FUNCTIONALITY

        line_count = self.disassembly_state.get_file_line_count()

        # Prompt for save file name.
        save_file = acting_client.request_code_save_file()
        if save_file is not None:
            for i in xrange(line_count):
                label_text = self.disassembly_state.get_file_line(i, disassembly.LI_LABEL)
                instruction_text = self.disassembly_state.get_file_line(i, disassembly.LI_INSTRUCTION)
                operands_text = self.disassembly_state.get_file_line(i, disassembly.LI_OPERANDS)
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
