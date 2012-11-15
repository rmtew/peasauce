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

from PySide import QtCore, QtGui

import run
import archlib


SETTINGS_FILE = "settings.pikl"


class WorkThread(QtCore.QThread):
    result = QtCore.Signal(int)

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


class CustomItemModel2(QtCore.QAbstractItemModel):
    _header_font = None

    def __init__(self, rows, columns, parent):
        self.column_count = columns

        super(CustomItemModel2, self).__init__(parent)

        self.column_alignments = [ QtCore.Qt.AlignLeft ] * self.column_count
        self.header_data = {}

    def set_header_font(self, font):
        self._header_font = font

    def refresh(self, parent):
        self.beginInsertRows(parent, 0, self.rowCount(parent))
        self.endInsertRows()

    def rowCount(self, parent):
        return run.get_line_count()

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
        return run.get_file_line(row, column)

    def parent(self, index):
        return QtCore.QModelIndex()

    def index(self, row, column, parent):
        if not self.hasIndex(row, column, parent):
            return QtCore.QModelIndex()

        return self.createIndex(row, column)

    if False:
        def flags(self, index):
            if not index.isValid():
                return QtCore.Qt.NoItemFlags

            return QtCore.Qt.ItemIsEnabled | QtCore.Qt.ItemIsSelectable


class CustomItemModel(QtGui.QStandardItemModel):
    def __init__(self, *args, **kwargs):
        super(CustomItemModel, self).__init__(*args, **kwargs)

        self.column_alignments = [ QtCore.Qt.AlignLeft ] * self.columnCount(QtCore.QModelIndex())

    def data(self, index, role=QtCore.Qt.DisplayRole):
        column, row = index.column(), index.row()
        if role == QtCore.Qt.TextAlignmentRole:
            return self.column_alignments[column]
        return super(CustomItemModel, self).data(index, role)


def create_table_model(parent, columns, _class=None):
    # Need to subclass QtGui.QStandardItemModel to get custom column alignment.
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



class MainWindow(QtGui.QMainWindow):
    _settings = None

    numberPopulated = QtCore.Signal(int)
    log_signal = QtCore.Signal(tuple)

    def __init__(self, parent=None):
        super(MainWindow, self).__init__(parent)

        self.thread = WorkThread()

        ## GENERATE THE UI

        self.setWindowTitle("PeaSauce")

        self.list_model = create_table_model(self, [ ("Address", int), ("Data", str), ("Label", str), ("Instruction", str), ("Operands", str), ("Extra", str) ], _class=CustomItemModel2)
        self.list_model.column_alignments[0] = QtCore.Qt.AlignRight
        self.list_table = create_table_widget(self.list_model)

        self.setCentralWidget(self.list_table)

        self.create_menus()
        self.create_dock_windows()

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
        self.log_model = create_table_model(self, [ ("Timestamp", str), ("System", str), ("Description", str), ])
        self.log_table = create_table_widget(self.log_model)
        self.log_table.setAlternatingRowColors(True)
        dock.setWidget(self.log_table)
        self.addDockWidget(QtCore.Qt.BottomDockWidgetArea, dock)
        self.viewMenu.addAction(dock.toggleViewAction())
        dock.setObjectName("dock-log")

        dock = QtGui.QDockWidget("Symbols", self)
        dock.setAllowedAreas(QtCore.Qt.LeftDockWidgetArea | QtCore.Qt.RightDockWidgetArea)
        self.symbols_model = create_table_model(self, [ ("Symbol", str), ("Address", int), ])
        self.symbols_table = create_table_widget(self.symbols_model)
        dock.setWidget(self.symbols_table)
        self.addDockWidget(QtCore.Qt.RightDockWidgetArea, dock)
        self.viewMenu.addAction(dock.toggleViewAction())
        dock.setObjectName("dock-symbols")

        dock = QtGui.QDockWidget("Segments", self)
        dock.setAllowedAreas(QtCore.Qt.LeftDockWidgetArea | QtCore.Qt.RightDockWidgetArea)
        self.segments_model = create_table_model(self, [ ("#", int), ("Type", str), ("Memory", int), ("Disk", int), ("Relocs", int), ("Symbols", int), ])
        self.segments_table = create_table_widget(self.segments_model)
        dock.setWidget(self.segments_table)
        self.addDockWidget(QtCore.Qt.RightDockWidgetArea, dock)
        self.viewMenu.addAction(dock.toggleViewAction())
        dock.setObjectName("dock-segments")

    def create_menus(self):
        self.open_action = QtGui.QAction("&Open ...", self, shortcut="Ctrl+O", statusTip="Disassemble a new file", triggered=self.on_file_open_menu)
        self.quit_action = QtGui.QAction("&Quit", self, shortcut="Ctrl+Q", statusTip="Quit the application", triggered=self.on_file_quit_menu)
        self.goto_address_action = QtGui.QAction("Go to address", self, shortcut="Ctrl+G", statusTip="View a specific address", triggered=self.on_search_goto_address_menu)
        self.choose_font_action = QtGui.QAction("Select font", self, statusTip="Change the font", triggered=self.on_settings_choose_font_menu)

        self.file_menu = self.menuBar().addMenu("&File")
        self.file_menu.addAction(self.open_action)
        self.file_menu.addSeparator()
        self.file_menu.addAction(self.quit_action)

        self.search_menu = self.menuBar().addMenu("&Search")
        self.search_menu.addAction(self.goto_address_action)

        self.viewMenu = self.menuBar().addMenu("&View")

        self.settings_menu = self.menuBar().addMenu("Settings")
        self.settings_menu.addAction(self.choose_font_action)

    def reset_all(self):
        self.reset_ui()
        self.reset_state()

    def reset_ui(self):
        for model in (self.list_model, self.symbols_model, self.segments_model, self.log_model):
            if model.rowCount():
                model.removeRows(0, model.rowCount(), QtCore.QModelIndex())
        self.file_path = None

    def reset_state(self):
        """ Called to clear out all state related to loaded data. """
        self.file_path = None
        run.set_symbol_insert_func(None)

    def show_confirmation_dialog(self, title, message):
        reply = QtGui.QMessageBox.question(self, title, message, QtGui.QMessageBox.Ok | QtGui.QMessageBox.Cancel)
        return reply == QtGui.QMessageBox.Ok

    def show_information_dialog(self, title, message):
        QtGui.QMessageBox.information(self, title, message)

    def on_file_open_menu(self):
        if self.file_path is not None:
            if not self.show_confirmation_dialog("Abandon work?", "You have existing work loaded, do you wish to abandon it?"):
                return
            self.reset_all()

        # Request the user select a file.
        options = QtGui.QFileDialog.Options()
        file_path, open_filter = QtGui.QFileDialog.getOpenFileName(self, "Select a file to disassemble", options=options)
        if not len(file_path):
            return

        # An attempt will be made to load an existing file.
        self.file_path = file_path

        # Display a modal dialog.
        progressDialog = self.progressDialog = QtGui.QProgressDialog(self)
        progressDialog.setCancelButtonText("&Cancel")
        progressDialog.setRange(0, 100)
        progressDialog.setWindowTitle("Loading a File")
        progressDialog.setMinimumDuration(1)

        self.thread.result.connect(self.on_file_processed_signal)
        self.thread.add_work(run.UI_display_file, file_path)

        while self.file_path is not None:
            progressDialog.setValue(0)
            progressDialog.setLabelText("Some disassembly stuff")
            QtGui.qApp.processEvents()
            if progressDialog.wasCanceled():
                self.reset_state()
                break

        progressDialog.close()

    def on_file_processed_signal(self, line_count):
        self.progressDialog.close()
        self.thread.result.disconnect(self.on_file_processed_signal)
        # This isn't really good enough, as long loading files may send mixed signals.
        if self.file_path is None:
            return

        if line_count == 0:
            self.reset_state()
            self.show_information_dialog("Unable to open file", "The file does not appear to be a supported executable file format.")
            return

        ## Populate the disassembly view with the loaded data.
        model = self.list_model
        model.refresh(QtCore.QModelIndex())

        ## SEGMENTS
 
        # Populate the segments dockable window with the loaded segment information.
        model = self.segments_model
        for segment_id in range(len(run.file_info.segments)):
            model.insertRows(model.rowCount(), 1, QtCore.QModelIndex())
            
            segment_type = run.file_info.get_segment_type(segment_id)
            if segment_type == archlib.SEGMENT_TYPE_CODE:
                segment_type = "code"
            elif segment_type == archlib.SEGMENT_TYPE_DATA:
                segment_type = "data"
            elif segment_type == archlib.SEGMENT_TYPE_BSS:
                segment_type = "bss"
            length = run.file_info.get_segment_length(segment_id)
            data_length = run.file_info.get_segment_data_length(segment_id)
            if run.file_info.get_segment_data_file_offset(segment_id) == -1:
                data_length = "-"
            reloc_count = len(run.file_info.relocations_by_segment_id.get(segment_id, []))
            symbol_count = len(run.file_info.symbols_by_segment_id.get(segment_id, []))

            model.setData(model.index(segment_id, 0, QtCore.QModelIndex()), segment_id)
            for i, column_value in enumerate((segment_type, length, data_length, reloc_count, symbol_count)):
                model.setData(model.index(segment_id, i+1, QtCore.QModelIndex()), column_value)

        self.segments_table.resizeColumnsToContents()
        self.segments_table.horizontalHeader().setStretchLastSection(True)

        ## SYMBOLS

        # Register for further symbol events (only add for now).
        run.set_symbol_insert_func(self._disassembly_event_new_symbol)

        model = self.symbols_model
        row_index = 0
        for symbol_address, symbol_label in run.symbols_by_address.iteritems():
            model.insertRows(model.rowCount(), 1, QtCore.QModelIndex())
            model.setData(model.index(row_index, 0, QtCore.QModelIndex()), symbol_label)
            model.setData(model.index(row_index, 1, QtCore.QModelIndex()), symbol_address)
            row_index += 1

        self.segments_table.resizeColumnsToContents()
        self.segments_table.horizontalHeader().setStretchLastSection(True)

    def on_file_quit_menu(self):
        if self.show_confirmation_dialog("Quit..", "Are you sure you wish to quit?"):
            self.close()

    def on_search_goto_address_menu(self):
        line_idx = self.list_table.currentIndex().row()
        if line_idx == -1:
            line_idx = 0
        address = run.get_address_for_line_number(line_idx)
        text, ok = QtGui.QInputDialog.getText(self, "Which address?", "Address:", QtGui.QLineEdit.Normal, "0x%X" % address)
        if ok and text != '':
            new_address = None
            if text.startswith("0x") or text.startswith("$"):
                new_address = int(text, 16)
            else:
                new_address = int(text)
            if new_address is not None:
                new_line_idx = run.get_line_number_for_address(new_address)
                self.list_table.selectRow(new_line_idx)

    def on_settings_choose_font_menu(self):
        font, ok = QtGui.QFontDialog.getFont(QtGui.QFont("Courier New", 10), self)
        if font and ok:
            self.list_table.setFont(font)
            self._set_setting("font-info", font.toString())

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

    def _disassembly_event_new_symbol(self, address, label):
        return
        model = self.segments_model
        for symbol_address, symbol_label in run.symbols_by_address.iteritems():
            model.insertRows(model.rowCount(), 1, QtCore.QModelIndex())
            model.setData(model.index(segment_id, 0, QtCore.QModelIndex()), symbol_label)
            model.setData(model.index(segment_id, 1, QtCore.QModelIndex()), symbol_address)

        self.segments_table.resizeColumnsToContents()
        self.segments_table.horizontalHeader().setStretchLastSection(True)
        


def _initialise_logging(window):
    def _ui_thread_logging(t):
        global window
        timestamp, logger_name, message = t
        table = window.log_table
        model = window.log_model
        row_index = model.rowCount()
        model.insertRows(row_index, 1, QtCore.QModelIndex())
        model.setData(model.index(row_index, 0, QtCore.QModelIndex()), time.ctime(timestamp))
        model.setData(model.index(row_index, 1, QtCore.QModelIndex()), logger_name)
        model.setData(model.index(row_index, 2, QtCore.QModelIndex()), message)
        table.resizeColumnsToContents()
        table.horizontalHeader().setStretchLastSection(True)
        #table.scrollTo(model.index(row_index, 0, QtCore.QModelIndex()), QtGui.QAbstractItemView.PositionAtBottom)
        table.scrollToBottom()

    window.log_signal.connect(_ui_thread_logging)

    class LogHandler(logging.Handler):
        def emit(self, record):
            msg = self.format(record)
            # These logging events may be happening in the worker thread, ensure they only get displayed in the UI thread.
            window.log_signal.emit((record.created, record.name, msg))

    handler = LogHandler()
    handler.setLevel(logging.DEBUG)

    logger = logging.root
    logger.setLevel(logging.DEBUG)
    logger.addHandler(handler)


if __name__ == '__main__':
    app = QtGui.QApplication(sys.argv)
    app_font = QtGui.QApplication.font()

    window = MainWindow()
    # The window needs to be created so we can connect to its signal.
    _initialise_logging(window)
    window.show()

    sys.exit(app.exec_())

