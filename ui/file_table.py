"""
Таблиця файлів: іконка, ім'я, розмір, стиснутий розмір, відсоток.

Стандартна таблиця ttk.Treeview не вміє фарбувати окремі клітинки (зелений відсоток,
жирні цифри), тому таблицю зроблено на текстовому полі tk.Text: кожен рядок — це рядок
тексту, колонки вирівнюються позиціями табуляції, а кольори й шрифти задаються тегами.
"""

import tkinter as tk
import tkinter.font as tkfont
from pathlib import Path

import customtkinter as ctk

from .theme import ACCENT, BG, BORDER, FONT, FONT_MEDIUM, FONT_SEMIBOLD, GREEN, MUTED, SECONDARY, TEXT, load_icon

# Яку іконку показати біля файлу — за розширенням
FILE_TYPES = {
    "file-text": {".txt", ".md", ".doc", ".docx", ".odt", ".rtf", ".pdf", ".log"},
    "file-code": {".py", ".pyw", ".js", ".ts", ".html", ".css", ".json", ".xml", ".c", ".cpp", ".h",
                  ".cs", ".java", ".kt", ".go", ".rs", ".php", ".sql", ".sh", ".bat", ".ini", ".yaml", ".yml"},
    "file-spreadsheet": {".csv", ".xls", ".xlsx", ".ods"},
    "photo": {".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp", ".svg", ".ico", ".tif", ".tiff"},
    "music": {".mp3", ".wav", ".flac", ".ogg", ".m4a", ".aac"},
    "movie": {".mp4", ".avi", ".mkv", ".mov", ".webm", ".wmv"},
    "file-zip": {".zip", ".rar", ".7z", ".gz", ".tar", ".huf"},
}
COLUMNS = (90, 90, 110)  # ширина колонок «Розмір», «Стиснуто», «%» у пікселях
PAD = 12                 # відступ тексту від країв таблиці


def icon_for(name):
    suffix = Path(name).suffix.lower()
    return next((icon for icon, suffixes in FILE_TYPES.items() if suffix in suffixes), "file")


class FileTable(ctk.CTkFrame):
    def __init__(self, master, can_drop):
        super().__init__(master, fg_color=BG, border_width=1, border_color=BORDER, corner_radius=8)
        self.can_drop = can_drop
        self.rows = []         # (ім'я, розмір, стиснуто, відсоток, стиль відсотка)
        self.drag_over = False
        self.icons = {}        # tk.Text не тримає картинки сам — зберігаємо їх тут
        self._render_job = None

        scale = ctk.ScalingTracker.get_widget_scaling(self)
        self.scale = scale
        px = lambda size: -round(size * scale)  # від'ємний розмір у Tkinter = пікселі
        self.fonts = {
            "body": tkfont.Font(self, family=FONT, size=px(13)),
            "name": tkfont.Font(self, family=FONT_MEDIUM, size=px(13)),
            "number": tkfont.Font(self, family=FONT_SEMIBOLD, size=px(13)),
            "title": tkfont.Font(self, family=FONT_MEDIUM, size=px(14)),
            "hint": tkfont.Font(self, family=FONT, size=px(12)),
        }

        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(2, weight=1)
        self.header = self._make_text(height=1)
        self.header.grid(row=0, column=0, columnspan=2, sticky="ew", padx=2, pady=(8, 6))
        tk.Frame(self, height=1, bg=BORDER).grid(row=1, column=0, columnspan=2, sticky="ew", padx=1, pady=(0, 2))
        self.body = self._make_text()
        # Відступ 2 з обох боків, як у заголовка: інакше без смуги прокрутки список закриває праву лінію рамки
        self.body.grid(row=2, column=0, sticky="nsew", padx=2, pady=(0, 6))
        self.scrollbar = ctk.CTkScrollbar(self, command=self.body.yview, width=12)
        self.body.configure(yscrollcommand=self._on_scroll)

        for widget in (self.header, self.body):
            widget.tag_configure("muted", foreground=MUTED)
            widget.tag_configure("secondary", foreground=SECONDARY)
            widget.tag_configure("good", foreground=GREEN)
            widget.tag_configure("name", font=self.fonts["name"])
            widget.tag_configure("number", font=self.fonts["number"])
        s = lambda value: round(value * scale)
        self.body.tag_configure("row", spacing1=s(7), spacing3=s(7))
        self.body.tag_configure("center", justify="center")
        self.body.tag_configure("title", font=self.fonts["title"], foreground=SECONDARY, spacing1=s(10))
        self.body.tag_configure("title_drop", font=self.fonts["title"], foreground=ACCENT, spacing1=s(10))
        self.body.tag_configure("hint", font=self.fonts["hint"], foreground=MUTED, spacing1=s(4))

        self.body.bind("<Configure>", lambda event: self._schedule_render())
        self._render()

    # ---------- що показати ----------

    def set_rows(self, rows):
        """rows: [(ім'я, розмір, стиснуто, відсоток, стиль)], стиль відсотка — "good", "muted" або None."""
        self.rows = list(rows)
        self._render()

    def set_drag_over(self, active):
        """Підсвітка, поки над вікном тримають перетягнуті файли."""
        self.drag_over = active
        self.configure(border_color=ACCENT if active else BORDER, border_width=2 if active else 1)
        if not self.rows:
            self._render()

    # ---------- малювання ----------

    def _make_text(self, height=None):
        text = tk.Text(self, bg=BG, fg=TEXT, font=self.fonts["body"], borderwidth=0, highlightthickness=0,
                       padx=round(PAD * self.scale), pady=0, wrap="none", cursor="arrow", takefocus=0,
                       selectbackground=BG, selectforeground=TEXT, inactiveselectbackground=BG,
                       insertwidth=0, height=height or 1, state="disabled")
        text.bind("<Button-1>", lambda event: "break")  # таблиця лише для перегляду
        return text

    def _schedule_render(self):
        # Під час зміни розміру вікна подій багато — перемальовуємо один раз, коли все вляжеться
        if self._render_job is not None:
            self.after_cancel(self._render_job)
        self._render_job = self.after(30, self._render)

    def _tab_stops(self):
        """Позиції правих країв колонок «Розмір», «Стиснуто», «%»."""
        width = self.body.winfo_width() - 2 * round(PAD * self.scale)
        size_w, packed_w, percent_w = (round(w * self.scale) for w in COLUMNS)
        percent_end = max(width - 2, size_w + packed_w + percent_w + 60)
        packed_end = percent_end - percent_w
        size_end = packed_end - packed_w
        return size_end, packed_end, percent_end

    def _render(self):
        self._render_job = None
        stops = self._tab_stops()
        tabs = [value for stop in stops for value in (stop, "right")]
        for widget in (self.header, self.body):
            widget.configure(state="normal", tabs=tabs)
            widget.delete("1.0", "end")

        self.header.insert("end", "Файл\tРозмір\tСтиснуто\t%", "secondary")
        if self.rows:
            name_width = stops[0] - round(COLUMNS[0] * self.scale) - round(28 * self.scale)
            for row in self.rows:
                self._insert_row(row, name_width)
        else:
            self._insert_placeholder()
        for widget in (self.header, self.body):
            widget.configure(state="disabled")

    def _insert_row(self, row, name_width):
        name, size, packed, percent, style = row
        text = self.body
        start = text.index("end-1c")
        text.image_create("end", image=self._icon(icon_for(name)), align="center")
        text.insert("end", "  ")
        text.insert("end", self._fit(name, name_width), "name")
        for value in (size, packed):
            text.insert("end", "\t")
            self._insert_size(value)
        text.insert("end", "\t")
        text.insert("end", percent, style or ())
        text.insert("end", "\n")
        text.tag_add("row", start, "end-1c")

    def _insert_size(self, value):
        """«1.2 МБ»: число жирним, одиниця звичайним, як у макеті. «—» — сірим."""
        number, _, unit = value.partition(" ")
        if not unit:
            self.body.insert("end", value, "muted")
        else:
            self.body.insert("end", number, "number")
            self.body.insert("end", " " + unit)

    def _insert_placeholder(self):
        """Порожня таблиця: підказка посередині."""
        text = self.body
        if self.drag_over:
            title, hint, tag = "Відпустіть, щоб додати", "файли й папки потраплять у список", "title_drop"
        elif self.can_drop:
            title, hint, tag = "Перетягніть файли або папку сюди", "або натисніть «Додати файли»", "title"
        else:
            title, hint, tag = "Тут з'являться файли для архіву", "Натисніть «Додати файли» або «Додати папку»", "title"
        content = round(40 * self.scale) + self.fonts["title"].metrics("linespace") \
            + self.fonts["hint"].metrics("linespace") + round(14 * self.scale)
        top = max(0, (self.body.winfo_height() - content) // 2)
        text.tag_configure("top", spacing1=top)
        text.image_create("end", image=self._icon("drag-drop", 40), align="center")
        text.insert("end", "\n" + title, tag)
        text.insert("end", "\n" + hint, "hint")
        text.tag_add("center", "1.0", "end")
        text.tag_add("top", "1.0", "1.end")

    def _fit(self, name, width):
        """Обрізає задовге ім'я з «…» посередині, щоб не налізало на колонку «Розмір»."""
        font = self.fonts["name"]
        if font.measure(name) <= width:
            return name
        keep_end = min(len(Path(name).suffix) + 4, len(name) // 2)
        head, tail = name[:-keep_end], name[-keep_end:]
        while head and font.measure(head + "…" + tail) > width:
            head = head[:-1]
        return head + "…" + tail

    def _icon(self, name, size=16):
        if (name, size) not in self.icons:
            self.icons[name, size] = load_icon(self, name, size)
        return self.icons[name, size]

    def _on_scroll(self, first, last):
        # Смугу прокрутки показуємо лише тоді, коли рядки не вміщуються. Сховану не оновлюємо:
        # customtkinter щоразу перемальовує її повністю, а під час зміни розміру вікна це гальмує.
        if float(first) <= 0 and float(last) >= 1:
            self.scrollbar.grid_remove()
        else:
            self.scrollbar.grid(row=2, column=1, sticky="ns", padx=(0, 4), pady=(0, 6))
            self.scrollbar.set(first, last)
