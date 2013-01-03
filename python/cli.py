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
This script is intended to provide a prompt which can be used as an interface
for disassembling, as an alternative to the GUI.
"""

import logging
import os
import sys

logger = logging.getLogger("UI")


PROMPTMSG_ABANDON_WORK = "Abandon work [yN]? "
ERRMSG_UNKNOWN_COMMAND = "unknown command"


def check_user_approves_exit(editor_state):
    if editor_state.state_id == EditorState.STATE_LOADED:
        response = raw_input(PROMPTMSG_ABANDON_WORK).strip.lower()
        if response[0] == "y":
            return True
        return False
    return True


def command_load(editor_state):
    # Ensure there is no work to lose.
    if check_user_approves_exit(editor_state):
        editor_state.reset_state()


def command_quit(editor_state):
    "Quit - Exit the program"
    # Ensure there is no work to lose.
    if check_user_approves_exit(editor_state):
        sys.exit(1)


def command_help(editor_state):
    "Help - List available commands"
    command_mapping = create_command_mapping()
    l = []
    for command_name, function in command_mapping.iteritems():
        l.append("%s\t-\t%s" % (command_name, function.__doc__))
    l.sort()
    for each in l:
        print each


def create_command_mapping():
    d = {}
    d["exit"] = d["x"] = command_quit
    d["quit"] = d["q"] = command_quit
    d["help"] = d["h"] = command_help
    d["load"] = d["l"] = command_load
    return d


def main_loop():
    command_mapping = create_command_mapping()
    editor_state = EditorState()
    while True:
        try:
            cli_text = raw_input("[ - ] ").strip()
        except EOFError:
            # Ctrl-z pressed.
            command_quit(editor_state)

        if cli_text == "":
            logger.debug("TODO: Enter hit, move to next line and print it.")
            continue

        cli_words = cli_text.split(" ", 1)
        cli_command = cli_words[0].lower()

        function = command_mapping.get(cli_command, None)
        if function is None:
            print "%s: %s" % (cli_command, ERRMSG_UNKNOWN_COMMAND)
        else:
            function(editor_state)


if __name__ == "__main__":
    # Set up the logger.
    logging.root.setLevel(logging.DEBUG)
    logging.root.addHandler(logging.StreamHandler())

    main_loop()
