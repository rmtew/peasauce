# Notes

Longer form notes on the various future work items listed in the `README.md`
file are located here.  Numbering of entries is simply the order in which
entries were added.

## Future Work

### Short Term Tasks

#### Bugs

#### Functionality

##### 0002: Disassembly: Jump table discovery / processing

Sample: NEURO
* Search for "JSR ARi" (not so easy as it matches ARid16)
  * 0x1E6E, 0xA4B6, 0xA4EC, 0xACB8, 0xAE26

Implementing this would drive operand introspection, and dataflow analysis.  A related use of operand introspection is the ability to follow references in operand values, or to alow the user to edit operands (replace values with symbols, change numeric base).

##### 0003: UI: Find text options

Currently, text searching just obtains a string to match from the user, and then goes from line to line looking for that string in a case-insensitive manner within the line.  Each line is simply all the columns joined together.  One obvious limitation is searching for something like `jsr ari` will also match `jsr arid16`, with no ability to prevent it.

##### 0004: Disassembly: Symbol library and the ability to apply symbol names to values

IN PROGRESS: The design for this needs to be fleshed out.

What is the least possible work involved in adding a symbol library?

Stream of consciousness thoughts:

* Automatically named, based on extraction from source material?
* Import from simple peasauce format.
* Tool to extract to peasauce format.
* Start with simple sample file (json?).

amitools imports fds, that would be a simple start.

1. cd local_binaries
2. git clone git@github.com:cnvogelg/amitools.git
3. have code look for `local_binaries\amitools`
4. if present, add `local_binaries\amitools` to path.
5. then can use it to read fd files and so forth.

What to do:
1. Finish disassembly.py code to identify library calls.
  1. May need to backtrack through caller references, or forward through calls, to find address register value.
  1. Will need to store/index library handle addresses.
	1. Special case for open library calls.
	  * Know library name register and backtrack for the address.
	  * Automatically rename the address symbol.
		* Flag that it is automatically renamed.
	  * Automatically inject the symbol value.
		* Will need to keep a persisted ProgramState entry. e.g. value_symbols[address] = { "D16": "fd:exec_lib:*"}

#### Technical Debt

### Medium Term Tasks

#### Functionality

##### 0001: Persistence: Change history

At the time of writing, persisting project state simply dumps the data structures to disk and they can be reloaded at a later time, allowing the user to continue altering the project state over time.

The idea behind this task is that instead of persisting the current project state, only persist the history of changes that have been made since the project was created. When a project is loaded, the history would be applied from start to finish resulting in the current project state being temporary and casually discarded.  This is not to say that the state couldn't be cached to speed up loading, but it would be advantageous that the state could be deleted and rebuilt.

The core advantages of this change would be:

* Natural support for undo & redo, both of which are necessary for a more comfortable user friendly experience at some point.
* Making it less of a burden to maintain the backwards compatible saved project state.

The bonus and yet to be proven advantages of this change would be:

* The user would be able to undo changes right back to the project creation, or anywhere in between and then save it out as a different project.
* The user would be able to view the changes as a revision history, where each save might be considered a changeset, and each interim change a commit.  Or thereabouts.
* The user might be able to give the project to another user, and then eventually when additional support for it is added, merge the changes made by both.
* Execution of actions should be automatic, interactive (user confirms all), or conditional (user confirms flagged actions, rest are automatic).

PROBLEM: What if changes in the load process change things so that the revision history is being applied to something too different from what it originally applied to?

### Long Term Tasks

#### Functionality

#### Pie In The Sky
