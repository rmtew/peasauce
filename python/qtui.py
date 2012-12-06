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

PySide eccentricities:
- After populating the disassembly view, it is not possible to tell it to select a row
  and scroll to it immediately.  Nothing will happen.  It needs to render first, so in
  order to do this, the paint event needs to be caught and the scrolling and selecting
  done there.
- Changing the font used in the TableView will not change the height of the rows, resulting
  in clipping of text.  The font height needs to be obtained and the row height changed
  accordingly.

http://doc.qt.digia.com/4.6/richtext-html-subset.html
http://qt-project.org/faq/answer/how_can_i_programatically_find_out_which_rows_items_are_visible_in_my_view
http://qt-project.org/wiki/Signals_and_Slots_in_PySide

"""

import collections
import cPickle
import logging
import os
import sys
import time
import traceback

from PySide import QtCore, QtGui

import disassembly
import disassemblylib
import loaderlib


SETTINGS_FILE = "settings.pikl"

APPLICATION_NAME = "PeaSauce"
PROJECT_SUFFIX = "psproj"
PROJECT_FILTER = APPLICATION_NAME +" project (*."+ PROJECT_SUFFIX +")"
SOURCE_CODE_FILTER = "Source code (*.s *.asm)"


logger = logging.getLogger("UI")


class WorkThread(QtCore.QThread):
    result = QtCore.Signal(tuple)

    def __init__(self, parent=None):
        super(WorkThread, self).__init__(parent)

        self.condition = QtCore.QWaitCondition()
        self.mutex = QtCore.QMutex()

        self.quit = False
        self.work_data = None

    def __del__(self):
        self.stop()

    def stop(self):
        self.mutex.lock()
        self.quit = True
        self.work_data = None
        self.condition.wakeOne()
        self.mutex.unlock()
        self.wait()

    def add_work(self, _callable, *_args, **_kwargs):
        self.mutex.lock()
        self.work_data = _callable, _args, _kwargs
 
        if not self.isRunning():
            self.start()
        else:
            self.condition.wakeOne()
        self.mutex.unlock()

    def run(self):
        self.mutex.lock()
        work_data = self.work_data
        self.work_data = None
        self.mutex.unlock()

        while not self.quit:
            try:
                try:
                    result = work_data[0](*work_data[1], **work_data[2])
                except Exception:
                    traceback.print_stack()
                    raise
            except SystemExit:
                traceback.print_exc()
                raise
            work_data = None

            self.mutex.lock()
            self.result.emit(result)
            self.condition.wait(self.mutex)
            work_data = self.work_data
            self.work_data = None
            self.mutex.unlock()

class BaseItemModel(QtCore.QAbstractItemModel):
    _header_font = None

    def __init__(self, columns, parent):
        super(BaseItemModel, self).__init__(parent)

        self._header_data = {}

        self._column_count = len(columns)
        self._column_types = {}
        self._column_alignments = [ None ] * len(columns)
        for i, (column_name, column_type) in enumerate(columns):
            self._column_types[i] = column_type
            self.setHeaderData(i, QtCore.Qt.Horizontal, column_name)
            if column_type is int or column_type is hex:
                self._column_alignments[i] = QtCore.Qt.AlignRight
            else:
                self._column_alignments[i] = QtCore.Qt.AlignLeft

    def _data_ready(self):
        row_count = self.rowCount()
        self.beginInsertRows(QtCore.QModelIndex(), 0, row_count-1)
        self.endInsertRows()

    def _clear_data(self):
        row_count = self.rowCount()
        self.beginRemoveRows(QtCore.QModelIndex(), 0, row_count-1)
        self.endRemoveRows()

    def _set_header_font(self, font):
        self._header_font = font

    def setHeaderData(self, section, orientation, data):
        self._header_data[(section, orientation)] = data

    def columnCount(self, parent):
        return self._column_count

    def headerData(self, section, orientation, role):
        if role == QtCore.Qt.DisplayRole:
            # e.g. section = column_index, orientation = QtCore.Qt.Horizontal
            return self._header_data.get((section, orientation))
        elif role == QtCore.Qt.FontRole:
            return self._header_font

    def data(self, index, role):
        if not index.isValid():
            return None

        if role == QtCore.Qt.TextAlignmentRole:
            column = index.column()
            return self._column_alignments[column]
        elif role != QtCore.Qt.DisplayRole:
            return None

        column, row = index.column(), index.row()
        column_type = self._column_types[column]
        value = self._lookup_cell_value(row, column)
        if column_type is hex:
            value = "$%X" % value
        return value

    def parent(self, index):
        return QtCore.QModelIndex()

    def index(self, row, column, parent):
        if not self.hasIndex(row, column, parent):
            return QtCore.QModelIndex()
        return self.createIndex(row, column)


class DisassemblyItemModel(BaseItemModel):
    def __init__(self, columns, parent):
        self.window = parent

        super(DisassemblyItemModel, self).__init__(columns, parent)

    def rowCount(self, parent=None):
        if self.window.disassembly_data is not None:
            return disassembly.get_line_count(self.window.disassembly_data)
        return 0

    def _lookup_cell_value(self, row, column):
        if self.window.disassembly_data is not None:
            return disassembly.get_file_line(self.window.disassembly_data, row, column)
        return ""


class CustomItemModel(BaseItemModel):
    """ The main reason for this subclass is to give custom column alignment. """
    def __init__(self, columns, parent):
        self._row_data = []

        super(CustomItemModel, self).__init__(columns, parent)

    def _set_row_data(self, row_data, removal_rows=None, addition_rows=None):
        self._row_data = row_data
        if addition_rows:
            self.beginInsertRows(QtCore.QModelIndex(), addition_rows[0], addition_rows[1])
            self.endInsertRows()
        elif removal_rows:
            self.beginRemoveRows(QtCore.QModelIndex(), removal_rows[0], removal_rows[1])
            self.endRemoveRows()

    def _get_row_data(self):
        return self._row_data

    def _lookup_cell_value(self, row, column):
        return self._row_data[row][column]

    def rowCount(self, parent=None):
        return len(self._row_data)


def create_table_model(parent, columns, _class=None):
    if _class is None:
        _class = CustomItemModel
    return _class(columns, parent)

class CustomQTableView(QtGui.QTableView):
    _initial_line_idx = None

    def paintEvent(self, event):
        if self._initial_line_idx is not None:
            self.scrollTo(window.list_model.index(self._initial_line_idx, 0, QtCore.QModelIndex()), QtGui.QAbstractItemView.PositionAtCenter)
            self.selectRow(self._initial_line_idx)
            self._initial_line_idx = None
        super(CustomQTableView, self).paintEvent(event)

    def setFont(self, font):
        result = super(CustomQTableView, self).setFont(font)
        fontMetrics = QtGui.QFontMetrics(font)
        # Whenever the font is changed, resize the row heights to suit.
        self.verticalHeader().setDefaultSectionSize(fontMetrics.lineSpacing() + 2)
        return result

def create_table_widget(model, multiselect=False):
    # Need a custom table view to get selected row.
    table = CustomQTableView()
    table.setModel(model)
    table.setCornerButtonEnabled(False)
    table.setGridStyle(QtCore.Qt.NoPen)
    table.setSortingEnabled(False)
    # Hide row numbers.
    table.verticalHeader().setVisible(False)
    table.verticalHeader().setDefaultSectionSize(14)
    # Allow column resizing, but ensure all space is taken up by columns.
    table.horizontalHeader().setStretchLastSection(True)
    #
    # table.setVerticalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)
    table.setVerticalScrollMode(QtGui.QAbstractItemView.ScrollPerItem)
    # No selection of individual cells, but rather line specific selection.
    table.setSelectionBehavior(QtGui.QAbstractItemView.SelectRows)
    if not multiselect:
        table.setSelectionMode(QtGui.QAbstractItemView.SingleSelection)
    table.setEditTriggers(QtGui.QAbstractItemView.NoEditTriggers)
    return table


STATE_INITIAL   = 0
STATE_LOADING   = 1
STATE_LOADED    = 2

class MainWindow(QtGui.QMainWindow):
    _settings = None
    disassembly_data = None

    loaded_signal = QtCore.Signal(int)
    log_signal = QtCore.Signal(tuple)

    def __init__(self, parent=None):
        super(MainWindow, self).__init__(parent)

        self.thread = WorkThread()

        ## GENERATE THE UI

        self.setWindowTitle(APPLICATION_NAME)

        self.list_model = create_table_model(self, [ ("Address", int), ("Data", str), ("Label", str), ("Instruction", str), ("Operands", str), ("Extra", str) ], _class=DisassemblyItemModel)
        self.list_model._column_alignments[0] = QtCore.Qt.AlignRight
        self.list_table = create_table_widget(self.list_model)

        self.setCentralWidget(self.list_table)

        self.create_menus()
        self.create_dock_windows()
        self.create_shortcuts()

        # Override the default behaviour of using the same font for the table header, that the table itself uses.
        # TODO: Maybe rethink this, as it looks a bit disparate to use different fonts for both.
        default_header_font = QtGui.QApplication.font(self.list_table.horizontalHeader())
        self.list_model._set_header_font(default_header_font)

        ## RESTORE SAVED SETTINGS

        # Restore the user selected font for the table view.
        self.font_info = self._get_setting("font-info")
        if self.font_info is not None:
            font = QtGui.QFont()
            if font.fromString(self.font_info):
                self.list_table.setFont(font)
                self.uncertain_code_references_table.setFont(font)
                self.uncertain_data_references_table.setFont(font)
                self.symbols_table.setFont(font)

        # Restore the layout of the main window and the dock windows.
        window_geometry = self._get_setting("window-geometry")
        if window_geometry is not None:
            self.restoreGeometry(window_geometry)

        window_state = self._get_setting("window-state")
        if window_state is not None:
            self.restoreState(window_state)

        ## INITIALISE APPLICATION STATE

        # State related to having something loaded.
        self.file_path = None
        self.program_state = STATE_INITIAL
        self.view_address_stack = []

    def closeEvent(self, event):
        """ Intercept the window close event and anything which needs to happen first. """
        # If we do not stop the thread, we see the following noise in the console:
        # "QThread: Destroyed while thread is still running"
        self.thread.stop()
        self.thread.wait()

        # Persist window layout.
        self._set_setting("window-geometry", self.saveGeometry())
        self._set_setting("window-state", self.saveState())

        # Let the window close.
        event.accept()

    def create_dock_windows(self):
        dock = QtGui.QDockWidget("Log", self)
        dock.setAllowedAreas(QtCore.Qt.BottomDockWidgetArea)
        self.log_model = create_table_model(self, [ ("Time", str), ("Level", str), ("System", str), ("Description", str), ])
        self.log_table = create_table_widget(self.log_model)
        self.log_table.setAlternatingRowColors(True) # Non-standard
        dock.setWidget(self.log_table)
        self.addDockWidget(QtCore.Qt.BottomDockWidgetArea, dock)
        self.viewMenu.addAction(dock.toggleViewAction())
        dock.setObjectName("dock-log") # State/geometry persistence requirement.

        dock = QtGui.QDockWidget("Symbol List", self)
        dock.setAllowedAreas(QtCore.Qt.LeftDockWidgetArea | QtCore.Qt.RightDockWidgetArea)
        self.symbols_model = create_table_model(self, [ ("Address", hex), ("Symbol", str), ])
        self.symbols_table = create_table_widget(self.symbols_model)
        self.symbols_table.setSortingEnabled(True) # Non-standard
        dock.setWidget(self.symbols_table)
        self.addDockWidget(QtCore.Qt.RightDockWidgetArea, dock)
        self.viewMenu.addAction(dock.toggleViewAction())
        dock.setObjectName("dock-symbols") # State/geometry persistence requirement.
        # Double-click on a row to scroll the view to the address for that row.
        def symbols_doubleClicked(index):
            row_index = index.row()
            new_address = self.symbols_model._lookup_cell_value(row_index, 0)
            self.scroll_to_address(new_address)
        self.symbols_table.doubleClicked.connect(symbols_doubleClicked)

        # The "Uncertain Code References" list is currently hidden by default.
        dock = QtGui.QDockWidget("Uncertain Code References", self)
        dock.setAllowedAreas(QtCore.Qt.LeftDockWidgetArea | QtCore.Qt.RightDockWidgetArea)
        self.uncertain_code_references_model = create_table_model(self, [ ("Address", hex), ("Value", hex), ("Source Code", str), ])
        self.uncertain_code_references_table = create_table_widget(self.uncertain_code_references_model, multiselect=True)
        self.uncertain_code_references_table.setSortingEnabled(True) # Non-standard
        dock.setWidget(self.uncertain_code_references_table)
        self.addDockWidget(QtCore.Qt.RightDockWidgetArea, dock)
        self.viewMenu.addAction(dock.toggleViewAction())
        dock.setObjectName("dock-uncertain-code-references") # State/geometry persistence requirement.
        dock.hide()
        # Double-click on a row to scroll the view to the address for that row.
        def uncertain_code_references_doubleClicked(index):
            row_index = index.row()
            new_address = self.uncertain_code_references_model._lookup_cell_value(row_index, 0)
            self.scroll_to_address(new_address)
        self.uncertain_code_references_table.doubleClicked.connect(uncertain_code_references_doubleClicked)
        def uncertain_code_references_customContextMenuRequested(pos):
            relocate_action = QtGui.QAction("Apply labelisation", self, statusTip="Specify selected rows should use labels in place of their absolute addresses", triggered=lambda*args:None)
            clear_action = QtGui.QAction("Clear labelisation", self, statusTip="Clear any specified rows label usage", triggered=lambda*args:None)
            menu = QtGui.QMenu(self)
            menu.addAction(relocate_action)
            menu.addAction(clear_action)
            menu.exec_(self.uncertain_code_references_table.mapToGlobal(pos))
        self.uncertain_code_references_table.setContextMenuPolicy(QtCore.Qt.CustomContextMenu)
        self.uncertain_code_references_table.customContextMenuRequested.connect(uncertain_code_references_customContextMenuRequested)

        # The "Uncertain Data References" list is currently hidden by default.
        dock = QtGui.QDockWidget("Uncertain Data References", self)
        dock.setAllowedAreas(QtCore.Qt.LeftDockWidgetArea | QtCore.Qt.RightDockWidgetArea)
        self.uncertain_data_references_model = create_table_model(self, [ ("Address", hex), ("Value", hex), ("Source Code", str), ])
        self.uncertain_data_references_table = create_table_widget(self.uncertain_data_references_model, multiselect=True)
        self.uncertain_data_references_table.setSortingEnabled(True) # Non-standard
        dock.setWidget(self.uncertain_data_references_table)
        self.addDockWidget(QtCore.Qt.RightDockWidgetArea, dock)
        self.viewMenu.addAction(dock.toggleViewAction())
        dock.setObjectName("dock-uncertain-data-references") # State/geometry persistence requirement.
        dock.hide()
        # Double-click on a row to scroll the view to the address for that row.
        def uncertain_data_references_doubleClicked(index):
            row_index = index.row()
            new_address = self.uncertain_data_references_model._lookup_cell_value(row_index, 0)
            self.scroll_to_address(new_address)
        self.uncertain_data_references_table.doubleClicked.connect(uncertain_data_references_doubleClicked)
        if False:
            def uncertain_data_references_customContextMenuRequested(pos):
                relocate_action = QtGui.QAction("Apply labelisation", self, statusTip="Specify selected rows should use labels in place of their absolute addresses", triggered=lambda*args:None)
                clear_action = QtGui.QAction("Clear labelisation", self, statusTip="Clear any specified rows label usage", triggered=lambda*args:None)
                menu = QtGui.QMenu(self)
                menu.addAction(relocate_action)
                menu.addAction(clear_action)
                menu.exec_(self.uncertain_data_references_table.mapToGlobal(pos))
            self.uncertain_data_references_table.setContextMenuPolicy(QtCore.Qt.CustomContextMenu)
            self.uncertain_data_references_table.customContextMenuRequested.connect(uncertain_data_references_customContextMenuRequested)

        dock = QtGui.QDockWidget("Segment List", self)
        dock.setAllowedAreas(QtCore.Qt.LeftDockWidgetArea | QtCore.Qt.RightDockWidgetArea)
        self.segments_model = create_table_model(self, [ ("#", int), ("Type", str), ("Memory", int), ("Disk", int), ("Relocs", int), ("Symbols", int), ])
        self.segments_table = create_table_widget(self.segments_model)
        dock.setWidget(self.segments_table)
        self.addDockWidget(QtCore.Qt.RightDockWidgetArea, dock)
        self.viewMenu.addAction(dock.toggleViewAction())
        dock.setObjectName("dock-segments") # State/geometry persistence requirement.

    def create_menus(self):
        self.open_action = QtGui.QAction("&Open file", self, shortcut="Ctrl+O", statusTip="Disassemble a new file", triggered=self.menu_file_open)
        self.save_project_action = QtGui.QAction("&Save project", self, statusTip="Save currently loaded project", triggered=self.interaction_request_save_project)
        self.save_project_as_action = QtGui.QAction("Save project as..", self, statusTip="Save currently loaded project under a specified name", triggered=self.interaction_request_save_project_as)
        self.export_source_action = QtGui.QAction("&Export source", self, statusTip="Export source code", triggered=self.interaction_request_export_source)
        self.quit_action = QtGui.QAction("&Quit", self, shortcut="Ctrl+Q", statusTip="Quit the application", triggered=self.menu_file_quit)

        self.edit_set_datatype_code_action = QtGui.QAction("Set datatype code", self, statusTip="Change data type to code", triggered=self.interaction_set_datatype_code)
        self.edit_set_datatype_32bit_action = QtGui.QAction("Set datatype 32 bit", self, statusTip="Change data type to 32 bit", triggered=self.interaction_set_datatype_32bit)
        self.edit_set_datatype_16bit_action = QtGui.QAction("Set datatype 16 bit", self, statusTip="Change data type to 16 bit", triggered=self.interaction_set_datatype_16bit)
        self.edit_set_datatype_8bit_action = QtGui.QAction("Set datatype 8 bit", self, statusTip="Change data type to 8 bit", triggered=self.interaction_set_datatype_8bit)
        self.edit_set_datatype_ascii_action = QtGui.QAction("Set datatype ascii", self, statusTip="Change data type to ascii", triggered=self.interaction_set_datatype_ascii)

        self.search_find = QtGui.QAction("Find..", self, shortcut="Ctrl+F", statusTip="Find some specific text", triggered=self.menu_search_find)
        self.goto_address_action = QtGui.QAction("Go to address", self, shortcut="Ctrl+G", statusTip="View a specific address", triggered=self.menu_search_goto_address)
        self.goto_previous_data_block_action = QtGui.QAction("Go to previous data", self, shortcut="Ctrl+Shift+D", statusTip="View previous data block", triggered=self.menu_search_goto_previous_data_block)
        self.goto_next_data_block_action = QtGui.QAction("Go to next data", self, shortcut="Ctrl+D", statusTip="View next data block", triggered=self.menu_search_goto_next_data_block)
        self.choose_font_action = QtGui.QAction("Select disassembly font", self, statusTip="Change the font used in the disassembly view", triggered=self.menu_settings_choose_font)

        self.file_menu = self.menuBar().addMenu("&File")
        self.file_menu.addAction(self.open_action)
        self.file_menu.addAction(self.save_project_action)
        self.file_menu.addAction(self.save_project_as_action)
        self.file_menu.addAction(self.export_source_action)
        self.file_menu.addSeparator()
        self.file_menu.addAction(self.quit_action)

        self.edit_menu = self.menuBar().addMenu("&Edit")
        self.edit_menu.addAction(self.edit_set_datatype_code_action)
        self.edit_menu.addAction(self.edit_set_datatype_32bit_action)
        self.edit_menu.addAction(self.edit_set_datatype_16bit_action)
        self.edit_menu.addAction(self.edit_set_datatype_8bit_action)
        self.edit_menu.addAction(self.edit_set_datatype_ascii_action)

        self.search_menu = self.menuBar().addMenu("&Search")
        self.search_menu.addAction(self.search_find)
        self.search_menu.addAction(self.goto_address_action)
        self.search_menu.addAction(self.goto_previous_data_block_action)
        self.search_menu.addAction(self.goto_next_data_block_action)

        self.viewMenu = self.menuBar().addMenu("&View")

        self.settings_menu = self.menuBar().addMenu("Settings")
        self.settings_menu.addAction(self.choose_font_action)

    def create_shortcuts(self):
        ## Main disassembly list table.
        # Place the current location on the browsing stack, and go to the address of the referenced symbol.
        QtGui.QShortcut(QtGui.QKeySequence(QtCore.Qt.Key_Right), self.list_table, self.interaction_view_push_symbol).setContext(QtCore.Qt.WidgetShortcut)
        # Go back in the browsing stack.
        QtGui.QShortcut(QtGui.QKeySequence(QtCore.Qt.Key_Left), self.list_table, self.interaction_view_pop_symbol).setContext(QtCore.Qt.WidgetShortcut)
        # Display referring addresses.
        QtGui.QShortcut(QtGui.QKeySequence(self.tr("Ctrl+Right")), self.list_table, self.interaction_view_referring_symbols).setContext(QtCore.Qt.WidgetShortcut)
        # Edit the name of a label.
        QtGui.QShortcut(QtGui.QKeySequence(QtCore.Qt.Key_Return), self.list_table, self.interaction_rename_symbol).setContext(QtCore.Qt.WidgetShortcut)

        ## Uncertain code references list table.
        QtGui.QShortcut(QtGui.QKeySequence(QtCore.Qt.Key_Return), self.uncertain_code_references_table, self.interaction_uncertain_code_references_view_push_symbol).setContext(QtCore.Qt.WidgetShortcut)
        ## Uncertain data references list table.
        QtGui.QShortcut(QtGui.QKeySequence(QtCore.Qt.Key_Return), self.uncertain_code_references_table, self.interaction_uncertain_data_references_view_push_symbol).setContext(QtCore.Qt.WidgetShortcut)

    def reset_all(self):
        self.reset_ui()
        self.reset_state()

    def reset_ui(self):
        for model in (self.list_model, self.symbols_model, self.uncertain_references_model, self.segments_model, self.log_model):
            model._clear_data()

    def reset_state(self):
        """ Called to clear out all state related to loaded data. """
        self.program_state = STATE_INITIAL
        self.file_path = None
        self.disassembly_data = None

    def menu_file_open(self):
        if self.program_state == STATE_LOADED:
            ret = QtGui.QMessageBox.question(self, "Abandon work?", "You have existing work loaded, do you wish to abandon it?", QtGui.QMessageBox.Ok | QtGui.QMessageBox.Cancel)
            if ret != QtGui.QMessageBox.Ok:
                return
            self.reset_all()
        elif self.program_state != STATE_INITIAL:
            return

        # Request the user select a file.
        options = QtGui.QFileDialog.Options()
        file_path, open_filter = QtGui.QFileDialog.getOpenFileName(self, "Select a file to disassemble", options=options)
        if not len(file_path):
            return

        self.attempt_open_file(file_path)

    def menu_file_quit(self):
        if QtGui.QMessageBox.question(self, "Quit..", "Are you sure you wish to quit?", QtGui.QMessageBox.Ok | QtGui.QMessageBox.Cancel):
            self.close()

    def menu_search_find(self):
        line_idx = self.list_table.currentIndex().row()
        if line_idx == -1:
            line_idx = 0
        text, ok = QtGui.QInputDialog.getText(self, "Find what?", "Text:", QtGui.QLineEdit.Normal, "")
        if ok and text != '':
            pass

    def menu_search_goto_address(self):
        line_idx = self.list_table.currentIndex().row()
        if line_idx == -1:
            line_idx = 0
        address = disassembly.get_address_for_line_number(self.disassembly_data, line_idx)
        # Skip lines which are purely for visual effect.
        if address is None:            
            return
        text, ok = QtGui.QInputDialog.getText(self, "Which address?", "Address:", QtGui.QLineEdit.Normal, "0x%X" % address)
        if ok and text != '':
            new_address = None
            if text.startswith("0x") or text.startswith("$"):
                new_address = int(text, 16)
            else:
                new_address = disassembly.get_address_for_symbol(self.disassembly_data, text)
                if new_address is None:
                    new_address = int(text)
            if new_address is not None:
                self.scroll_to_address(new_address)

    def menu_search_goto_previous_data_block(self):
        line_idx = self.list_table.currentIndex().row()
        if line_idx == -1:
            line_idx = 0
        new_line_idx = disassembly.get_next_data_line_number(self.disassembly_data, line_idx, -1)
        if new_line_idx is None:
            return
        self.list_table.scrollTo(self.list_model.index(new_line_idx, 0, QtCore.QModelIndex()), QtGui.QAbstractItemView.PositionAtCenter)
        self.list_table.selectRow(new_line_idx)

    def menu_search_goto_next_data_block(self):
        line_idx = self.list_table.currentIndex().row()
        if line_idx == -1:
            line_idx = 0
        new_line_idx = disassembly.get_next_data_line_number(self.disassembly_data, line_idx, 1)
        if new_line_idx is None:
            return
        self.list_table.scrollTo(self.list_model.index(new_line_idx, 0, QtCore.QModelIndex()), QtGui.QAbstractItemView.PositionAtCenter)
        self.list_table.selectRow(new_line_idx)

    def menu_settings_choose_font(self):
        font, ok = QtGui.QFontDialog.getFont(self.list_table.font(), self)
        if font and ok:
            self.list_table.setFont(font)
            self.uncertain_code_references_table.setFont(font)
            self.uncertain_data_references_table.setFont(font)
            self._set_setting("font-info", font.toString())

    ## INTERACTION FUNCTIONS

    def interaction_request_save_project(self):
        if self.program_state == STATE_LOADED:
            self.request_and_save_file({ PROJECT_FILTER : "save-file", })

    def interaction_request_save_project_as(self):
        if self.program_state == STATE_LOADED:
            self.request_and_save_file({ PROJECT_FILTER : "save-file", })

    def interaction_request_export_source(self):
        if self.program_state == STATE_LOADED:
            self.request_and_save_file({ SOURCE_CODE_FILTER : "code", })

    def interaction_rename_symbol(self):
        if self.program_state != STATE_LOADED:
            return

        selected_line_numbers = [ index.row() for index in self.list_table.selectionModel().selectedRows() ]
        if not len(selected_line_numbers):
            return
        current_address = disassembly.get_address_for_line_number(self.disassembly_data, selected_line_numbers[0])
        symbol_name = disassembly.get_symbol_for_address(self.disassembly_data, current_address)
        if symbol_name is not None:
            text, ok = QtGui.QInputDialog.getText(self, "Rename symbol", "New name:", QtGui.QLineEdit.Normal, symbol_name)
            if ok and text != symbol_name:
                # TODO: Move this to the platform or architecture level.
                regExp = QtCore.QRegExp("([a-zA-Z_]+[a-zA-Z0-9_\.]*)")
                if regExp.exactMatch(text):
                    new_symbol_name = regExp.cap(1)
                    disassembly.set_symbol_for_address(self.disassembly_data, current_address, new_symbol_name)
                    logger.info("Renamed symbol '%s' to '%s' at address $%06X.", symbol_name, new_symbol_name, current_address)
                else:
                    QtGui.QMessageBox.information(self, "Invalid symbol name", "The symbol name needs to match standard practices.")

    def interaction_uncertain_code_references_view_push_symbol(self):
        if self.program_state != STATE_LOADED:
            return

        # Place current address on the stack.
        selected_line_numbers = [ index.row() for index in self.list_table.selectionModel().selectedRows() ]
        if not len(selected_line_numbers):
            return
        current_address = disassembly.get_address_for_line_number(self.disassembly_data, selected_line_numbers[0])

        # View selected uncertain code reference address.
        row_idx = self.uncertain_code_references_table.currentIndex().row()
        address = self.uncertain_code_references_model._lookup_cell_value(row_idx, 0)
        self.functionality_view_push_address(current_address, address)

    def interaction_uncertain_data_references_view_push_symbol(self):
        if self.program_state != STATE_LOADED:
            return

        # Place current address on the stack.
        selected_line_numbers = [ index.row() for index in self.list_table.selectionModel().selectedRows() ]
        if not len(selected_line_numbers):
            return
        current_address = disassembly.get_address_for_line_number(self.disassembly_data, selected_line_numbers[0])

        # View selected uncertain code reference address.
        row_idx = self.uncertain_data_references_table.currentIndex().row()
        address = self.uncertain_data_references_model._lookup_cell_value(row_idx, 0)
        self.functionality_view_push_address(current_address, address)

    def interaction_view_push_symbol(self):
        if self.program_state != STATE_LOADED:
            return

        # Place current address on the stack.
        selected_line_numbers = [ index.row() for index in self.list_table.selectionModel().selectedRows() ]
        if not len(selected_line_numbers):
            return
        current_address = disassembly.get_address_for_line_number(self.disassembly_data, selected_line_numbers[0])
        # Whether a non-disassembly "readability" line was selected.
        if current_address is None:
            return
        operand_addresses = disassembly.get_referenced_symbol_addresses_for_line_number(self.disassembly_data, selected_line_numbers[0])
        if len(operand_addresses) == 1:
            self.functionality_view_push_address(current_address, operand_addresses[0])
        elif len(operand_addresses) == 2:
            logger.error("Too many addresses, unexpected situation.  Need some selection mechanism.  %s", operand_addresses)
        else:
            logger.warning("No addresses, nothing to go to.")

    def interaction_view_pop_symbol(self):
        if self.program_state != STATE_LOADED:
            logger.error("view pop symbol called with incorrect program state, want: %d, have: %d.", STATE_LOADED, self.program_state)
            return

        if len(self.view_address_stack):
            address = self.view_address_stack.pop()
            line_number = disassembly.get_line_number_for_address(self.disassembly_data, address)
            logger.info("view pop symbol going to address %06X / line number %d %s." % (address, line_number, str(self.view_address_stack)))
            self.list_table.scrollTo(self.list_model.index(line_number, 0, QtCore.QModelIndex()), QtGui.QAbstractItemView.PositionAtCenter)
            self.list_table.selectRow(line_number)
        else:
            logger.error("view pop symbol has empty stack and nowhere to go to.")

    def interaction_view_referring_symbols(self):
        # Place current address on the stack.
        selected_line_numbers = [ index.row() for index in self.list_table.selectionModel().selectedRows() ]
        if not len(selected_line_numbers):
            return
        current_address = disassembly.get_address_for_line_number(self.disassembly_data, selected_line_numbers[0])
        # Whether a non-disassembly "readability" line was selected.
        if current_address is None:
            return
        addresses = disassembly.get_referring_addresses(self.disassembly_data, current_address)
        for address in addresses:
            logger.debug("%06X: Referring address %06X", current_address, address)
        # One address -> goto?
        # Going to an address should push the current.
        if len(addresses) == 0:
            logger.warning("No addresses, nothing to go to.")
        elif len(addresses) == 1:
            self.functionality_view_push_address(current_address, addresses.pop())
        else:
            logger.error("Too many addresses, unexpected situation.  Need some selection mechanism.")

    def interaction_set_datatype_code(self):
        address = self.get_current_address()
        if address is None:
            return
        self.set_data_type(address, disassembly.DATA_TYPE_CODE)

    def interaction_set_datatype_32bit(self):
        address = self.get_current_address()
        if address is None:
            return
        self.set_data_type(address, disassembly.DATA_TYPE_LONGWORD)

    def interaction_set_datatype_16bit(self):
        address = self.get_current_address()
        if address is None:
            return
        self.set_data_type(address, disassembly.DATA_TYPE_WORD)

    def interaction_set_datatype_8bit(self):
        address = self.get_current_address()
        if address is None:
            return
        self.set_data_type(address, disassembly.DATA_TYPE_BYTE)

    def interaction_set_datatype_ascii(self):
        address = self.get_current_address()
        if address is None:
            return
        self.set_data_type(address, disassembly.DATA_TYPE_ASCII)

    ## MISCELLANEIA

    def scroll_to_address(self, new_address):
        new_line_idx = disassembly.get_line_number_for_address(self.disassembly_data, new_address)
        logger.debug("goto line: %d address: $%X", new_line_idx, new_address)
        self.list_table.scrollTo(self.list_model.index(new_line_idx, 0, QtCore.QModelIndex()), QtGui.QAbstractItemView.PositionAtCenter)
        self.list_table.selectRow(new_line_idx)

    def functionality_view_push_address(self, current_address, address):
        self.view_address_stack.append(current_address)
        next_line_number = disassembly.get_line_number_for_address(self.disassembly_data, address)
        if next_line_number is not None:
            self.list_table.scrollTo(self.list_model.index(next_line_number, 0, QtCore.QModelIndex()), QtGui.QAbstractItemView.PositionAtCenter)
            self.list_table.selectRow(next_line_number)
            logger.info("view push symbol going to address %06X / line number %d." % (address, next_line_number))
        else:
            logger.error("view push symbol for address %06X unable to resolve line number." % address)

    def set_data_type(self, address, data_type):
        disassembly.set_data_type_at_address(self.disassembly_data, address, data_type)

    def get_current_address(self):
        # Place current address on the stack.
        selected_line_numbers = [ index.row() for index in self.list_table.selectionModel().selectedRows() ]
        if not len(selected_line_numbers):
            logger.debug("Failed to get current address, no selected lines.")
            return
        current_address = disassembly.get_address_for_line_number(self.disassembly_data, selected_line_numbers[0])
        # Whether a non-disassembly "readability" line was selected.
        if current_address is None:
            logger.debug("Failed to get current address, no address for line.")
            return
        return current_address

    def _set_setting(self, setting_name, setting_value):
        self._settings[setting_name] = setting_value
        with open(SETTINGS_FILE, "wb") as f:
            cPickle.dump(self._settings, f)

    def _get_setting(self, setting_name, default_value=None):
        if self._settings is None:
            if os.path.exists(SETTINGS_FILE):
                with open(SETTINGS_FILE, "rb") as f:
                    self._settings = cPickle.load(f)
            else:
                self._settings = {}
        return self._settings.get(setting_name, default_value)

        filter_strings = ";;".join(filters.iterkeys())
        """
                # options = QtGui.QFileDialog.Options()
                # file_path, filter_text = QtGui.QFileDialog.getOpenFileName(self, caption="Load from...", filter=filter_strings, options=options)
                # if not len(file_path):
                    # return
                # if filters[filter_text] == "load-file":
                    # self.load_work(file_path)
                # self.request_and_load_file({ "Load file (*.wrk)" : "load-file", })
        """
    def attempt_open_file(self, file_path):
        # Cover the case of a command-line startup with a current directory file name.
        if os.path.dirname(file_path) == "":
            file_path = os.path.join(os.getcwd(), file_path)

        # An attempt will be made to load an existing file.
        self.program_state = STATE_LOADING
        self.file_path = file_path

        # Start the disassembly on the worker thread.
        self.thread.result.connect(self.attempt_display_file)
        if file_path.endswith("."+ PROJECT_SUFFIX):
            # We display the load project dialog after loading.
            self.thread.add_work(disassembly.load_project, file_path)
            progress_title = "Load Project"
            progress_text = "Loading project"
        else:
            new_options = disassembly.get_new_project_options(self.disassembly_data)
            result = NewProjectDialog(new_options, file_path, self).exec_()
            if result != QtGui.QDialog.Accepted:
                self.reset_state()
                return
            self.thread.add_work(disassembly.load_file, file_path, new_options)
            progress_title = "New Project"
            progress_text = "Creating initial project"

        # Display a modal dialog.
        progressDialog = self.progressDialog = QtGui.QProgressDialog(self)
        progressDialog.setCancelButtonText("&Cancel")
        progressDialog.setWindowTitle(progress_title)
        progressDialog.setAutoClose(True)
        progressDialog.setWindowModality(QtCore.Qt.WindowModal)
        progressDialog.setRange(0, 100)
        progressDialog.setMinimumDuration(0)
        progressDialog.setValue(20)
        progressDialog.setLabelText(progress_text +"..")

        # Register to hear if the cancel button is pressed.
        def canceled():
            # Clean up our use of the worker thread.
            self.thread.result.disconnect(self.attempt_display_file)
            self.reset_state()
            self.progressDialog = None
        progressDialog.canceled.connect(canceled)
        
        # Wait until cancel or the work is complete.
        t0 = time.time()
        progressDialog.show()
        while self.progressDialog is not None:
            QtGui.qApp.processEvents()
        logger.debug("Loading file finished in %0.1fs", time.time() - t0)

    def attempt_display_file(self, result):
        # This isn't really good enough, as long loading files may send mixed signals.
        if self.file_path is None:
            return

        self.program_state = STATE_LOADED

        # Close the progress dialog without canceling it.
        self.progressDialog.setValue(100)
        self.progressDialog = None

        # Clean up our use of the worker thread.
        self.thread.result.disconnect(self.attempt_display_file)

        self.disassembly_data, line_count = result

        if line_count == 0:
            self.reset_state()
            QtGui.QMessageBox.information(self, "Unable to open file", "The file does not appear to be a supported executable file format.")
            return

        ## Last minute steps before display of loaded data.
        if self.file_path.endswith("."+ PROJECT_SUFFIX):
            load_options = disassembly.get_load_project_options(self.disassembly_data)
            ##if disassembly.is_project_inputfile_cached(self.disassembly_data):
            ##    disassembly.validate_cached_file_size(self.disassembly_data, load_options)
            ##    disassembly.validate_cached_file_checksum(self.disassembly_data, load_options)
            # If the input file is cached, it's data should have been cached by the project loading.
            if not disassembly.is_segment_data_cached(self.disassembly_data):
                result = LoadProjectDialog(load_options, self.file_path, self).exec_()
                if result != QtGui.QDialog.Accepted:
                    self.reset_state()
                    return

                disassembly.cache_segment_data(self.disassembly_data, load_options.loader_file_path)

        ## Proceed with display of loaded data.
        entrypoint_address = disassembly.get_entrypoint_address(self.disassembly_data)
        new_line_idx = disassembly.get_line_number_for_address(self.disassembly_data, entrypoint_address)

        self.list_table._initial_line_idx = new_line_idx

        ## Populate the disassembly view with the loaded data.
        model = self.list_model
        model._data_ready()

        ## SEGMENTS
 
        if False:
            # Populate the segments dockable window with the loaded segment information.
            model = self.segments_model
            loader_segments = self.disassembly_data.loader_segments
            for segment_id in range(len(loader_segments)):
                model.insertRows(model.rowCount(), 1, QtCore.QModelIndex())
                
                if loaderlib.is_segment_type_code(loader_segments, segment_id):
                    segment_type = "code"
                elif loaderlib.is_segment_type_data(loader_segments, segment_id):
                    segment_type = "data"
                elif loaderlib.is_segment_type_bss(loader_segments, segment_id):
                    segment_type = "bss"
                length = loaderlib.get_segment_length(loader_segments, segment_id)
                data_length = loaderlib.get_segment_data_length(loader_segments, segment_id)
                if loaderlib.get_segment_data_file_offset(loader_segments, segment_id) == -1:
                    data_length = "-"
                reloc_count = "-"#len(self.disassembly_data.file_info.relocations_by_segment_id[segment_id])
                symbol_count = "-"#len(self.disassembly_data.file_info.symbols_by_segment_id[segment_id])

                model.setData(model.index(segment_id, 0, QtCore.QModelIndex()), segment_id)
                for i, column_value in enumerate((segment_type, length, data_length, reloc_count, symbol_count)):
                    model.setData(model.index(segment_id, i+1, QtCore.QModelIndex()), column_value)

            self.segments_table.resizeColumnsToContents()
            self.segments_table.horizontalHeader().setStretchLastSection(True)

        ## SYMBOLS

        # Register for further symbol events (only add for now).
        disassembly.set_symbol_insert_func(self.disassembly_data, self.disassembly_symbol_added)

        row_data = self.disassembly_data.symbols_by_address.items()
        self.symbols_model._set_row_data(row_data, addition_rows=(0, len(row_data)-1))
        self.symbols_table.resizeColumnsToContents()
        self.symbols_table.horizontalHeader().setStretchLastSection(True)

        ## UNCERTAIN REFERENCES

        disassembly.set_uncertain_reference_modification_func(self.disassembly_data, self.disassembly_uncertain_reference_modification)

        results = disassembly.get_uncertain_code_references(self.disassembly_data)
        self.uncertain_code_references_model._set_row_data(results, addition_rows=(0, len(results)-1))
        self.uncertain_code_references_table.resizeColumnsToContents()
        self.uncertain_code_references_table.horizontalHeader().setStretchLastSection(True)

        results = disassembly.get_uncertain_data_references(self.disassembly_data)
        self.uncertain_data_references_model._set_row_data(results, addition_rows=(0, len(results)-1))
        self.uncertain_data_references_table.resizeColumnsToContents()
        self.uncertain_data_references_table.horizontalHeader().setStretchLastSection(True)

        ## DONE LOADING ##

        self.loaded_signal.emit(0)

    # TODO: FIX
    def disassembly_symbol_added(self, symbol_address, symbol_label):
        model = self.symbols_model
        model.insertRows(model.rowCount(), 1, QtCore.QModelIndex())
        self._add_symbol_to_model(symbol_address, symbol_label)

        self.symbols_table.resizeColumnsToContents()
        self.symbols_table.horizontalHeader().setStretchLastSection(True)

    def disassembly_uncertain_reference_modification(self, data_type_from, data_type_to, address, length):
        if data_type_from == disassembly.DATA_TYPE_CODE:
            from_model = self.uncertain_code_references_model
        else:
            from_model = self.uncertain_data_references_model
        from_row_data = from_model._get_row_data()
        removal_idx0 = None
        removal_idxN = len(from_row_data)
        for i, entry in enumerate(from_row_data):
            if entry[0] < address:
                continue
            if entry[0] >= address + length:
                removal_idxN = i
                break
            if removal_idx0 is None:
                removal_idx0 = i
        if removal_idx0 is None:
            removal_idx0 = 0
        from_row_data[removal_idx0:removal_idxN] = []
        from_model._set_row_data(from_row_data, removal_rows=(removal_idx0, removal_idxN-1))

        addition_rows = disassembly.get_uncertain_references_by_address(self.disassembly_data, address)
        if len(addition_rows):
            if data_type_to == disassembly.DATA_TYPE_CODE:
                to_model = self.uncertain_code_references_model
            else:
                to_model = self.uncertain_data_references_model
            to_row_data = to_model._get_row_data()

            from_idx = 0
            to_idx = 0
            insert_ranges = []
            while to_idx < len(to_row_data) and from_idx < len(addition_rows):
                insert_value = addition_rows[from_idx]
                if insert_value < to_row_data[to_idx]:
                    to_row_data.insert(to_idx, insert_value)
                    if len(insert_ranges) and insert_ranges[-1][1] == to_idx-1:
                        insert_ranges[-1][1] = to_idx
                    else:
                        if len(insert_ranges):
                            to_model._set_row_data(to_row_data, addition_rows=(insert_ranges[-1][0], insert_ranges[-1][1]))
                        insert_ranges.append([ to_idx, to_idx ])
                    from_idx += 1
                to_idx += 1
            if len(insert_ranges):
                to_model._set_row_data(to_row_data, addition_rows=(insert_ranges[-1][0], insert_ranges[-1][1]))

    # TODO: FIX
    def _add_symbol_to_model(self, symbol_address, symbol_label, row_index=None):
        model = self.symbols_model
        if row_index is None:
            row_index = model.rowCount()-1
        model.setData(model.index(row_index, 0, QtCore.QModelIndex()), symbol_label)
        model.setData(model.index(row_index, 1, QtCore.QModelIndex()), "%X" % symbol_address)

    def request_and_save_file(self, filters):
        filter_strings = ";;".join(filters.iterkeys())

        options = QtGui.QFileDialog.Options()
        file_path, filter_text = QtGui.QFileDialog.getSaveFileName(self, caption="Save to...", filter=filter_strings, options=options)
        if not len(file_path):
            return
        if filters[filter_text] == "code":
            self.save_disassembled_source(file_path)
        elif filters[filter_text] == "save-file":
            save_options = disassembly.get_save_project_options(self.disassembly_data)
            # Lightweight validation of whether there's the input file is cached.
            if disassembly.is_project_inputfile_cached(self.disassembly_data):
                if self.disassembly_data.savefile_path is None or not disassembly.validate_cached_file_size(self.disassembly_data, save_options):
                    result = SaveProjectDialog(save_options, file_path, self).exec_()
                    if result != QtGui.QDialog.Accepted:
                        return
            self.save_work(file_path, save_options)

    def save_disassembled_source(self, file_path):
        line_count = disassembly.get_line_count(self.disassembly_data)

        # Display a modal dialog.
        progressDialog = self.progressDialog = QtGui.QProgressDialog(self)
        progressDialog.setCancelButtonText("&Cancel")
        progressDialog.setRange(0, line_count)
        progressDialog.setWindowTitle("Saving source code")
        progressDialog.setMinimumDuration(1)
        progressDialog.setAutoClose(True)
        progressDialog.setWindowModality(QtCore.Qt.WindowModal)

        # Initialise the dialog status.
        progressDialog.setLabelText("Writing source code..")

        # Note: Writing to cStringIO is not faster than writing directly to file.
        with open(file_path, "w") as f:
            for i in xrange(line_count):
                progressDialog.setValue(i)

                label_text = disassembly.get_file_line(self.disassembly_data, i, disassembly.LI_LABEL)
                instruction_text = disassembly.get_file_line(self.disassembly_data, i, disassembly.LI_INSTRUCTION)
                operands_text = disassembly.get_file_line(self.disassembly_data, i, disassembly.LI_OPERANDS)
                if label_text:
                    f.write(label_text)
                f.write("\t")
                f.write(instruction_text)
                if operands_text:
                    f.write("\t")
                    f.write(operands_text)
                f.write("\n")

                QtGui.qApp.processEvents()
                if progressDialog.wasCanceled():
                    # If the process was aborted, delete the partially exported file.
                    f.close()
                    os.remove(file_path)
                    break
            else:
                progressDialog.setValue(line_count)        

    def load_work(self, file_path):
        disassembly.load_project(file_path)

    def save_work(self, file_path, save_options):
        disassembly.save_project(file_path, self.disassembly_data, save_options)

## Option dialogs.

class ClickableLabel(QtGui.QLabel):
    clicked = QtCore.Signal()

    def mousePressEvent(self, event):
        if event.button() == QtCore.Qt.LeftButton:
            self.clicked.emit()

def _make_inputdata_options(dialog, group_title, keep_input_data=True):
    """
    This uses two workarounds resulting in a second-rate solution:
    - Radio button text does not wrap, so the workaround is that no text is
      given to the radio buttons.  Instead the text is displayed using labels.
    - Labels cannot be clicked on to get the related radio buttons to depress.
      Instead, a custom label class is created that responds to mouse press
      events.  This leaves gaps in the clickable areas.
    """
    dialog.inputdata_do_radio = QtGui.QRadioButton()
    dialog.inputdata_dont_radio = QtGui.QRadioButton()
    inputdata_do_short_label = ClickableLabel("Saved work SHOULD contain source/input file data.")
    inputdata_do_short_label.clicked.connect(dialog.inputdata_do_radio.click)
    inputdata_do_long_label = ClickableLabel("When you load your saved work, you WILL NOT need to provide the source/input file.")
    inputdata_do_long_label.clicked.connect(dialog.inputdata_do_radio.click)
    inputdata_dont_short_label = ClickableLabel("Saved work SHOULD NOT contain source/input file data.")
    inputdata_dont_short_label.clicked.connect(dialog.inputdata_dont_radio.click)
    inputdata_dont_long_label = ClickableLabel("When you load your saved work, you WILL need to provide the source/input file.")
    inputdata_dont_long_label.clicked.connect(dialog.inputdata_dont_radio.click)
    if keep_input_data:
        dialog.inputdata_do_radio.setChecked(True)
    else:
        dialog.inputdata_dont_radio.setChecked(True)
    inputdata_groupbox = QtGui.QGroupBox(group_title)
    inputdata_layout = QtGui.QGridLayout()
    inputdata_layout.addWidget(dialog.inputdata_do_radio, 0, 0)
    inputdata_layout.addWidget(inputdata_do_short_label, 0, 1)
    inputdata_layout.addWidget(inputdata_do_long_label, 1, 1)
    inputdata_layout.addWidget(dialog.inputdata_dont_radio, 2, 0)
    inputdata_layout.addWidget(inputdata_dont_short_label, 2, 1)
    inputdata_layout.addWidget(inputdata_dont_long_label, 3, 1)
    inputdata_groupbox.setLayout(inputdata_layout)
    return inputdata_groupbox

def _set_default_font(widget):
    font = QtGui.QFont()
    if not font.fromString("Arial,8,-1,5,50,0,0,0,0,0"):
        font = QtGui.QApplication.font()
    widget.setFont(font)


class LoadProjectDialog(QtGui.QDialog):
    def __init__(self, load_options, file_path, parent=None):
        super(LoadProjectDialog, self).__init__(parent)

        self.load_options = load_options
        _set_default_font(self)

        self.setWindowTitle("Load Project")
        self.setWindowModality(QtCore.Qt.WindowModal)

        ## Information layout.
        problem_groupbox = QtGui.QGroupBox("Problem")
        problem_label1 = QtGui.QLabel("This project does not include the original data.")
        problem_label2 = QtGui.QLabel("Perhaps whomever created the project opted to exclude it.")
        problem_label3 = QtGui.QLabel("Perhaps Peasource's cached copy was somehow deleted.")
        problem_label4 = QtGui.QLabel("In any case, you need to locate and provide it.")
        problem_layout = QtGui.QVBoxLayout()
        problem_layout.addWidget(problem_label1)
        problem_layout.addSpacing(10)
        problem_layout.addWidget(problem_label2)
        problem_layout.addWidget(problem_label3)
        problem_layout.addSpacing(10)
        problem_layout.addWidget(problem_label4)
        problem_groupbox.setLayout(problem_layout)

        original_filesize = self.parentWidget().disassembly_data.file_size
        original_filename = self.parentWidget().disassembly_data.file_name
        original_checksum = self.parentWidget().disassembly_data.file_checksum

        filespec_groupbox = QtGui.QGroupBox("Original file")
        filespec_layout = QtGui.QGridLayout()
        filename_key_label = QtGui.QLabel("Name:")
        filename_value_label = QtGui.QLabel(original_filename)
        filesize_key_label = QtGui.QLabel("Size:")
        filesize_value_label = QtGui.QLabel("%d bytes" % original_filesize)
        filechecksum_key_label = QtGui.QLabel("Checksum:")
        filechecksum_value_label = QtGui.QLabel("".join("%X" % ord(c) for c in original_checksum))
        filespec_layout.addWidget(filename_key_label, 0, 0, 1, 1)
        filespec_layout.addWidget(filename_value_label, 0, 1, 1, 19)
        filespec_layout.addWidget(filesize_key_label, 1, 0, 1, 1)
        filespec_layout.addWidget(filesize_value_label, 1, 1, 1, 19)
        filespec_layout.addWidget(filechecksum_key_label, 2, 0, 1, 1)
        filespec_layout.addWidget(filechecksum_value_label, 2, 1, 1, 19)
        filespec_groupbox.setLayout(filespec_layout)

        filelocation_groupbox = QtGui.QGroupBox("File location")
        filelocation_layout = QtGui.QVBoxLayout()
        path_layout = QtGui.QHBoxLayout()
        path_lineedit = QtGui.QLineEdit()
        path_button = QtGui.QToolButton(self) # A button that stays minimally sized.
        path_button.setText("...")
        path_button.setToolButtonStyle(QtCore.Qt.ToolButtonTextOnly)
        path_layout.addWidget(path_lineedit)
        path_layout.addWidget(path_button)
        valid_size_checkbox = QtGui.QCheckBox("Size", self)
        valid_size_checkbox.setChecked(False)
        valid_size_checkbox.setEnabled(False)
        valid_checksum_checkbox = QtGui.QCheckBox("Checksum", self)
        valid_checksum_checkbox.setChecked(False)
        valid_checksum_checkbox.setEnabled(False)
        validity_layout = QtGui.QHBoxLayout()
        validity_layout.addWidget(QtGui.QLabel("Validity:"))
        validity_layout.addWidget(valid_size_checkbox, alignment=QtCore.Qt.AlignLeft)
        validity_layout.addWidget(valid_checksum_checkbox, alignment=QtCore.Qt.AlignLeft)
        filelocation_layout.addLayout(path_layout)
        filelocation_layout.addLayout(validity_layout)
        filelocation_groupbox.setLayout(filelocation_layout)

        # The algorithm used to enable the load button is:
        # - Wait 2 seconds after the last text change, or when return pressed.
        # - Check if given path is a file of the correct size.
        # - 

        self.validation_attempt = 0
        self.validation_attempt_text = None
        self.validation_key = None

        def validate_file_path(validation_attempt, file_path):
            # Maybe the user kept typing, if so they're not finished.
            if self.validation_attempt != validation_attempt:
                return
            path_lineedit.setEnabled(False)
            if os.path.isfile(file_path):
                if os.path.getsize(file_path) == original_filesize:
                    valid_size_checkbox.setChecked(True)
                file_checksum = disassembly.calculate_file_checksum(file_path)
                if file_checksum == original_checksum:
                    valid_checksum_checkbox.setChecked(True)
                if valid_size_checkbox.isChecked() and valid_checksum_checkbox.isChecked():
                    load_button.setEnabled(True)
                    self.valid_file_path = file_path
            path_lineedit.setEnabled(True)

        def _reset_widgets():
            self.valid_file_path = None
            valid_size_checkbox.setChecked(False)
            valid_checksum_checkbox.setChecked(False)
            load_button.setEnabled(False)
        def on_path_lineedit_textChanged(new_text):
            if self.validation_attempt_text != new_text:
                _reset_widgets()
                self.validation_attempt_text = new_text
                self.validation_attempt += 1 
                QtCore.QTimer.singleShot(2000, lambda n=self.validation_attempt: validate_file_path(n, new_text))
        def on_path_lineedit_returnPressed():
            if self.validation_attempt_text != path_lineedit.text():
                _reset_widgets()
                self.validation_attempt_text = path_lineedit.text()
                self.validation_attempt += 1 
                validate_file_path(self.validation_attempt, path_lineedit.text())

        path_lineedit.textChanged.connect(on_path_lineedit_textChanged)
        path_lineedit.returnPressed.connect(on_path_lineedit_returnPressed)

        def on_path_button_clicked():
            options = QtGui.QFileDialog.Options()
            file_path, open_filter = QtGui.QFileDialog.getOpenFileName(self, "Locate original file..", options=options)
            if not len(file_path):
                return
            path_lineedit.setText(file_path)
        path_button.clicked.connect(on_path_button_clicked)

        ## Buttons layout.
        load_button = QtGui.QPushButton("Load")
        load_button.setEnabled(False)
        cancel_button = QtGui.QPushButton("Cancel")
        self.connect(load_button, QtCore.SIGNAL("clicked()"), self, QtCore.SLOT("accept()"))
        self.connect(cancel_button, QtCore.SIGNAL("clicked()"), self, QtCore.SLOT("reject()"))

        buttons_layout = QtGui.QHBoxLayout()
        buttons_layout.addWidget(load_button, QtCore.Qt.AlignRight)
        buttons_layout.addWidget(cancel_button, QtCore.Qt.AlignRight)

        ## Outer layout.
        information_layout = QtGui.QVBoxLayout()
        information_layout.addWidget(problem_groupbox)
        information_layout.addWidget(filespec_groupbox)
        information_layout.addWidget(filelocation_groupbox)
        information_layout.addLayout(buttons_layout)
        self.setLayout(information_layout)

    def accept(self):
        self.load_options.loader_file_path = self.valid_file_path
        return super(LoadProjectDialog, self).accept()

class SaveProjectDialog(QtGui.QDialog):
    def __init__(self, save_options, file_path, parent=None):
        super(SaveProjectDialog, self).__init__(parent)

        self.save_options = save_options
        _set_default_font(self)

        self.setWindowTitle("Save Project")
        self.setWindowModality(QtCore.Qt.WindowModal)

        ## File options layout.
        inputdata_groupbox = _make_inputdata_options(self, "File Options", save_options.cache_input_data)

        ## Buttons layout.
        save_button = QtGui.QPushButton("Save")
        cancel_button = QtGui.QPushButton("Cancel")
        self.connect(save_button, QtCore.SIGNAL("clicked()"), self, QtCore.SLOT("accept()"))
        self.connect(cancel_button, QtCore.SIGNAL("clicked()"), self, QtCore.SLOT("reject()"))

        buttons_layout = QtGui.QHBoxLayout()
        buttons_layout.addWidget(save_button, QtCore.Qt.AlignRight)
        buttons_layout.addWidget(cancel_button, QtCore.Qt.AlignRight)

        ## Outer layout.
        outer_vertical_layout = QtGui.QVBoxLayout()
        outer_vertical_layout.addWidget(inputdata_groupbox)
        outer_vertical_layout.addLayout(buttons_layout)
        self.setLayout(outer_vertical_layout)

    def accept(self):
        self.save_options.cache_input_data = self.inputdata_do_radio.isChecked()
        return super(SaveProjectDialog, self).accept()


class NewProjectDialog(QtGui.QDialog):
    def __init__(self, new_options, file_path, parent=None):
        super(NewProjectDialog, self).__init__(parent)

        _set_default_font(self)

        self.new_options = new_options
        dir_path, file_name = os.path.split(file_path)

        # Attempt to identify the file type.
        identification_result = loaderlib.identify_file(file_path)
        if identification_result is not None:
            file_info, file_details = identification_result
            new_options.is_binary_file = False
        else:
            file_info, file_details = None, {}
            new_options.is_binary_file = True

        ## Options / information layouts.
        # File groupbox.
        file_name_key_label = QtGui.QLabel("Name:")
        file_name_value_label = QtGui.QLabel(file_name)
        file_size_key_label = QtGui.QLabel("Size:")
        file_size_value_label = QtGui.QLabel("%d bytes" % os.path.getsize(file_path))
        file_hline = QtGui.QFrame()
        file_hline.setFrameShape(QtGui.QFrame.HLine)
        file_hline.setFrameShadow(QtGui.QFrame.Sunken)
        file_hline.setLineWidth(0)
        file_hline.setMidLineWidth(1)

        file_type_key_label = QtGui.QLabel("Type:")
        file_type_value_label = QtGui.QLabel(file_details.get("filetype", "-"))
        file_arch_key_label = QtGui.QLabel("Architecture:")
        self.file_arch_value_combobox = file_arch_value_combobox = QtGui.QComboBox(self)
        if new_options.is_binary_file:
            # List all supported processor options, for user to choose.
            for arch_name in disassemblylib.get_arch_names():
                file_arch_value_combobox.addItem(arch_name)
            file_arch_value_combobox.setEnabled(True)
        else:
            # Fixed processor defined by the file format.
            file_arch_value_combobox.addItem(file_details["processor"])
            file_arch_value_combobox.setEnabled(False)

        information_groupbox = QtGui.QGroupBox("File Information")
        information_layout = QtGui.QGridLayout()
        information_layout.addWidget(file_name_key_label, 0, 0)
        information_layout.addWidget(file_name_value_label, 0, 1)
        information_layout.addWidget(file_size_key_label, 1, 0)
        information_layout.addWidget(file_size_value_label, 1, 1)
        information_layout.addWidget(file_hline, 2, 0, 1, 2)
        information_layout.addWidget(file_type_key_label, 3, 0)
        information_layout.addWidget(file_type_value_label, 3, 1)
        information_layout.addWidget(file_arch_key_label, 4, 0)
        information_layout.addWidget(file_arch_value_combobox, 4, 1)
        information_groupbox.setLayout(information_layout)

        # Processing groupbox.
        load_address = 0
        entrypoint_address = 0
        if not new_options.is_binary_file:
            load_address = loaderlib.get_load_address(file_info)
            entrypoint_address = loaderlib.get_entrypoint_address(file_info)

        processing_loadaddress_key_label = QtGui.QLabel("Load address:")
        self.processing_loadaddress_value_textedit = processing_loadaddress_value_textedit = QtGui.QLineEdit("0x%X" % load_address)
        processing_loadaddress_value_textedit.setEnabled(new_options.is_binary_file)
        processing_entryaddress_key_label = QtGui.QLabel("Entrypoint address:")
        self.processing_entryaddress_value_textedit = processing_entryaddress_value_textedit = QtGui.QLineEdit("0x%X" % entrypoint_address)
        processing_entryaddress_value_textedit.setEnabled(new_options.is_binary_file)
        processing_hline1 = QtGui.QFrame()
        processing_hline1.setFrameShape(QtGui.QFrame.HLine)
        processing_hline1.setFrameShadow(QtGui.QFrame.Sunken)
        processing_hline1.setLineWidth(0)
        processing_hline1.setMidLineWidth(0)

        processing_groupbox = QtGui.QGroupBox("Processing")
        processing_layout = QtGui.QGridLayout()
        processing_layout.addWidget(processing_loadaddress_key_label, 0, 0)
        processing_layout.addWidget(processing_loadaddress_value_textedit, 0, 1)
        processing_layout.addWidget(processing_entryaddress_key_label, 1, 0)
        processing_layout.addWidget(processing_entryaddress_value_textedit, 1, 1)
        fill_row_count = information_layout.rowCount() - processing_layout.rowCount() # Need grid spacing to be equal.
        processing_layout.addWidget(processing_hline1, 2, 0, fill_row_count, 2)
        processing_groupbox.setLayout(processing_layout)

        # Gather together complete options layout.
        options_layout = QtGui.QHBoxLayout()
        options_layout.addWidget(information_groupbox)
        options_layout.addWidget(processing_groupbox)

        ## Buttons layout.
        create_button = QtGui.QPushButton("Create")
        cancel_button = QtGui.QPushButton("Cancel")
        create_button.clicked.connect(self.accept)
        cancel_button.clicked.connect(self.reject)

        buttons_layout = QtGui.QHBoxLayout()
        buttons_layout.addWidget(create_button, QtCore.Qt.AlignRight)
        buttons_layout.addWidget(cancel_button, QtCore.Qt.AlignRight)

        ## Outer layout.
        outer_vertical_layout = QtGui.QVBoxLayout()
        outer_vertical_layout.addLayout(options_layout)
        outer_vertical_layout.addLayout(buttons_layout)
        self.setLayout(outer_vertical_layout)

        self.setWindowTitle("New Project")
        self.setWindowModality(QtCore.Qt.WindowModal)

    def accept(self):
        if self.new_options.is_binary_file:
            self.new_options.dis_name = self.file_arch_value_combobox.currentText()
            self.new_options.loader_load_address = to_int(self.processing_loadaddress_value_textedit.text())
            self.new_options.loader_entrypoint_address = to_int(self.processing_entryaddress_value_textedit.text())
        return super(NewProjectDialog, self).accept()

# TODO: int(, 16) chokes on $ prefix.  Done elsewhere too.
def to_int(value):
    if value.startswith("0x") or value.startswith("$"):
        return int(value, 16)
    return int(value)


## General script startup code.

def _initialise_logging(window):
    def _ui_thread_logging(t):
        global window
        timestamp, level_name, logger_name, message = t
        table = window.log_table
        model = window.log_model
        row_index = model.rowCount()
        model.insertRows(row_index, 1, QtCore.QModelIndex())
        model.setData(model.index(row_index, 0, QtCore.QModelIndex()), time.ctime(timestamp))
        model.setData(model.index(row_index, 1, QtCore.QModelIndex()), level_name)
        model.setData(model.index(row_index, 2, QtCore.QModelIndex()), logger_name)
        model.setData(model.index(row_index, 3, QtCore.QModelIndex()), message)
        #table.resizeColumnsToContents()
        #table.horizontalHeader().setStretchLastSection(True)
        #table.scrollTo(model.index(row_index, 0, QtCore.QModelIndex()), QtGui.QAbstractItemView.PositionAtBottom)
        table.scrollToBottom()

    window.log_signal.connect(_ui_thread_logging)

    class LogHandler(logging.Handler):
        def emit(self, record):
            msg = self.format(record)
            # These logging events may be happening in the worker thread, ensure they only get displayed in the UI thread.
            print msg
            return
            window.log_signal.emit((record.created, record.levelname, record.name, msg))

    handler = LogHandler()
    handler.setLevel(logging.DEBUG)

    root_logger = logging.root
    root_logger.setLevel(logging.DEBUG)
    root_logger.addHandler(handler)
    root_logger.debug("Logging redirected to standard output as inter-thread logging is slow.")


if __name__ == '__main__':
    app = QtGui.QApplication(sys.argv)

    window = MainWindow()
    # The window needs to be created so we can connect to its signal.
    _initialise_logging(window)
    window.show()

    # Do our own argument handling.  The documentation for QApplication says that
    # QT will remove it's own arguments from argc, but this does not apply when
    # it is used in PySide.
    def _arg_file_load():
        if len(sys.argv) > 1:
            s = sys.argv[-1]
            if s[0] != "-":
                def _received_loaded_signal(var):
                    window.close()
                # If we want to exit once the loading is complete (e.g. profiling).
                #window.loaded_signal.connect(_received_loaded_signal)

                t = QtCore.QTimer()
                t.setSingleShot(True)
                # If a reference is not kept for the timer, it will die before it does its job.  So hence "t is not None".
                t.timeout.connect(lambda: window.attempt_open_file(s) or t is not None)
                t.start(50)
    _arg_file_load()

    sys.exit(app.exec_())

