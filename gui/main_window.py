"""Main application window."""

from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QSplitter,
    QToolBar, QLabel, QComboBox, QPushButton, QFileDialog,
    QGroupBox, QFormLayout, QSpinBox, QDoubleSpinBox, QTableWidget,
    QTableWidgetItem, QHeaderView, QMessageBox, QApplication,
    QTabWidget, QScrollArea, QSizePolicy, QLineEdit,
)
from PyQt6.QtCore import Qt, QSize
from PyQt6.QtGui import QAction, QFont, QColor, QDoubleValidator

class NoScrollSpinBox(QDoubleSpinBox):
    """QDoubleSpinBox that ignores mouse wheel events."""
    def wheelEvent(self, event):
        event.ignore()

class NoScrollComboBox(QComboBox):
    """QComboBox that ignores mouse wheel events."""
    def wheelEvent(self, event):
        event.ignore()

class NoScrollIntSpinBox(QSpinBox):
    """QSpinBox that ignores mouse wheel events."""
    def wheelEvent(self, event):
        event.ignore()


from core.dxf_loader import DxfPart, load_dxf
from core.nesting import NestItem, nest_parts, calculate_quote, NestResult, QuoteResult
from gui.dxf_canvas import DxfCanvas, PART_COLOURS
from gui.nest_canvas import NestCanvas


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("DXF Quoting Tool")
        self.resize(1280, 800)
        self.setMinimumSize(900, 600)

        self.parts: list[DxfPart] = []
        self._canvases: list[DxfCanvas] = []
        self._units = "mm"

        self._build_toolbar()
        self._build_ui()
        self._apply_style()

    def _build_toolbar(self):
        tb = QToolBar("Main")
        tb.setIconSize(QSize(20, 20))
        tb.setMovable(False)
        self.addToolBar(tb)

        open_action = QAction("Open DXF", self)
        open_action.triggered.connect(self._open_file)
        tb.addAction(open_action)

        clear_action = QAction("Clear All", self)
        clear_action.triggered.connect(self._clear_all)
        tb.addAction(clear_action)

        tb.addSeparator()

        tb.addWidget(QLabel("  Units: "))
        self._units_combo = NoScrollComboBox()
        self._units_combo.addItems(["mm", "inch"])
        self._units_combo.setMinimumWidth(70)
        self._units_combo.currentTextChanged.connect(self._units_changed)
        tb.addWidget(self._units_combo)

        tb.addSeparator()

        self._measure_btn = QPushButton("Measure")
        self._measure_btn.setCheckable(True)
        self._measure_btn.setMinimumWidth(80)
        self._measure_btn.toggled.connect(self._toggle_measure)
        tb.addWidget(self._measure_btn)

        self._measure_label = QLabel("  --")
        self._measure_label.setFont(QFont("Consolas", 11))
        self._measure_label.setStyleSheet("color: #FF5722;")
        tb.addWidget(self._measure_label)

        tb.addWidget(QLabel("    "))  # spacer

        self._fit_btn = QPushButton("Fit View")
        self._fit_btn.setMinimumWidth(80)
        self._fit_btn.clicked.connect(self._fit_view)
        tb.addWidget(self._fit_btn)

    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QHBoxLayout(central)
        main_layout.setContentsMargins(4, 4, 4, 4)

        # Main horizontal splitter: left canvases | right controls
        main_splitter = QSplitter(Qt.Orientation.Horizontal)

        # Left: stacked canvases
        left_splitter = QSplitter(Qt.Orientation.Vertical)

        # Tab widget for part viewers
        self._tab_widget = QTabWidget()
        self._tab_widget.setTabsClosable(True)
        self._tab_widget.tabCloseRequested.connect(self._close_tab)
        # Add a placeholder when empty
        self._placeholder = QLabel("Open a DXF file to get started")
        self._placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._placeholder.setStyleSheet("color: #666; font-size: 14px;")
        self._tab_widget.addTab(self._placeholder, "No files loaded")
        self._tab_widget.setTabsClosable(False)
        left_splitter.addWidget(self._tab_widget)

        self._nest_canvas = NestCanvas()
        left_splitter.addWidget(self._nest_canvas)
        left_splitter.setSizes([500, 250])

        main_splitter.addWidget(left_splitter)

        # Right: vertical splitter with expandable sections
        right_splitter = QSplitter(Qt.Orientation.Vertical)
        right_splitter.setMinimumWidth(320)
        right_splitter.setChildrenCollapsible(True)

        # --- Parts list ---
        parts_group = QGroupBox("Loaded Parts")
        parts_inner = QVBoxLayout(parts_group)
        parts_inner.setContentsMargins(6, 18, 6, 6)
        self._parts_table = QTableWidget(0, 5)
        self._parts_table.setHorizontalHeaderLabels(["Part", "Size (mm)", "Cut (m)", "Qty", ""])
        self._parts_table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeMode.Stretch
        )
        self._parts_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Fixed)
        self._parts_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Fixed)
        self._parts_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.Fixed)
        self._parts_table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeMode.Fixed)
        self._parts_table.setColumnWidth(1, 100)
        self._parts_table.setColumnWidth(2, 65)
        self._parts_table.setColumnWidth(3, 85)
        self._parts_table.setColumnWidth(4, 30)
        self._parts_table.verticalHeader().setVisible(False)
        self._parts_table.cellClicked.connect(self._part_row_clicked)
        parts_inner.addWidget(self._parts_table)
        right_splitter.addWidget(parts_group)

        # --- Sheet settings ---
        sheet_widget = QGroupBox("Sheet Settings")
        sheet_form = QFormLayout(sheet_widget)
        sheet_form.setContentsMargins(6, 18, 6, 6)
        sheet_form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)

        # Sheet size preset dropdown
        # Tuples are (label, width, height) where width is the long
        # side (left-to-right) and height is the short side (top-to-bottom)
        self._sheet_sizes = [
            ("Custom", 0, 0),
            ("1200 x 2400  (standard)", 2400, 1200),
            ("1500 x 3000  (standard)", 3000, 1500),
            ("1200 x 3000  (common)", 3000, 1200),
            ("1500 x 2400  (common)", 2400, 1500),
            ("1500 x 3600  (common)", 3600, 1500),
            ("1200 x 3600  (common)", 3600, 1200),
            ("1200 x 4000  (large)", 4000, 1200),
            ("1500 x 4000  (large)", 4000, 1500),
            ("1200 x 6000  (large)", 6000, 1200),
            ("1500 x 6000  (large)", 6000, 1500),
            ("1800 x 6000  (large)", 6000, 1800),
        ]
        self._sheet_preset = NoScrollComboBox()
        self._updating_preset = False
        for label, w, h in self._sheet_sizes:
            self._sheet_preset.addItem(label)
        self._sheet_preset.setCurrentIndex(0)
        self._sheet_preset.currentIndexChanged.connect(self._sheet_preset_changed)
        sheet_form.addRow("Sheet size:", self._sheet_preset)

        dim_validator = QDoubleValidator(1.0, 99999.0, 1)
        self._sheet_w = QLineEdit("2400")
        self._sheet_w.setValidator(dim_validator)
        self._sheet_w.textChanged.connect(self._sheet_dims_changed)
        sheet_form.addRow("Width (mm):", self._sheet_w)

        self._sheet_h = QLineEdit("1200")
        self._sheet_h.setValidator(dim_validator)
        self._sheet_h.textChanged.connect(self._sheet_dims_changed)
        sheet_form.addRow("Height (mm):", self._sheet_h)

        self._gap = NoScrollSpinBox()
        self._gap.setRange(0, 100)
        self._gap.setValue(5)
        self._gap.setSuffix(" mm")
        self._gap.setDecimals(1)
        self._gap.setButtonSymbols(QDoubleSpinBox.ButtonSymbols.NoButtons)
        sheet_form.addRow("Part gap:", self._gap)

        self._edge_offset = NoScrollSpinBox()
        self._edge_offset.setRange(0, 200)
        self._edge_offset.setValue(5)
        self._edge_offset.setSuffix(" mm")
        self._edge_offset.setDecimals(1)
        self._edge_offset.setButtonSymbols(QDoubleSpinBox.ButtonSymbols.NoButtons)
        sheet_form.addRow("Edge offset:", self._edge_offset)

        # Select the default standard size
        self._sheet_preset.setCurrentIndex(1)

        right_splitter.addWidget(sheet_widget)

        # --- Costing + Button ---
        cost_and_button = QWidget()
        cost_and_button_layout = QVBoxLayout(cost_and_button)
        cost_and_button_layout.setContentsMargins(0, 0, 0, 0)
        cost_and_button_layout.setSpacing(6)

        cost_group = QGroupBox("Costing")
        cost_form = QFormLayout(cost_group)
        cost_form.setContentsMargins(6, 18, 6, 6)
        cost_form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)

        self._sheet_cost = NoScrollSpinBox()
        self._sheet_cost.setRange(0, 99999)
        self._sheet_cost.setValue(150.00)
        self._sheet_cost.setPrefix("$ ")
        self._sheet_cost.setDecimals(2)
        self._sheet_cost.setButtonSymbols(QDoubleSpinBox.ButtonSymbols.NoButtons)
        cost_form.addRow("Cost per sheet:", self._sheet_cost)

        self._cut_cost = NoScrollSpinBox()
        self._cut_cost.setRange(0, 9999)
        self._cut_cost.setValue(1.50)
        self._cut_cost.setPrefix("$ ")
        self._cut_cost.setDecimals(2)
        self._cut_cost.setButtonSymbols(QDoubleSpinBox.ButtonSymbols.NoButtons)
        cost_form.addRow("Cut cost per m:", self._cut_cost)

        cost_and_button_layout.addWidget(cost_group)

        self._nest_btn = QPushButton("NEST && QUOTE")
        self._nest_btn.setFixedHeight(44)
        self._nest_btn.setFont(QFont("Segoe UI", 12, QFont.Weight.Bold))
        self._nest_btn.clicked.connect(self._run_nesting)
        cost_and_button_layout.addWidget(self._nest_btn)

        right_splitter.addWidget(cost_and_button)

        # --- Results + Copy ---
        results_and_copy = QWidget()
        results_and_copy_layout = QVBoxLayout(results_and_copy)
        results_and_copy_layout.setContentsMargins(0, 0, 0, 0)
        results_and_copy_layout.setSpacing(6)

        results_group = QGroupBox("Quote Results")
        results_form = QFormLayout(results_group)
        results_form.setContentsMargins(6, 18, 6, 6)
        results_form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)

        self._res_sheets = QLabel("--")
        results_form.addRow("Sheets needed:", self._res_sheets)

        self._res_util = QLabel("--")
        results_form.addRow("Utilisation:", self._res_util)

        self._res_sheet_cost = QLabel("--")
        results_form.addRow("Sheet cost:", self._res_sheet_cost)

        self._res_utilised_cost = QLabel("--")
        results_form.addRow("Utilised cost:", self._res_utilised_cost)

        self._res_cut_len = QLabel("--")
        results_form.addRow("Cut length:", self._res_cut_len)

        self._res_cut_cost = QLabel("--")
        results_form.addRow("Cut cost:", self._res_cut_cost)

        self._res_total = QLabel("--")
        self._res_total.setFont(QFont("Segoe UI", 13, QFont.Weight.Bold))
        results_form.addRow("TOTAL:", self._res_total)

        results_and_copy_layout.addWidget(results_group)

        self._copy_btn = QPushButton("Copy Quote to Clipboard")
        self._copy_btn.setMinimumHeight(32)
        self._copy_btn.clicked.connect(self._copy_quote)
        results_and_copy_layout.addWidget(self._copy_btn)
        results_and_copy_layout.addStretch()

        right_splitter.addWidget(results_and_copy)

        # Default section sizes: parts tall, settings compact, costing compact, results compact
        right_splitter.setSizes([300, 200, 180, 200])

        main_splitter.addWidget(right_splitter)
        main_splitter.setSizes([900, 380])

        # Assemble
        main_layout.addWidget(main_splitter)

        # State
        self._last_quote: QuoteResult | None = None
        self._last_nest: NestResult | None = None

    def _apply_style(self):
        self.setStyleSheet("""
            QMainWindow, QWidget { background-color: #2b2b2b; color: #e0e0e0; }
            QGroupBox {
                font-weight: bold; border: 1px solid #444;
                border-radius: 4px; margin-top: 8px; padding-top: 14px;
            }
            QGroupBox::title { subcontrol-origin: margin; left: 8px; padding: 0 4px; }
            QPushButton {
                background-color: #3a3a3a; border: 1px solid #555;
                border-radius: 3px; padding: 6px 14px; color: #e0e0e0;
                min-height: 24px;
            }
            QPushButton:hover { background-color: #4a4a4a; }
            QPushButton:checked { background-color: #D46A2B; color: white; }
            QDoubleSpinBox, QSpinBox, QComboBox, QLineEdit {
                background-color: #3a3a3a; border: 1px solid #555;
                border-radius: 3px; padding: 4px 6px; color: #e0e0e0;
                min-height: 22px;
            }
            QTableWidget {
                background-color: #2a2a2a; gridline-color: #444;
                border: 1px solid #444;
            }
            QHeaderView::section {
                background-color: #1B2A4A; color: white;
                border: 1px solid #333; padding: 4px;
            }
            QToolBar {
                background-color: #333; border-bottom: 1px solid #444;
                spacing: 6px; padding: 3px;
            }
            QLabel { color: #e0e0e0; }
            QTabWidget::pane { border: 1px solid #444; }
            QTabBar::tab {
                background-color: #3a3a3a; color: #ccc; border: 1px solid #444;
                padding: 6px 14px; margin-right: 2px; border-top-left-radius: 4px;
                border-top-right-radius: 4px;
            }
            QTabBar::tab:selected { background-color: #1B2A4A; color: white; }
            QTabBar::tab:hover { background-color: #4a4a4a; }
            QTabBar::close-button { image: none; width: 12px; height: 12px; }
            QSplitter::handle { background-color: #555; }
            QSplitter::handle:vertical { height: 4px; }
            QSplitter::handle:horizontal { width: 4px; }
            QScrollArea { border: none; background-color: #2b2b2b; }
            QScrollBar:vertical {
                background-color: #2b2b2b; width: 10px; border: none;
            }
            QScrollBar::handle:vertical {
                background-color: #555; border-radius: 4px; min-height: 30px;
            }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
        """)

    # --- Actions ---

    def _open_file(self):
        paths, _ = QFileDialog.getOpenFileNames(
            self, "Open DXF Files", "",
            "DXF Files (*.dxf);;All Files (*)",
        )
        if not paths:
            return

        # Remove placeholder tab if present
        if self._placeholder is not None:
            idx = self._tab_widget.indexOf(self._placeholder)
            if idx >= 0:
                self._tab_widget.removeTab(idx)
                self._placeholder = None
            self._tab_widget.setTabsClosable(True)

        for path in paths:
            try:
                part = load_dxf(path, unit_override=self._units)
                self.parts.append(part)

                # Create a canvas tab for this part
                canvas = DxfCanvas()
                canvas.measurement_changed.connect(self._on_measurement)
                canvas.set_parts([part])
                self._canvases.append(canvas)

                short_name = part.name[:30]
                self._tab_widget.addTab(canvas, short_name)
                self._tab_widget.setCurrentWidget(canvas)

            except Exception as e:
                QMessageBox.warning(self, "Load Error", f"Failed to load:\n{path}\n\n{e}")

        self._refresh_parts_table()

    def _close_tab(self, index: int):
        widget = self._tab_widget.widget(index)
        if widget in self._canvases:
            canvas_idx = self._canvases.index(widget)
            self._canvases.pop(canvas_idx)
            self.parts.pop(canvas_idx)

        self._tab_widget.removeTab(index)
        self._refresh_parts_table()

        # Restore placeholder if no tabs left
        if self._tab_widget.count() == 0:
            self._placeholder = QLabel("Open a DXF file to get started")
            self._placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self._placeholder.setStyleSheet("color: #666; font-size: 14px;")
            self._tab_widget.addTab(self._placeholder, "No files loaded")
            self._tab_widget.setTabsClosable(False)

    def _clear_all(self):
        self.parts.clear()
        self._canvases.clear()
        self._tab_widget.clear()

        self._placeholder = QLabel("Open a DXF file to get started")
        self._placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._placeholder.setStyleSheet("color: #666; font-size: 14px;")
        self._tab_widget.addTab(self._placeholder, "No files loaded")
        self._tab_widget.setTabsClosable(False)

        self._refresh_parts_table()
        self._nest_canvas.nest_result = None
        self._nest_canvas.update()
        self._clear_results()

    def _sheet_preset_changed(self, index: int):
        if self._updating_preset:
            return
        _, w, h = self._sheet_sizes[index]
        if w > 0 and h > 0:
            self._updating_preset = True
            self._sheet_w.setText(str(int(w)))
            self._sheet_h.setText(str(int(h)))
            self._updating_preset = False

    def _sheet_dims_changed(self):
        if self._updating_preset:
            return
        # Check if current dims match a preset; if not, switch to Custom
        try:
            w = float(self._sheet_w.text())
            h = float(self._sheet_h.text())
        except ValueError:
            return
        for i, (_, pw, ph) in enumerate(self._sheet_sizes):
            if pw == w and ph == h:
                self._updating_preset = True
                self._sheet_preset.setCurrentIndex(i)
                self._updating_preset = False
                return
        self._updating_preset = True
        self._sheet_preset.setCurrentIndex(0)  # Custom
        self._updating_preset = False

    def _units_changed(self, text: str):
        self._units = text
        new_parts = []
        new_canvases = []
        for i, part in enumerate(self.parts):
            try:
                new_part = load_dxf(part.filepath, unit_override=text)
            except Exception:
                new_part = part
            new_parts.append(new_part)
            # Update the canvas for this tab
            if i < len(self._canvases):
                self._canvases[i].set_parts([new_part])

        self.parts = new_parts
        self._refresh_parts_table()

    def _toggle_measure(self, checked: bool):
        for canvas in self._canvases:
            canvas.measure_mode = checked
            canvas._measure_p1 = None
            canvas._measure_p2 = None
            canvas.update()
        if not checked:
            self._measure_label.setText("  --")

    def _on_measurement(self, distance: float):
        self._measure_label.setText(f"  {distance:.2f} {self._units}")

    def _fit_view(self):
        # Fit the currently visible tab
        current = self._tab_widget.currentWidget()
        if isinstance(current, DxfCanvas):
            current.fit_view()
            current.update()

    def _refresh_parts_table(self):
        # Sync canvas colours to current part indices
        for i, canvas in enumerate(self._canvases):
            canvas.part_colour = PART_COLOURS[i % len(PART_COLOURS)]
            canvas.update()

        self._parts_table.setRowCount(len(self.parts))
        for i, part in enumerate(self.parts):
            name_item = QTableWidgetItem(part.name[:30])
            name_item.setFlags(name_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self._parts_table.setItem(i, 0, name_item)

            size_item = QTableWidgetItem(f"{part.width:.0f} x {part.height:.0f}")
            size_item.setFlags(size_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self._parts_table.setItem(i, 1, size_item)

            cut_item = QTableWidgetItem(f"{part.cut_length_m:.2f}")
            cut_item.setFlags(cut_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self._parts_table.setItem(i, 2, cut_item)

            qty_spin = NoScrollIntSpinBox()
            qty_spin.setRange(1, 999)
            qty_spin.setValue(1)
            qty_spin.setMinimumWidth(75)
            qty_spin.setStyleSheet("QSpinBox { padding-right: 18px; }")
            self._parts_table.setCellWidget(i, 3, qty_spin)

            remove_btn = QPushButton("\u2715")
            remove_btn.setFixedSize(26, 26)
            remove_btn.setStyleSheet(
                "QPushButton { color: #ff6666; background-color: #2a2a2a; border: none; "
                "font-weight: bold; font-size: 14px; padding: 0; margin: 0; }"
                "QPushButton:hover { color: white; background-color: #cc3333; }"
            )
            remove_btn.clicked.connect(lambda checked, idx=i: self._remove_part(idx))
            self._parts_table.setCellWidget(i, 4, remove_btn)

    def _part_row_clicked(self, row: int, _col: int):
        if 0 <= row < len(self._canvases):
            self._tab_widget.setCurrentWidget(self._canvases[row])

    def _remove_part(self, index: int):
        if index < 0 or index >= len(self.parts):
            return
        self.parts.pop(index)
        # Remove matching canvas tab
        if index < len(self._canvases):
            canvas = self._canvases.pop(index)
            tab_idx = self._tab_widget.indexOf(canvas)
            if tab_idx >= 0:
                self._tab_widget.removeTab(tab_idx)
        # Restore placeholder if empty
        if not self.parts and self._tab_widget.count() == 0:
            self._placeholder = QLabel("Open a DXF file to get started")
            self._placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self._placeholder.setStyleSheet("color: #666; font-size: 14px;")
            self._tab_widget.addTab(self._placeholder, "No files loaded")
            self._tab_widget.setTabsClosable(False)
        self._refresh_parts_table()

    def _run_nesting(self):
        if not self.parts:
            QMessageBox.information(self, "No Parts", "Load at least one DXF file first.")
            return

        items: list[NestItem] = []
        colour_map: dict[str, int] = {}
        for i, part in enumerate(self.parts):
            qty_widget = self._parts_table.cellWidget(i, 3)
            qty = qty_widget.value() if qty_widget else 1
            colour_map[part.name] = i
            for _ in range(qty):
                items.append(NestItem(
                    name=part.name,
                    width=part.width,
                    height=part.height,
                    cut_length=part.total_cut_length,
                ))

        nest = nest_parts(
            items,
            sheet_width=float(self._sheet_w.text() or 0),
            sheet_height=float(self._sheet_h.text() or 0),
            gap=self._gap.value(),
            edge_offset=self._edge_offset.value(),
        )

        quote = calculate_quote(
            nest,
            sheet_cost=self._sheet_cost.value(),
            cut_cost_per_m=self._cut_cost.value(),
            units=self._units,
        )

        self._last_nest = nest
        self._last_quote = quote

        utilised_cost = quote.sheet_cost_total * (quote.utilisation / 100.0)

        self._res_sheets.setText(str(quote.sheets_needed))
        self._res_util.setText(f"{quote.utilisation:.1f}%")
        self._res_sheet_cost.setText(f"${quote.sheet_cost_total:.2f}")
        self._res_utilised_cost.setText(f"${utilised_cost:.2f}")
        self._res_cut_len.setText(f"{quote.cut_length_m:.2f} m")
        self._res_cut_cost.setText(f"${quote.cut_cost_total:.2f}")
        self._res_total.setText(f"${utilised_cost + quote.cut_cost_total:.2f}")
        self._res_total.setStyleSheet("color: #D46A2B; font-size: 14px; font-weight: bold;")

        self._nest_canvas.set_result(nest, colour_map)

    def _clear_results(self):
        for label in [self._res_sheets, self._res_util, self._res_sheet_cost,
                      self._res_utilised_cost, self._res_cut_len, self._res_cut_cost,
                      self._res_total]:
            label.setText("--")
        self._res_total.setStyleSheet("")

    def _copy_quote(self):
        if not self._last_quote:
            return
        q = self._last_quote
        utilised_cost = q.sheet_cost_total * (q.utilisation / 100.0)
        total = utilised_cost + q.cut_cost_total
        text = (
            f"DXF Quote\n"
            f"Sheets: {q.sheets_needed} @ ${q.sheet_cost_each:.2f} = ${q.sheet_cost_total:.2f}\n"
            f"Utilisation: {q.utilisation:.1f}%\n"
            f"Utilised cost: ${utilised_cost:.2f}\n"
            f"Cut length: {q.cut_length_m:.2f} m @ ${q.cut_cost_per_m:.2f}/m = ${q.cut_cost_total:.2f}\n"
            f"TOTAL: ${total:.2f}\n"
        )
        clipboard = QApplication.clipboard()
        if clipboard:
            clipboard.setText(text)
