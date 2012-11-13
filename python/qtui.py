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

Possibility for less programming overhead with later dynamic row insertion (e.g. add full line comment / change datatype):

CustomItemModel.data() is called to get the text to display in all table cells, as they are refreshed.  It
should be possible to never set the values for all the cells, and to just give them through data() on
demand.  This should be better for dynamic row insertion, perhaps?

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

# Nasty global variable that caches persisted setting values.
settings = None


if False:
    class CustomTableView(QtGui.QTableView):
        def __init__(self, parent=None):
            super(CustomTableView, self).__init__(parent)

            # May start as None.
            self.selected_row_index = None

        def currentChanged(self, currentIndex, previousIndex):
            self.selected_row_index = currentIndex.row()
            print "self.selected_row_index", self.selected_row_index
            # Is this necessary?
            super(CustomTableView, self).currentChanged(currentIndex, previousIndex)


class CustomItemModel(QtGui.QStandardItemModel):
    def __init__(self, *args, **kwargs):
        super(CustomItemModel, self).__init__(*args, **kwargs)

        self.column_alignments = [ QtCore.Qt.AlignLeft ] * self.columnCount(QtCore.QModelIndex())

    def data(self, index, role=QtCore.Qt.DisplayRole):
        column, row = index.column(), index.row()
        if role == QtCore.Qt.TextAlignmentRole:
            return self.column_alignments[column]
            if column > 0:
                return QtCore.Qt.AlignLeft
            else:
                return QtCore.Qt.AlignRight
        return super(CustomItemModel, self).data(index, role)


def create_table_model(parent, column_names):
    # Need to subclass QtGui.QStandardItemModel to get custom column alignment.
    model = CustomItemModel(0, len(column_names), parent)
    for i, column_name in enumerate(column_names):    
        model.setHeaderData(i, QtCore.Qt.Horizontal, column_name)
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


# Encapsulate all the widgets that make up the main widget.
class MainWidget(QtGui.QWidget):
    def __init__(self, parent=None):
        super(MainWidget, self).__init__(parent)

        self.model = create_table_model(self, [ "Address", "Data", "Label", "Instruction", "Operands", "Extra" ])
        self.model.column_alignments = [ QtCore.Qt.AlignRight, QtCore.Qt.AlignLeft,  QtCore.Qt.AlignLeft, QtCore.Qt.AlignLeft, QtCore.Qt.AlignLeft, QtCore.Qt.AlignLeft ]
        self.table = create_table_widget(self.model)

        layout = QtGui.QGridLayout()
        layout.addWidget(self.table, 0, 0)
        self.setLayout(layout)


class MainWindow(QtGui.QMainWindow):
    numberPopulated = QtCore.Signal(int)

    def __init__(self, parent=None):
        super(MainWindow, self).__init__(parent)

        self.setWindowTitle("PeaSauce")

        self.mainWidget = MainWidget(self)
        self.setCentralWidget(self.mainWidget)

        self.create_menus()
        self.create_dock_windows()

        self.font_info = get_setting("font-info")
        if self.font_info is not None:
            font = QtGui.QFont()
            if font.fromString(self.font_info):
                self.set_font_for_all_widgets(font)

    if False:
        def updateLog(self, number):
            self.logViewer.append("%d items added." % number)

    def create_dock_windows(self):
        dock = QtGui.QDockWidget("Log", self)
        dock.setAllowedAreas(QtCore.Qt.BottomDockWidgetArea)
        self.log_model = create_table_model(self, [ "Timestamp", "System", "Description", ])
        self.log_model.column_alignments = [ QtCore.Qt.AlignLeft, QtCore.Qt.AlignLeft, QtCore.Qt.AlignLeft ]
        self.log_table = create_table_widget(self.log_model)
        self.log_table.setAlternatingRowColors(True)
        dock.setWidget(self.log_table)
        self.addDockWidget(QtCore.Qt.BottomDockWidgetArea, dock)
        self.viewMenu.addAction(dock.toggleViewAction())

        dock = QtGui.QDockWidget("Symbols", self)
        dock.setAllowedAreas(QtCore.Qt.LeftDockWidgetArea | QtCore.Qt.RightDockWidgetArea)
        self.symbols_model = create_table_model(self, [ "Symbol", ])
        self.symbols_table = create_table_widget(self.symbols_model)
        dock.setWidget(self.symbols_table)
        self.addDockWidget(QtCore.Qt.RightDockWidgetArea, dock)
        self.viewMenu.addAction(dock.toggleViewAction())

        dock = QtGui.QDockWidget("Segments", self)
        dock.setAllowedAreas(QtCore.Qt.LeftDockWidgetArea | QtCore.Qt.RightDockWidgetArea)
        self.segments_model = create_table_model(self, [ "#", "Type", "Alloc  Size", "Disk Size", ])
        self.segments_model.column_alignments = [ QtCore.Qt.AlignRight, QtCore.Qt.AlignLeft, QtCore.Qt.AlignRight, QtCore.Qt.AlignRight,  ]
        self.segments_table = create_table_widget(self.segments_model)
        dock.setWidget(self.segments_table)
        self.addDockWidget(QtCore.Qt.RightDockWidgetArea, dock)
        self.viewMenu.addAction(dock.toggleViewAction())

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

    def show_confirmation_dialog(self, title, message):
        reply = QtGui.QMessageBox.question(self, title, message, QtGui.QMessageBox.Ok | QtGui.QMessageBox.Cancel)
        return reply == QtGui.QMessageBox.Ok

    def show_information_dialog(self, title, message):
        QtGui.QMessageBox.information(self, title, message)

    def on_file_open_menu(self):
        options = QtGui.QFileDialog.Options()
        file_path, open_filter = QtGui.QFileDialog.getOpenFileName(self, "Select a file to disassemble", options=options)
        if len(file_path):
            line_count = run.UI_display_file(file_path)
            if line_count is None:
                self.show_information_dialog("Unable to open file", "The file does not appear to be a supported executable file format.")
                return

            ## Clear out any existing loaded state.
            # TODO: This should probably be put in a better place with a confirmation dialog?
            for model in (self.mainWidget.model, self.symbols_model, self.segments_model):
                if model.rowCount():
                    model.removeRows(0, model.rowCount(), QtCore.QModelIndex())

            ## Populate the disassembly view with the loaded data.
            model = self.mainWidget.model
            model.insertRows(model.rowCount(), line_count, QtCore.QModelIndex())
            for row_index in range(line_count):
                for column_index in range(6):
                    text = run.get_file_line(row_index, column_index)
                    model.setData(model.index(row_index, column_index, QtCore.QModelIndex()), text)

            ## Populate the segments dockable window with the loaded segment information.
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

                model.setData(model.index(segment_id, 0, QtCore.QModelIndex()), segment_id)
                for i, column_value in enumerate((segment_type, length, data_length)):
                    model.setData(model.index(segment_id, i+1, QtCore.QModelIndex()), column_value)
            self.segments_table.resizeColumnsToContents()
            self.segments_table.horizontalHeader().setStretchLastSection(True)

    def on_file_quit_menu(self):
        if self.show_confirmation_dialog("Quit..", "Are you sure you wish to quit?"):
            self.close()

    def on_search_goto_address_menu(self):
        line_idx = self.mainWidget.table.currentIndex().row()
        # block, block_idx = run.lookup_metadata_by_line_count(line_idx)
        print "got line_idx", line_idx
        if line_idx == -1:
            line_idx = 0
        address = run.get_address_for_line_number(line_idx)
        text, ok = QtGui.QInputDialog.getText(self, "Which address?", "Address:", QtGui.QLineEdit.Normal, "0x%X" % address)
        if ok and text != '':
            print "GOT LABEL", text
            new_address = None
            if text.startswith("0x") or text.startswith("$"):
                new_address = int(text, 16)
            else:
                new_address = int(text)
            if new_address is not None:
                new_line_idx = run.get_line_number_for_address(new_address)
                print "got new line number", new_line_idx
                self.mainWidget.table.selectRow(new_line_idx)


    def on_settings_choose_font_menu(self):
        # For now just change the font that the table view is using.
        font, ok = QtGui.QFontDialog.getFont(QtGui.QFont("Courier New", 10), self)
        if font and ok:
            self.set_font_for_all_widgets(font)
            set_setting("font-info", font.toString())

    def set_font_for_all_widgets(self, font):
        self.mainWidget.table.setFont(font)
        self.log_table.setFont(font)
        self.symbols_table.setFont(font)
        self.segments_table.setFont(font)


def set_setting(setting_name, setting_value):
    global settings
    settings[setting_name] = setting_value
    with open(SETTINGS_FILE, "wb") as f:
        cPickle.dump(settings, f)

def get_setting(setting_name, default_value=None):
    global settings
    if settings is None:
        if os.path.exists(SETTINGS_FILE):
            with open(SETTINGS_FILE, "rb") as f:
                settings = cPickle.load(f)
        else:
            settings = {}
    return settings.get(setting_name, default_value)

def _initialise_logging():
    class LogHandler(logging.Handler):
        def emit(self, record):
            global window
            msg = self.format(record)

            table = window.log_table
            model = window.log_model
            row_index = model.rowCount()
            model.insertRows(row_index, 1, QtCore.QModelIndex())
            model.setData(model.index(row_index, 0, QtCore.QModelIndex()), time.ctime(record.created))
            model.setData(model.index(row_index, 1, QtCore.QModelIndex()), record.name)
            model.setData(model.index(row_index, 2, QtCore.QModelIndex()), msg)
            table.resizeColumnsToContents()
            table.horizontalHeader().setStretchLastSection(True)
            table.scrollTo(model.index(row_index, 0, QtCore.QModelIndex()), QtGui.QAbstractItemView.PositionAtBottom)

    handler = LogHandler()
    handler.setLevel(logging.DEBUG)

    logger = logging.root
    logger.setLevel(logging.DEBUG)
    logger.addHandler(handler)


if __name__ == '__main__':
    _initialise_logging()

    app = QtGui.QApplication(sys.argv)

    window = MainWindow()
    window.show()

    sys.exit(app.exec_())

