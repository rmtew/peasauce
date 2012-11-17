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

http://doc.qt.digia.com/4.6/richtext-html-subset.html
http://qt-project.org/faq/answer/how_can_i_programatically_find_out_which_rows_items_are_visible_in_my_view
http://qt-project.org/wiki/Signals_and_Slots_in_PySide

"""


import cPickle
import logging
import os
import sys
import time
import traceback

from PySide import QtCore, QtGui

import disassembly
import loaderlib


SETTINGS_FILE = "settings.pikl"


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
            result = work_data[0](*work_data[1], **work_data[2])
            work_data = None

            self.mutex.lock()
            self.result.emit(result)
            self.condition.wait(self.mutex)
            work_data = self.work_data
            self.work_data = None
            self.mutex.unlock()


class DisassemblyItemModel(QtCore.QAbstractItemModel):
    _header_font = None

    def __init__(self, rows, columns, parent):
        self.column_count = columns
        self.window = parent

        super(DisassemblyItemModel, self).__init__(parent)

        self.column_alignments = [ QtCore.Qt.AlignLeft ] * self.column_count
        self.header_data = {}

    def set_header_font(self, font):
        self._header_font = font

    def _data_ready(self):
        row_count = self.rowCount()
        self.beginInsertRows(QtCore.QModelIndex(), 0, row_count-1)
        self.endInsertRows()

    def _clear_data(self):
        row_count = self.rowCount()
        self.beginRemoveRows(QtCore.QModelIndex(), 0, row_count-1)
        self.endRemoveRows()

    def rowCount(self, parent=None):
        if self.window.disassembly_data is not None:
            return disassembly.get_line_count(self.window.disassembly_data)
        return 0

    def columnCount(self, parent):
        return self.column_count

    def setHeaderData(self, section, orientation, data):
        self.header_data[(section, orientation)] = data

    def headerData(self, section, orientation, role):
        if role == QtCore.Qt.DisplayRole:
            # e.g. section = column_index, orientation = QtCore.Qt.Horizontal
            return self.header_data.get((section, orientation))
        elif role == QtCore.Qt.FontRole:
            return self._header_font

    def data(self, index, role):
        if not index.isValid():
            return None

        if role == QtCore.Qt.TextAlignmentRole:
            column = index.column()
            return self.column_alignments[column]
        elif role != QtCore.Qt.DisplayRole:
            return None

        column, row = index.column(), index.row()
        if self.window.disassembly_data is not None:
            return disassembly.get_file_line(self.window.disassembly_data, row, column)
        return ""

    def parent(self, index):
        return QtCore.QModelIndex()

    def index(self, row, column, parent):
        if not self.hasIndex(row, column, parent):
            if row == 10739:
                print "ZZZ"
            return QtCore.QModelIndex()
        if row == 10739:
            print "YYY"
        return self.createIndex(row, column)


class CustomItemModel(QtGui.QStandardItemModel):
    """ The main reason for this subclass is to give custom column alignment. """
    def __init__(self, row_count, column_count, parent):
        super(CustomItemModel, self).__init__(row_count, column_count, parent)

        self.column_alignments = [ QtCore.Qt.AlignLeft ] * self.columnCount(QtCore.QModelIndex())

    def _clear_data(self):
        # .clear() also clears the header of columns, this is sufficient.
        self.removeRows(0, self.rowCount(), QtCore.QModelIndex())

    def data(self, index, role=QtCore.Qt.DisplayRole):
        column, row = index.column(), index.row()
        if role == QtCore.Qt.TextAlignmentRole:
            return self.column_alignments[column]
        return super(CustomItemModel, self).data(index, role)


def create_table_model(parent, columns, _class=None):
    if _class is None:
        _class = CustomItemModel
    model = _class(0, len(columns), parent)
    for i, (column_name, column_type) in enumerate(columns):
        model.setHeaderData(i, QtCore.Qt.Horizontal, column_name)
        if column_type is int:
            model.column_alignments[i] = QtCore.Qt.AlignRight
        else:
            model.column_alignments[i] = QtCore.Qt.AlignLeft
    return model


def create_table_widget(model):
    # Need a custom table view to get selected row.
    table = QtGui.QTableView()
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

        self.setWindowTitle("PeaSauce")

        self.list_model = create_table_model(self, [ ("Address", int), ("Data", str), ("Label", str), ("Instruction", str), ("Operands", str), ("Extra", str) ], _class=DisassemblyItemModel)
        self.list_model.column_alignments[0] = QtCore.Qt.AlignRight
        self.list_table = create_table_widget(self.list_model)

        self.setCentralWidget(self.list_table)

        self.create_menus()
        self.create_dock_windows()
        self.create_shortcuts()

        # Override the default behaviour of using the same font for the table header, that the table itself uses.
        # TODO: Maybe rethink this, as it looks a bit disparate to use different fonts for both.
        default_header_font = QtGui.QApplication.font(self.list_table.horizontalHeader())
        self.list_model.set_header_font(default_header_font)

        ## RESTORE SAVED SETTINGS

        # Restore the user selected font for the table view.
        self.font_info = self._get_setting("font-info")
        if self.font_info is not None:
            font = QtGui.QFont()
            if font.fromString(self.font_info):
                self.list_table.setFont(font)

        # Restore the layout of the main window and the dock windows.
        window_geometry = self._get_setting("window-geometry")
        if window_geometry is not None:
            self.restoreGeometry(window_geometry)

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

        dock = QtGui.QDockWidget("Symbols", self)
        dock.setAllowedAreas(QtCore.Qt.LeftDockWidgetArea | QtCore.Qt.RightDockWidgetArea)
        self.symbols_model = create_table_model(self, [ ("Symbol", str), ("Address", int), ])
        self.symbols_table = create_table_widget(self.symbols_model)
        self.symbols_table.setSortingEnabled(True) # Non-standard
        dock.setWidget(self.symbols_table)
        self.addDockWidget(QtCore.Qt.RightDockWidgetArea, dock)
        self.viewMenu.addAction(dock.toggleViewAction())
        dock.setObjectName("dock-symbols") # State/geometry persistence requirement.

        dock = QtGui.QDockWidget("Segments", self)
        dock.setAllowedAreas(QtCore.Qt.LeftDockWidgetArea | QtCore.Qt.RightDockWidgetArea)
        self.segments_model = create_table_model(self, [ ("#", int), ("Type", str), ("Memory", int), ("Disk", int), ("Relocs", int), ("Symbols", int), ])
        self.segments_table = create_table_widget(self.segments_model)
        dock.setWidget(self.segments_table)
        self.addDockWidget(QtCore.Qt.RightDockWidgetArea, dock)
        self.viewMenu.addAction(dock.toggleViewAction())
        dock.setObjectName("dock-segments") # State/geometry persistence requirement.

    def create_menus(self):
        self.open_action = QtGui.QAction("&Open file", self, shortcut="Ctrl+O", statusTip="Disassemble a new file", triggered=self.menu_file_open)
        self.load_work_action = QtGui.QAction("&Load work", self, statusTip="Load previous work", triggered=self.interaction_request_load_work)
        self.save_work_action = QtGui.QAction("&Save work", self, statusTip="Save current work", triggered=self.interaction_request_save_work)
        self.export_source_action = QtGui.QAction("&Export source", self, statusTip="Export source code", triggered=self.interaction_request_export_source)
        self.quit_action = QtGui.QAction("&Quit", self, shortcut="Ctrl+Q", statusTip="Quit the application", triggered=self.menu_file_quit)
        self.goto_address_action = QtGui.QAction("Go to address", self, shortcut="Ctrl+G", statusTip="View a specific address", triggered=self.menu_search_goto_address)
        self.choose_font_action = QtGui.QAction("Select disassembly font", self, statusTip="Change the font used in the disassembly view", triggered=self.menu_settings_choose_font)

        self.file_menu = self.menuBar().addMenu("&File")
        self.file_menu.addAction(self.open_action)
        self.file_menu.addAction(self.load_work_action)
        self.file_menu.addAction(self.save_work_action)
        self.file_menu.addAction(self.export_source_action)
        self.file_menu.addSeparator()
        self.file_menu.addAction(self.quit_action)

        self.search_menu = self.menuBar().addMenu("&Search")
        self.search_menu.addAction(self.goto_address_action)

        self.viewMenu = self.menuBar().addMenu("&View")

        self.settings_menu = self.menuBar().addMenu("Settings")
        self.settings_menu.addAction(self.choose_font_action)

    def create_shortcuts(self):
        # Place the current location on the browsing stack, and go to the address of the referenced symbol.
        QtGui.QShortcut(QtGui.QKeySequence(QtCore.Qt.Key_Right), self.list_table, self.interaction_view_push_symbol)
        # Go back in the browsing stack.
        QtGui.QShortcut(QtGui.QKeySequence(QtCore.Qt.Key_Left), self.list_table, self.interaction_view_pop_symbol)
        # Edit the name of a label.
        QtGui.QShortcut(QtGui.QKeySequence(QtCore.Qt.Key_Return), self.list_table, self.interaction_rename_symbol)

    def reset_all(self):
        self.reset_ui()
        self.reset_state()

    def reset_ui(self):
        for model in (self.list_model, self.symbols_model, self.segments_model, self.log_model):
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

    def menu_search_goto_address(self):
        line_idx = self.list_table.currentIndex().row()
        if line_idx == -1:
            line_idx = 0
        address = disassembly.get_address_for_line_number(self.disassembly_data, line_idx)
        text, ok = QtGui.QInputDialog.getText(self, "Which address?", "Address:", QtGui.QLineEdit.Normal, "0x%X" % address)
        if ok and text != '':
            new_address = None
            if text.startswith("0x") or text.startswith("$"):
                new_address = int(text, 16)
            else:
                new_address = int(text)
            if new_address is not None:
                new_line_idx = disassembly.get_line_number_for_address(self.disassembly_data, new_address)
                self.list_table.selectRow(new_line_idx)

    def menu_settings_choose_font(self):
        # TODO: Could identify the current font and pass it in to be initial selection.
        font, ok = QtGui.QFontDialog.getFont(QtGui.QFont("Courier New", 10), self)
        if font and ok:
            self.list_table.setFont(font)
            self._set_setting("font-info", font.toString())

    ## INTERACTION FUNCTIONS

    def interaction_request_load_work(self):
        if self.program_state == STATE_LOADED:
            self.request_and_load_file({ "Load file (*.wrk)" : "load-file", })

    def interaction_request_save_work(self):
        if self.program_state == STATE_LOADED:
            self.request_and_save_file({ "Save file (*.wrk)" : "save-file", })

    def interaction_request_export_source(self):
        if self.program_state == STATE_LOADED:
            self.request_and_save_file({ "Source code (*.s *.asm)" : "code", })

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

    def interaction_view_push_symbol(self):
        if self.program_state != STATE_LOADED:
            return

        # Place current address on the stack.
        selected_line_numbers = [ index.row() for index in self.list_table.selectionModel().selectedRows() ]
        if not len(selected_line_numbers):
            return
        current_address = disassembly.get_address_for_line_number(self.disassembly_data, selected_line_numbers[0])
        operand_addresses = disassembly.get_referenced_symbol_addresses_for_line_number(self.disassembly_data, selected_line_numbers[0])
        if len(operand_addresses) == 1:
            self.view_address_stack.append(current_address)
            # ...
            address = operand_addresses[0]
            next_line_number = disassembly.get_line_number_for_address(self.disassembly_data, address)
            self.list_table.selectRow(next_line_number)
            logger.info("view push symbol going to address %06X / line number %d." % (address, next_line_number))
        elif len(operand_addresses) == 2:
            logger.error("Too many addresses, unexpected situation.")
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
            self.list_table.selectRow(line_number)
        else:
            logger.error("view pop symbol has empty stack and nowhere to go to.")

    ## MISCELLANEIA

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

    def attempt_open_file(self, file_path):
        # An attempt will be made to load an existing file.
        self.program_state = STATE_LOADING
        self.file_path = file_path

        # Display a modal dialog.
        progressDialog = self.progressDialog = QtGui.QProgressDialog(self)
        progressDialog.setCancelButtonText("&Cancel")
        progressDialog.setRange(0, 100)
        progressDialog.setWindowTitle("Loading a File")
        progressDialog.setMinimumDuration(1)
        progressDialog.setAutoClose(True)
        progressDialog.setWindowModality(QtCore.Qt.WindowModal)

        # Start the disassembly on the worker thread.
        self.thread.result.connect(self.attempt_display_file)
        self.thread.add_work(disassembly.load_file, file_path)

        # Initialise the dialog status.
        progressDialog.setValue(20)
        progressDialog.setLabelText("Disassembling..")

        # Register to hear if the cancel button is pressed.
        def canceled():
            # Clean up our use of the worker thread.
            self.thread.result.disconnect(self.attempt_display_file)
            self.reset_state()
            self.progressDialog = None
        progressDialog.canceled.connect(canceled)

        # Wait until cancel or the work is complete.
        while self.progressDialog is not None:
            QtGui.qApp.processEvents()

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

        ## Populate the disassembly view with the loaded data.
        model = self.list_model
        model._data_ready()

        ## SEGMENTS
 
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
            reloc_count = len(self.disassembly_data.file_info.relocations_by_segment_id[segment_id])
            symbol_count = len(self.disassembly_data.file_info.symbols_by_segment_id[segment_id])

            model.setData(model.index(segment_id, 0, QtCore.QModelIndex()), segment_id)
            for i, column_value in enumerate((segment_type, length, data_length, reloc_count, symbol_count)):
                model.setData(model.index(segment_id, i+1, QtCore.QModelIndex()), column_value)

        self.segments_table.resizeColumnsToContents()
        self.segments_table.horizontalHeader().setStretchLastSection(True)

        ## SYMBOLS

        # Register for further symbol events (only add for now).
        disassembly.set_symbol_insert_func(self.disassembly_data, self.disassembly_symbol_added)

        model = self.symbols_model
        model.insertRows(model.rowCount(), len(self.disassembly_data.symbols_by_address), QtCore.QModelIndex())
        row_index = 0
        for symbol_address, symbol_label in self.disassembly_data.symbols_by_address.iteritems():
            self._add_symbol_to_model(symbol_address, symbol_label, row_index)
            row_index += 1

        self.symbols_table.resizeColumnsToContents()
        self.symbols_table.horizontalHeader().setStretchLastSection(True)

        self.loaded_signal.emit(0)

    def disassembly_symbol_added(self, symbol_address, symbol_label):
        model = self.symbols_model
        model.insertRows(model.rowCount(), 1, QtCore.QModelIndex())
        self._add_symbol_to_model(symbol_address, symbol_label)

        self.symbols_table.resizeColumnsToContents()
        self.symbols_table.horizontalHeader().setStretchLastSection(True)

    def _add_symbol_to_model(self, symbol_address, symbol_label, row_index=None):
        model = self.symbols_model
        if row_index is None:
            row_index = model.rowCount()-1
        model.setData(model.index(row_index, 0, QtCore.QModelIndex()), symbol_label)
        model.setData(model.index(row_index, 1, QtCore.QModelIndex()), "%X" % symbol_address)

    def request_and_load_file(self, filters):
        filter_strings = ";;".join(filters.iterkeys())

        options = QtGui.QFileDialog.Options()
        file_path, filter_text = QtGui.QFileDialog.getOpenFileName(self, caption="Load from...", filter=filter_strings, options=options)
        if filters[filter_text] == "load-file":
            self.load_work(file_path)

    def request_and_save_file(self, filters):
        filter_strings = ";;".join(filters.iterkeys())

        options = QtGui.QFileDialog.Options()
        file_path, filter_text = QtGui.QFileDialog.getSaveFileName(self, caption="Save to...", filter=filter_strings, options=options)
        if filters[filter_text] == "code":
            self.save_disassembled_source(file_path)
        elif filters[filter_text] == "save-file":
            self.save_work(file_path)

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

    def save_work(self, file_path):
        pass

    def load_work(self, file_path):
        pass


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
            window.log_signal.emit((record.created, record.levelname, record.name, msg))

    handler = LogHandler()
    handler.setLevel(logging.DEBUG)

    root_logger = logging.root
    root_logger.setLevel(logging.DEBUG)
    root_logger.addHandler(handler)


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

