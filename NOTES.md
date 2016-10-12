# Notes

Longer form notes on the various future work items listed in the `README.md`
file are located here.  Numbering of entries is simply the order in which
entries were added.

## Future Work

### Short Term Tasks

#### Bugs

#### Functionality

#### Technical Debt

### Medium Term Tasks

#### Functionality

##### 0001: Persistence: Change History

At the time of writing, persisting project state simply dumps the data structures to disk and they can be reloaded at a later time, allowing the user to continue altering the project state over time.

The idea behind this task is that instead of persisting the current project state, only persist the history of changes that have been made since the project was created. When a project is loaded, the history would be applied from start to finish resulting in the current project state being temporary and casually discarded.  This is not to say that the state couldn't be cached to speed up loading, but it would be advantageous that the state could be deleted and rebuilt.

The core advantages of this change would be:

* Natural support for undo & redo, both of which are necessary for a more comfortable user friendly experience at some point.
* Making it less of a burden to maintain the backwards compatible saved project state.

The bonus and yet to be proven advantages of this change would be:

* The user would be able to undo changes right back to the project creation, or anywhere in between and then save it out as a different project.
* The user would be able to view the changes as a revision history, where each save might be considered a changeset, and each interim change a commit.  Or thereabouts.
* The user might be able to give the project to another user, and then eventually when additional support for it is added, merge the changes made by both.

### Long Term Tasks

#### Functionality

#### Pie In The Sky
