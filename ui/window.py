"""
Головне вікно архіватора (бібліотека customtkinter).

Важка робота (стиснення, шифрування) виконується в окремому потоці,
щоб вікно не «зависало». Фоновий потік не чіпає віджети напряму —
він кладе повідомлення в чергу, а вікно кожні 50 мс забирає їх і оновлює екран.

Файли можна додати кнопками або просто перетягнути у вікно (бібліотека tkinterdnd2).
"""

import os
import queue
import subprocess
import sys
import threading
import time
import warnings
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox

import customtkinter as ctk

from core import archive, crypto

from . import tutorial
from .file_table import FileTable
from .theme import (ACCENT, ACCENT_HOVER, BG, BORDER, CARD, FONT, FONT_MEDIUM, GREEN, HOVER, MUTED, SECONDARY,
                   TEXT, load_icon, match_titlebar, set_window_icon, smooth_resize)

try:
    from tkinterdnd2 import DND_FILES, TkinterDnD
    DnDWrapper = TkinterDnD.DnDWrapper
except ImportError:  # бібліотеку не встановлено — програма працює, лише без перетягування
    TkinterDnD, DnDWrapper = None, object

# Іконки — звичайні PNG у кількох розмірах (див. theme.load_icon), тому попередження
# customtkinter «картинка не CTkImage» тут зайве
warnings.filterwarnings("ignore", message=".*Given image is not CTkImage")

ARCHIVE_TYPES = [("Архів Хаффмана", "*.huf"), ("Усі файли", "*.*")]


def open_folder(path):
    """Відкриває папку у файловому менеджері системи."""
    if sys.platform == "win32":
        os.startfile(path)
    elif sys.platform == "darwin":
        subprocess.Popen(["open", path])
    else:
        subprocess.Popen(["xdg-open", path])


def show_in_folder(path):
    """Відкриває папку, де лежить файл, і виділяє сам файл (на Linux — просто папку)."""
    path = os.path.normpath(path)
    if sys.platform == "win32":
        subprocess.Popen(f'explorer /select,"{path}"')
    elif sys.platform == "darwin":
        subprocess.Popen(["open", "-R", path])
    else:
        subprocess.Popen(["xdg-open", os.path.dirname(path)])


def format_size(size):
    """1234567 -> "1.2 МБ"."""
    value = float(size)
    for unit in ("Б", "КБ", "МБ", "ГБ"):
        if value < 1024 or unit == "ГБ":
            break
        value /= 1024
    if unit == "Б" or value >= 10:
        return f"{value:.0f} {unit}"
    return f"{value:.1f} {unit}"


class App(ctk.CTk, DnDWrapper):
    def __init__(self):
        ctk.set_appearance_mode("dark")
        super().__init__(fg_color=BG)
        self.title("Huffman Archiver")
        self.geometry("700x600")
        self.minsize(600, 520)
        set_window_icon(self)

        self.files = []              # [(шлях, ім'я в архіві)] — що будемо архівувати
        self.events = queue.Queue()  # повідомлення від фонового потоку
        self.busy = False
        self.font = ctk.CTkFont(family=FONT, size=14)
        self.small_font = ctk.CTkFont(family=FONT, size=12)
        self.value_font = ctk.CTkFont(family=FONT_MEDIUM, size=20)
        self.can_drop = self._enable_drop()

        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)
        self._build_toolbar()
        self._build_table()
        self._build_actions()
        self._build_progress()
        self._build_stats()
        match_titlebar(self)
        smooth_resize(self)

        self.tour = None
        if tutorial.is_first_launch():
            self.after(500, self.start_tutorial)  # трохи чекаємо, поки вікно з'явиться на екрані
        self._poll_events()

    # ---------- побудова вікна ----------

    def _button(self, master, text, icon, command, accent=False):
        """Кнопка з іконкою зліва: синя (головна дія) або з рамкою."""
        if accent:
            colors = dict(fg_color=ACCENT, hover_color=ACCENT_HOVER, text_color="#ffffff", border_width=0)
        else:
            colors = dict(fg_color="transparent", hover_color=HOVER, text_color=TEXT,
                          border_width=1, border_color=BORDER)
        return ctk.CTkButton(master, text=text, image=load_icon(self, icon), compound="left", command=command,
                             font=self.font, width=0, height=36, corner_radius=8, **colors)

    def _row(self, row, pady):
        """
        Невидимий рядок на всю ширину вікна, у який складаємо кнопки чи картки.
        Звичайний tk.Frame, а не CTkFrame: customtkinter перемальовував би його при кожній
        зміні розміру вікна. Відступи tk.Frame не масштабує сам, тому множимо їх на масштаб екрана.
        """
        scale = ctk.ScalingTracker.get_widget_scaling(self)
        frame = tk.Frame(self, bg=BG)
        frame.grid(row=row, column=0, sticky="ew", padx=round(20 * scale), pady=[round(p * scale) for p in pady])
        return frame

    def _build_toolbar(self):
        bar = self._row(0, pady=(18, 12))
        self.add_files_button = self._button(bar, "Додати файли", "file-plus", self.add_files)
        self.add_folder_button = self._button(bar, "Додати папку", "folder-plus", self.add_folder)
        self.clear_button = self._button(bar, "Очистити", "trash", self.clear)
        for column, button in enumerate((self.add_files_button, self.add_folder_button, self.clear_button)):
            button.grid(row=0, column=column, padx=(0, 8))

        # Кнопка «?» праворуч — відкриває інструкцію
        bar.grid_columnconfigure(3, weight=1)
        self.help_button = ctk.CTkButton(bar, text="?", command=self.start_tutorial, width=36, height=36,
                                         font=ctk.CTkFont(family=FONT_MEDIUM, size=15),
                                         fg_color="transparent", hover_color=HOVER, border_width=1,
                                         border_color=BORDER, text_color=TEXT, corner_radius=18)
        self.help_button.grid(row=0, column=4)

    def _build_table(self):
        self.table = FileTable(self, can_drop=self.can_drop)
        self.table.grid(row=1, column=0, sticky="nsew", padx=20)

    def _build_actions(self):
        row = self._row(2, pady=(14, 14))
        row.grid_columnconfigure(1, weight=1)

        self.lock_icon = ctk.CTkLabel(row, text="", image=load_icon(self, "lock", 18), width=22)
        self.lock_icon.grid(row=0, column=0, padx=(0, 10))
        # «●», а не «•»: у Montserrat звичайна точка дуже дрібна, а цього знака в ньому немає,
        # тож Windows візьме його з системного шрифту
        self.password = ctk.CTkEntry(row, placeholder_text="Пароль (порожньо — без шифрування)", show="●",
                                     font=self.font, height=36, corner_radius=8, fg_color=BG, border_width=1,
                                     border_color=BORDER, text_color=TEXT, placeholder_text_color=MUTED)
        self.password.grid(row=0, column=1, sticky="ew", padx=(0, 10))

        self.create_button = self._button(row, "Створити архів", "archive", self.create_archive, accent=True)
        self.create_button.grid(row=0, column=2, padx=(0, 8))
        self.extract_button = self._button(row, "Розпакувати", "package-export", self.extract_archive)
        self.extract_button.grid(row=0, column=3)

    def _build_progress(self):
        self.progress = ctk.CTkProgressBar(self, height=6, corner_radius=3, fg_color=CARD, progress_color=ACCENT)
        self.progress.grid(row=3, column=0, sticky="ew", padx=20)
        self._reset_progress()
        self.status = ctk.CTkLabel(self, text="Додайте файли або відкрийте архів", font=self.small_font,
                                   text_color=SECONDARY, anchor="w", justify="left")
        self.status.grid(row=4, column=0, sticky="ew", padx=20, pady=(6, 12))
        # Довгі повідомлення переносимо на новий рядок. Ширину беремо від самого вікна, а не від
        # напису: інакше перенесення змінює ширину напису, а та — перенесення, і так по колу.
        self.bind("<Configure>", self._wrap_status, add="+")

    def _wrap_status(self, event):
        if event.widget is self:
            width = event.width / ctk.ScalingTracker.get_widget_scaling(self) - 2 * 20  # мінус відступи
            self.status.configure(wraplength=max(width, 100))

    def _build_stats(self):
        row = self._row(5, pady=(0, 20))
        self.stats_row = row
        self.stats = {}
        for column, (key, title) in enumerate([("before", "Було"), ("after", "Стало"),
                                               ("time", "Час"), ("crypto", "Шифрування")]):
            row.grid_columnconfigure(column, weight=1, uniform="stats")
            card = ctk.CTkFrame(row, fg_color=CARD, corner_radius=8)
            card.grid(row=0, column=column, sticky="ew", padx=(0 if column == 0 else 10, 0))
            # Написи не розтягуємо на всю картку (anchor замість fill): тоді при зміні розміру
            # вікна вони лишаються як є і їх не треба перемальовувати
            ctk.CTkLabel(card, text=title, font=self.small_font, text_color=SECONDARY,
                         height=16).pack(anchor="w", padx=14, pady=(10, 0))
            value = ctk.CTkLabel(card, text="—", font=self.value_font, text_color=TEXT, height=28)
            value.pack(anchor="w", padx=14, pady=(0, 10))
            self.stats[key] = value

    # ---------- перетягування файлів (drag & drop) ----------

    def _enable_drop(self):
        """
        Вмикає перетягування файлів у вікно. Tkinter сам цього не вміє, тому підключаємо
        розширення tkdnd (бібліотека tkinterdnd2). Повертає False, якщо його немає.
        """
        if TkinterDnD is None:
            return False
        try:
            TkinterDnD._require(self)  # завантажує tkdnd у Tcl-інтерпретатор вікна
        except RuntimeError:
            return False
        self.drop_target_register(DND_FILES)  # вікно приймає файли з Провідника
        self.dnd_bind("<<DropEnter>>", self._on_drag_enter)
        self.dnd_bind("<<DropLeave>>", self._on_drag_leave)
        self.dnd_bind("<<Drop>>", self._on_drop)
        return True

    def _on_drag_enter(self, event):
        self.table.set_drag_over(True)
        return event.action

    def _on_drag_leave(self, event):
        self.table.set_drag_over(False)
        return event.action

    def _on_drop(self, event):
        self.table.set_drag_over(False)
        # Шляхи приходять одним рядком: "C:/a.txt {C:/папка з пробілами}" — splitlist розбирає його
        paths = self.tk.splitlist(event.data)
        if not self.busy:
            # Обробляємо трохи згодом: поки ця функція не завершилась, Провідник чекає на нас
            self.after(10, lambda: self._add_dropped(paths))
        return event.action

    def _add_dropped(self, paths):
        if not self._add_paths(paths, self.add_files_button):
            self.status.configure(text="Нічого не додано: серед перетягнутого немає файлів")

    # ---------- дії кнопок ----------

    def start_tutorial(self):
        if self.tour is None or not self.tour.active:
            self.tour = tutorial.Tour(self)
        else:
            self._tutorial_step_done(self.help_button)  # «?» на останньому кроці закриває інструкцію

    def _tutorial_step_done(self, button):
        """Дію виконано: якщо інструкція саме підсвічує цю кнопку, вона перейде до наступного кроку."""
        if self.tour is not None:
            self.tour.done(button)

    def add_files(self):
        paths = filedialog.askopenfilenames(title="Виберіть файли")
        if paths:
            self._add_paths(paths, self.add_files_button)

    def add_folder(self):
        folder = filedialog.askdirectory(title="Виберіть папку")
        if not folder:
            return
        sources = archive.collect_files([folder])
        if not sources:
            messagebox.showinfo("Архіватор", "У цій папці немає файлів.")
            return
        self._add_sources(sources)
        self._tutorial_step_done(self.add_folder_button)

    def clear(self):
        self.files = []
        self._show_files()
        self._show_stats("—", "—", "—", None)
        self._reset_progress()
        self.status.configure(text="Додайте файли або відкрийте архів")
        self._tutorial_step_done(self.clear_button)

    def create_archive(self):
        if not self.files:
            messagebox.showinfo("Архіватор", "Спершу додайте файли або папку.")
            return
        path = filedialog.asksaveasfilename(title="Зберегти архів як", defaultextension=".huf",
                                            filetypes=ARCHIVE_TYPES, initialfile="archive.huf")
        if not path:
            return
        password = self.password.get()
        files = list(self.files)
        self._run_in_background(
            lambda report: archive.create_archive(files, path, password, report),
            lambda entries, seconds: self._on_created(entries, path, bool(password), seconds))

    def extract_archive(self):
        path = filedialog.askopenfilename(title="Виберіть архів", filetypes=ARCHIVE_TYPES)
        if not path:
            return
        try:
            encrypted = archive.is_encrypted(path)
        except (archive.ArchiveError, OSError) as error:
            messagebox.showerror("Помилка", str(error))
            return
        password = self.password.get()
        if encrypted and not password:
            messagebox.showwarning("Потрібен пароль", "Цей архів зашифровано. Введіть пароль і спробуйте ще раз.")
            self.password.focus()
            return
        out_dir = filedialog.askdirectory(title="Куди розпакувати?", initialdir=str(Path(path).parent))
        if not out_dir:
            return
        self._run_in_background(
            lambda report: archive.extract_archive(path, out_dir, password, report),
            lambda result, seconds: self._on_extracted(result, path, encrypted, seconds))

    def _add_paths(self, paths, button):
        """
        Додає вибрані або перетягнуті файли й папки. Якщо серед них є архів .huf —
        спершу питаємо: найчастіше його хочуть розпакувати, а не запакувати ще раз.
        Повертає True, якщо щось додано.
        """
        archives = [path for path in paths if Path(path).suffix.lower() == ".huf" and Path(path).is_file()]
        if archives:
            names = ", ".join(Path(path).name for path in archives[:3]) + (" …" if len(archives) > 3 else "")
            what = "це вже архів" if len(archives) == 1 else "це вже архіви"
            if not messagebox.askyesno("Це вже архів",
                                       f"{names} — {what}.\nЩоб дістати з нього файли, натисніть «Розпакувати».\n\n"
                                       "Все одно додати в новий архів?"):
                paths = [path for path in paths if path not in archives]
        sources = archive.collect_files(paths)
        if not sources:
            return False
        self._add_sources(sources)
        self._tutorial_step_done(button)
        return True

    # ---------- результати ----------

    def _on_created(self, entries, path, encrypted, seconds):
        self._show_entries(entries)
        before = sum(entry.original_size for entry in entries)
        after = Path(path).stat().st_size
        self._show_stats(format_size(before), format_size(after), f"{seconds:.1f} с", encrypted)

        message = f"{Path(path).name} ({format_size(after)}) збережено в папці:\n{Path(path).parent}"
        if after > before:
            # Чесно пояснюємо, чому «стало» більше, ніж «було», — інакше схоже на помилку
            service = "імена, розміри, контрольні суми" + (", дані для перевірки пароля" if encrypted else "")
            note = (f"Архів більший за файли на {format_size(after - before)}: стискати тут було нічого "
                    f"(файли замалі або вже стиснуті), а службові дані ({service}) теж займають місце.")
            self.status.configure(text=note)
            message += "\n\n" + note
        else:
            self.status.configure(text=f"Архів створено: {path}")
        message += "\n\nЩоб перевірити архів, натисніть «Розпакувати».\n\nВідкрити папку з архівом?"
        if messagebox.askyesno("Архів створено", message):
            show_in_folder(path)
        self._tutorial_step_done(self.create_button)

    def _on_extracted(self, result, path, encrypted, seconds):
        target_dir, entries = result
        self.files = []  # таблиця тепер показує вміст архіву, а не список для архівування
        self._show_entries(entries)
        after = sum(entry.original_size for entry in entries)
        self._show_stats(format_size(Path(path).stat().st_size), format_size(after), f"{seconds:.1f} с", encrypted)
        self.status.configure(text=f"Розпаковано в: {target_dir}")
        if messagebox.askyesno("Готово", f"Файли розпаковано в:\n{target_dir}\n\nВідкрити папку?"):
            open_folder(target_dir)
        self._tutorial_step_done(self.extract_button)

    def _add_sources(self, sources):
        known = {path for path, _ in self.files}
        self.files += [(path, name) for path, name in sources if path not in known]
        self._show_files()

    def _show_files(self):
        self.table.set_rows((name, format_size(path.stat().st_size), "—", "—", "muted") for path, name in self.files)
        self.status.configure(text=f"Файлів у списку: {len(self.files)}")

    def _show_entries(self, entries):
        rows = []
        for entry in entries:
            if entry.method == archive.HUFFMAN:
                saved = 1 - entry.packed_size / entry.original_size
                percent, style = f"−{saved:.0%}", "good"  # зеленим
            else:
                percent, style = "без стиснення", "muted"  # сірим
            rows.append((entry.name, format_size(entry.original_size), format_size(entry.packed_size), percent, style))
        self.table.set_rows(rows)

    def _show_stats(self, before, after, seconds, encrypted):
        self.stats["before"].configure(text=before)
        self.stats["after"].configure(text=after)
        self.stats["time"].configure(text=seconds)
        if encrypted is None:
            self.stats["crypto"].configure(text="—", text_color=TEXT)
        elif encrypted:
            self.stats["crypto"].configure(text="AES-256", text_color=GREEN)
        else:
            self.stats["crypto"].configure(text="немає", text_color=MUTED)

    # ---------- фонова робота ----------

    def _run_in_background(self, job, on_done):
        """Запускає job(report) в окремому потоці; on_done(результат, секунди) викличеться у вікні."""
        self._set_busy(True)
        started = time.perf_counter()

        def worker():
            try:
                result = job(self._report_progress)
                self.events.put(("done", (on_done, result, time.perf_counter() - started)))
            except (archive.ArchiveError, crypto.WrongPasswordError, OSError) as error:
                self.events.put(("error", str(error)))
            except Exception as error:
                self.events.put(("error", f"Неочікувана помилка: {error!r}"))

        threading.Thread(target=worker, daemon=True).start()

    def _report_progress(self, fraction, message):
        # Викликається з фонового потоку, тому лише кладемо повідомлення в чергу
        self.events.put(("progress", (fraction, message)))

    def _poll_events(self):
        try:
            while True:
                kind, value = self.events.get_nowait()
                if kind == "progress":
                    fraction, message = value
                    self.progress.set(fraction)
                    self.status.configure(text=f"{message}… {fraction:.0%}")
                elif kind == "done":
                    on_done, result, seconds = value
                    self._set_busy(False)
                    self.progress.set(1)
                    on_done(result, seconds)
                elif kind == "error":
                    self._set_busy(False)
                    self._reset_progress()
                    self.status.configure(text=value)
                    messagebox.showerror("Помилка", value)
        except queue.Empty:
            pass
        finally:
            self.after(50, self._poll_events)  # навіть після помилки продовжуємо слухати чергу

    def report_callback_exception(self, exc, value, traceback):
        # Без консолі (main.pyw) помилку не було б видно, тому показуємо її у вікні
        messagebox.showerror("Помилка", f"Неочікувана помилка: {value!r}")

    def _set_busy(self, busy):
        self.busy = busy
        state = "disabled" if busy else "normal"
        for button in (self.add_files_button, self.add_folder_button, self.clear_button,
                       self.create_button, self.extract_button):
            button.configure(state=state)
        if busy:
            self.progress.configure(progress_color=ACCENT)
            self.progress.set(0)

    def _reset_progress(self):
        # На нулі customtkinter усе одно малює синю крапку — ховаємо її кольором доріжки
        self.progress.configure(progress_color=CARD)
        self.progress.set(0)
