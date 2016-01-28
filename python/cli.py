"""
    Peasauce - interactive disassembler
    Copyright (C) 2012-2016 Richard Tew
    Licensed using the MIT license.
"""

"""
This script is intended to provide a prompt which can be used as an interface
for disassembling, as an alternative to the GUI.

TODO:
- enter an address to go to it while editing (may clash with enter line number).
- enter a symbol name to go to it (requires tighter integration).
"""

import logging
import os
import sys
import types

import toolapi

logger = logging.getLogger("UI")


PROMPTMSG_ABANDON_WORK = "Abandon work [yN]? "
ERRMSG_UNKNOWN_COMMAND = "unknown command"


def check_user_approves_exit(toolapiob):
    if toolapiob.editor_state.in_loaded_state():
        response = raw_input(PROMPTMSG_ABANDON_WORK).strip().lower()
        if response[0] == "y":
            return True
        return False
    return True


def command_load(toolapiob, arg_string):
    # Ensure there is no work to lose.
    if not check_user_approves_exit(toolapiob):
        return

    result = toolapiob.load_file(arg_string)
    # Cancelled?
    if result is None:
        print "Usage: load <file path>"
        return
    # Error message?
    if type(result) in types.StringTypes:
        print "ERROR: unable to open file -", result
        return

    # This isn't really good enough, as long loading files may conflict with cancellation and subsequent load attempts.
    if not toolapiob.editor_state.in_loaded_state():
        return

    print "success"

def command_quit(toolapiob, arg_string):
    "Quit - Exit the program"
    # Ensure there is no work to lose.
    if check_user_approves_exit(toolapiob):
        sys.exit(1)


def command_help(toolapiob, arg_string):
    "Help - List available commands"
    command_mapping = create_command_mapping()
    l = []
    for command_name, function in command_mapping.iteritems():
        l.append("%s\t-\t%s" % (command_name, function.__doc__))
    l.sort()
    for each in l:
        print each

def default_command_no_file_loaded(toolapiob, arg_string):
    print "ERROR: no file loaded."

def editor_command_go_to_line(toolapiob, arg_string):
    line_number = int(arg_string)
    if line_number < 0 or toolapiob.editor_state.get_line_count() <= line_number:
        return
    toolapiob.editor_state.set_line_number(line_number)
    print_line(toolapiob, line_number)

def editor_command_print_current_line(toolapiob, arg_string):
    line_number = toolapiob.editor_state.get_line_number()
    print_line(toolapiob, line_number)

def editor_command_print_next_line(toolapiob, arg_string):
    line_number = toolapiob.editor_state.get_line_number() + 1
    if line_number < 0 or line_number == toolapiob.editor_state.get_line_count():
        return
    toolapiob.editor_state.set_line_number(line_number)
    print_line(toolapiob, line_number)

def print_line(toolapiob, line_number):
    row = toolapiob.editor_state.get_row_for_line_number(line_number)
    row_widths = [ 10, 10, 10, 10, 25 ]
    line = ""
    for i, s in enumerate(row):
        width = row_widths[i]
        if len(s) <= width:
            line += s
            line += " " * (width - len(s))
        else:
            line += s[:width-2]
            line += ".."
        line += " "
    print line

def create_command_mapping(toolapiob):
    d = {}
    d["exit"] = d["x"] = command_quit
    d["quit"] = d["q"] = command_quit
    d["help"] = d["h"] = command_help
    d["load"] = d["l"] = command_load

    if toolapiob.editor_state.in_loaded_state():
        d["<number>"] = editor_command_go_to_line
        d["p"] = editor_command_print_current_line
        d[""] = editor_command_print_next_line
    else:
        d["<number>"] = default_command_no_file_loaded
        d["p"] = default_command_no_file_loaded
        d[""] = lambda: None
    return d


def main_loop():
    toolapiob = toolapi.ToolAPI()
    while True:
        prompt = "] "
        if toolapiob.editor_state.in_loaded_state():
            prompt = ": "
        try:
            cli_text = raw_input(prompt).strip()
        except EOFError:
            # Ctrl-z pressed.
            command_quit(toolapiob)

        cli_number = None
        if cli_text == "":
            cli_command = cli_args = ""
        else:
            idx = cli_text.find(" ")
            if idx == -1:
                try:
                    cli_number = int(cli_text)
                    cli_command = "<number>"
                    cli_args = cli_text
                except ValueError:
                    pass

                if cli_number is None:
                    cli_command = cli_text
                    cli_args = ""
            else:
                cli_command = cli_text[:idx].lower()
                cli_args = cli_text[idx+1:].strip()

        command_mapping = create_command_mapping(toolapiob)
        function = command_mapping.get(cli_command, None)
        if function is None:
            print "%s: %s" % (cli_command, ERRMSG_UNKNOWN_COMMAND)
        else:
            function(toolapiob, cli_args)


if __name__ == "__main__":
    # Set up the logger.
    logging.root.setLevel(logging.DEBUG)
    logging.root.addHandler(logging.StreamHandler())

    main_loop()
