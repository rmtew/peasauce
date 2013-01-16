"""
    Peasauce - interactive disassembler
    Copyright (C) 2012, 2013  Richard Tew

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
This provides an API to allow direct use of the disassembly logic without
involving a GUI.
"""

import os
import types

import editor_state


ERRMSG_FILE_DOES_NOT_EXIST = "File does not exist."


class ToolEditorClient(editor_state.ClientAPI):
    # __init__(self, owner)

    # External responsibility.
    _binary_parameters = None
    _goto_address_value = None

    def reset_state(self):
        self.owner_ref().reset_state()

    def request_load_file(self):
        # Offers the user a chance to load a file.
        # Returns None if user aborted.
        # Returns the file object on success.
        file_path = self.owner_ref().get_file_path()
        if file_path is None or not os.path.isfile(file_path):
            return ERRMSG_FILE_DOES_NOT_EXIST
        return open(file_path, "rb"), file_path

    def get_load_file(self):
        file_path = self.owner_ref().get_file_path()
        return open(file_path, "rb")

    def request_new_project_option_values(self, new_options):
        if self._binary_parameters is not None:
            new_options.dis_name, new_options.loader_load_address, new_options.loader_entrypoint_offset = self._binary_parameters
        return new_options

    def request_load_project_option_values(self, load_options):
        load_options.loader_file_path = self.owner_ref().get_input_file_path()
        return load_options

    def request_address(self, address):
        return self._goto_address_value

    # These can be ignored, as we have no GUI.
    def event_tick(self, active_client): pass
    def event_prolonged_action(self, active_client, title_msg_id, description_msg_id, can_cancel, step_count, abort_callback): pass
    def event_prolonged_action_update(self, active_client, description_msg_id, step_number): pass
    def event_prolonged_action_complete(self, active_client): pass
    def event_load_successful(self, active_client): pass


class ToolAPI(object):
    editor_state = None

    file_path = None
    input_file_path = None

    def __init__(self, editor_state_ob=None):
        self.editor_client = ToolEditorClient(self)
        if editor_state_ob is None:
            editor_state_ob = editor_state.EditorState()
        editor_state_ob.register_client(self.editor_client)
        self.editor_state = editor_state_ob

    def reset_state(self):
        """ Called by the editor client. """
        if self.editor_state is None or self.editor_state.in_initial_state(self.editor_client):
            return
        # This is set in initial state, before loading.
        self.file_path = None
        self.input_file_path = None

    def get_file_path(self):
        """ Called by the editor client. """
        return self.file_path

    def get_input_file_path(self):
        """ Called by the editor client. """
        return self.input_file_path

    def load_binary_file(self, file_path, dis_name, load_address, entrypoint_offset):
        # Not ideal, but works for now.
        self.editor_client._binary_parameters = dis_name, load_address, entrypoint_offset
        try:
            return self.load_file(file_path)
        finally:
            self.editor_client._binary_parameters = None

    def load_file(self, file_path, input_file_path=None):
        self.file_path = file_path
        self.input_file_path = input_file_path
        result = self.editor_state.load_file(self.editor_client)
        if result is None or type(result) in types.StringTypes:
            self.editor_state.reset_state(self.editor_client)
        return result

    def _get_address(self):
        return self.editor_state.get_address(self.editor_client)

    def _goto_address(self, address):
        self.editor_client._goto_address_value = address
        try:
            return self.editor_state.goto_address(self.editor_client)
        finally:
            self.editor_client._goto_address_value = None

    def get_data_type_for_address(self, address):
        return self.editor_state.get_data_type_for_address(self.editor_client, address)

    def set_datatype(self, address, type_name):
        self._goto_address(address)
        if type_name == "code":
            return self.editor_state.set_datatype_code(self.editor_client)
        elif type_name == "32bit":
            return self.editor_state.set_datatype_32bit(self.editor_client)
        elif type_name == "16bit":
            return self.editor_state.set_datatype_16bit(self.editor_client)
        elif type_name == "8bit":
            return self.editor_state.set_datatype_8bit(self.editor_client)
        elif type_name == "ascii":
            return self.editor_state.set_datatype_ascii(self.editor_client)

    def get_uncertain_code_references(self):
        return self.editor_state.get_uncertain_code_references(self.editor_client)

    def get_uncertain_data_references(self):
        return self.editor_state.get_uncertain_data_references(self.editor_client)

    def get_source_code_for_address(self, address):
        return self.editor_state.get_source_code_for_address(self.editor_client, address)

    def get_referring_addresses_for_address(self, address):
        return self.editor_state.get_referring_addresses_for_address(self.editor_client, address)
