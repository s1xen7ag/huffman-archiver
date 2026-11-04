"""
Інструкція «як у іграх»: покрокові підказки, як користуватися програмою.

Вікно затемнюється, потрібна кнопка підсвічується, а поруч з'являється картка
з поясненням. Кроки перемикаються кнопками «Далі» / «Назад» або стрілками
на клавіатурі, Esc — пропустити. Якщо натиснути саму підсвічену кнопку,
після виконаної дії інструкція перейде далі сама. При першому запуску
інструкція відкривається сама, потім — за кнопкою «?».

Як зроблено затемнення: у Tkinter не буває напівпрозорих віджетів, зате бувають
напівпрозорі вікна. Тому навколо підсвіченої кнопки ставимо 4 темні вікна
без рамок (зверху, знизу, зліва, справа), і посередині лишається «віконце» з кнопкою.
"""

import ctypes
import json
import sys
import tkinter as tk
from pathlib import Path

import customtkinter as ctk

from .theme import ACCENT, ACCENT_HOVER, BORDER, FONT, FONT_SEMIBOLD, HOVER, MUTED, PANEL, SECONDARY, TEXT, load_icon

SETTINGS_FILE = Path.home() / ".huffman_archiver.json"  # тут запам'ятовуємо, що інструкцію вже бачили
HOLE_PADDING = 6  # відступ підсвітки навколо кнопки
GAP = 12          # відстань від підсвітки до картки з підказкою


def is_first_launch():
    try:
        return not json.loads(SETTINGS_FILE.read_text("utf-8")).get("tutorial_done")
    except (OSError, ValueError, AttributeError):
        return True


def remember_done():
    try:
        SETTINGS_FILE.write_text(json.dumps({"tutorial_done": True}), "utf-8")
    except OSError:
        pass  # не вдалося зберегти — нічого страшного, інструкція просто покажеться ще раз


def keep_above(window, owner):
    """
    Робить вікно «підлеглим» головному: Windows тоді завжди тримає його над
    головним вікном (навіть якщо клікнути по програмі) і ховає разом з ним.
    Для вікон без рамки Tkinter цього сам не робить, тому звертаємось до WinAPI.
    """
    if sys.platform != "win32":
        return
    user32 = ctypes.WinDLL("user32")
    user32.GetAncestor.restype = ctypes.c_void_p
    user32.GetAncestor.argtypes = [ctypes.c_void_p, ctypes.c_uint]
    set_long = getattr(user32, "SetWindowLongPtrW", None) or user32.SetWindowLongW  # 64 / 32 біти
    set_long.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_void_p]
    GA_ROOT, GWLP_HWNDPARENT = 2, -8
    set_long(user32.GetAncestor(window.winfo_id(), GA_ROOT), GWLP_HWNDPARENT,
             user32.GetAncestor(owner.winfo_id(), GA_ROOT))


def build_steps(app):
    """Кроки інструкції: (віджети для підсвітки, заголовок, текст). None — без підсвітки."""
    return [
        (None, "Вітаємо в Huffman Archiver!",
         "Ця коротка інструкція покаже, як користуватися програмою і яка кнопка за що відповідає.\n\n"
         "Гортайте кнопками внизу або стрілками ← → на клавіатурі. Підсвічену кнопку можна "
         "одразу натиснути: коли дію виконано, підказка сама перейде далі."),
        ([app.add_files_button, app.add_folder_button], "Крок 1. Додайте файли",
         "«Додати файли» — вибрати один або кілька файлів.\n"
         "«Додати папку» — взяти всі файли з папки разом з підпапками.\n"
         + ("Або просто перетягніть файли у вікно з Провідника.\n" if app.can_drop else "")
         + "\nСпробуйте: натисніть одну з кнопок."),
        ([app.table], "Список файлів",
         "Тут видно, що потрапить в архів. Після стиснення з'явиться, скільки місця зекономлено.\n\n"
         "Сірим позначено файли, які вже стиснуті (JPG, MP4, ZIP): вони зберігаються як є."),
        ([app.lock_icon, app.password], "Крок 2. Пароль (за бажанням)",
         "Введіть пароль, щоб зашифрувати архів AES-256.\n\n"
         "Без пароля такий архів не відкрити, тож не забудьте його! "
         "Залиште поле порожнім, якщо шифрування не потрібне."),
        ([app.create_button], "Крок 3. Створіть архів",
         "Виберіть, куди зберегти файл .huf, і програма стисне файли. Ваші оригінали не змінюються."),
        ([app.progress, app.status, app.stats_row], "Результат",
         "Смужка показує, що програма робить зараз. Картки внизу: розмір до і після, "
         "час роботи і чи зашифровано архів."),
        ([app.extract_button], "Розпакування",
         "Виберіть архів .huf і папку, куди розпакувати. Файли з'являться в новій папці, "
         "нічого не перезапишеться.\n\nДля зашифрованого архіву спершу введіть пароль."),
        ([app.clear_button], "Очистити",
         "Очищає список файлів, щоб почати з нуля."),
        ([app.help_button], "Готово!",
         "Якщо щось забудете, натисніть «?», і ця інструкція покажеться знову."),
    ]


class Tour:
    def __init__(self, app):
        self.app = app
        self.steps = build_steps(app)
        self.index = 0
        self.active = True
        self._last_geometry = None  # де було головне вікно, коли ми востаннє розставляли підказки
        self._positions = {}        # вікно -> (x, y, розмір): щоб швидко зсувати при перетягуванні

        self.shades = [self._make_window(bg="black", alpha=0.65) for _ in range(4)]
        for shade in self.shades:
            # Клік по затемненню передає йому фокус, і воно вилазить поверх картки. Тому одразу
            # після цього (after_idle) повертаємо фокус програмі, а картку піднімаємо наверх.
            shade.bind("<FocusIn>", lambda event: self.app.after_idle(self._nudge))
        self.card = self._make_window(bg=BORDER)
        self._build_card()

        keys = {"<Right>": self.next, "<Return>": self.next, "<Left>": self.back, "<Escape>": self.finish}
        self.key_bindings = []
        for key, action in keys.items():
            handler = lambda event, action=action: self._on_key(event, action)
            self.key_bindings.append((key, app.bind(key, handler, add="+")))
            self.card.bind(key, handler)

        # Подія <Configure> приходить на кожен рух чи зміну розміру головного вікна.
        # Обробник вішаємо на власний «тег», щоб потім прибрати його, не зачепивши customtkinter.
        self._tag = f"tour{id(self)}"
        app.bind_class(self._tag, "<Configure>", lambda event: self._follow())
        app.bindtags((self._tag,) + app.bindtags())

        self.show(0)

    # ---------- кнопки картки ----------

    def next(self):
        if self.index + 1 < len(self.steps):
            self.show(self.index + 1)
        else:
            self.finish()

    def back(self):
        if self.index > 0:
            self.show(self.index - 1)

    def done(self, widget):
        """Користувач сам натиснув підсвічену кнопку і дія вдалася — переходимо до наступного кроку."""
        if self.active and widget in (self.steps[self.index][0] or []):
            self.next()

    def _on_key(self, event, action):
        # У полі пароля стрілки рухають курсор, а не гортають інструкцію
        if isinstance(event.widget, tk.Entry) and event.keysym in ("Left", "Right"):
            return
        action()

    def _nudge(self):
        """Клік по затемненню: картка знову зверху, а її рамка коротко блимає — «дивись сюди»."""
        if not self.active:
            return
        self.app.focus_force()
        self.card.lift()
        self.card.configure(bg=ACCENT)
        self.app.after(300, lambda: self.active and self.card.configure(bg=BORDER))

    def finish(self):
        if not self.active:
            return
        self.active = False
        for key, funcid in self.key_bindings:
            self.app.unbind(key, funcid)
        self.app.bindtags(tuple(tag for tag in self.app.bindtags() if tag != self._tag))
        self.app.unbind_class(self._tag, "<Configure>")
        for window in self.shades + [self.card]:
            window.destroy()
        remember_done()

    # ---------- показ кроку ----------

    def show(self, index):
        self.index = index
        _, title, text = self.steps[index]

        # Індикатор прогресу: пройдені кроки сині, поточний — довга «таблетка»
        self.dots.delete("all")
        gap = round(5 * ctk.ScalingTracker.get_widget_scaling(self.app))
        x = 0
        for i in range(len(self.steps)):
            image = self.dot_images["step-current" if i == index else "step-done" if i < index else "step-todo"]
            self.dots.create_image(x, 0, image=image, anchor="nw")
            x += image.width() + gap
        self.dots.configure(width=x - gap, height=image.height())
        self.counter.configure(text=f"{index + 1} / {len(self.steps)}")

        self.title.configure(text=title)
        self.text.configure(text=text)
        last = index == len(self.steps) - 1
        self.next_button.configure(text="Зрозуміло!" if last else "Далі →")
        if last:
            self.skip_button.pack_forget()
        else:
            self.skip_button.pack(side="left")
        if index == 0:
            self.back_button.pack_forget()
        else:
            self.back_button.pack(side="right", padx=(0, 8))
        self._place()

    def _make_window(self, bg, alpha=None):
        window = tk.Toplevel(self.app, bg=bg)
        window.withdraw()              # покажемо, коли визначимо місце
        window.overrideredirect(True)  # без рамки і заголовка
        # Не викликаємо window.transient(): для вікон без рамки він заважає їх переміщувати.
        # Над головним вікном їх тримає keep_above().
        if alpha is not None:
            window.attributes("-alpha", alpha)
        return window

    def _build_card(self):
        font = ctk.CTkFont(family=FONT, size=13)
        body = ctk.CTkFrame(self.card, fg_color=PANEL, corner_radius=0)
        body.pack(padx=1, pady=1)  # 1 піксель фону картки виглядає як рамка

        top = ctk.CTkFrame(body, fg_color="transparent")
        top.pack(fill="x", padx=18, pady=(16, 6))
        # Крапки малюємо картинками на одному полотні. Якби кожна крапка була окремим віджетом,
        # при перемиканні кроку Windows на мить лишав би старі крапки поруч з новими.
        self.dot_images = {name: load_icon(self.app, name, 8) for name in ("step-done", "step-todo", "step-current")}
        self.dots = tk.Canvas(top, bg=PANEL, highlightthickness=0, bd=0)
        self.dots.pack(side="left")
        # Постійна ширина: цифри різної ширини, і без неї напис змінював би розмір на кожному кроці
        self.counter = ctk.CTkLabel(top, text="", font=ctk.CTkFont(family=FONT, size=12),
                                    text_color=MUTED, height=16, width=40, anchor="e")
        self.counter.pack(side="right")

        self.title = ctk.CTkLabel(body, text="", font=ctk.CTkFont(family=FONT_SEMIBOLD, size=18),
                                  text_color=TEXT, anchor="w", justify="left")
        self.title.pack(fill="x", padx=18)
        # Однакова ширина на всіх кроках: картка не «дихає» і лічильник не обрізається
        self.text = ctk.CTkLabel(body, text="", font=font, text_color=SECONDARY, width=370,
                                 anchor="w", justify="left", wraplength=370)
        self.text.pack(fill="x", padx=18, pady=(4, 16))

        buttons = ctk.CTkFrame(body, fg_color="transparent")
        buttons.pack(fill="x", padx=18, pady=(0, 16))
        self.skip_button = ctk.CTkButton(buttons, text="Пропустити", command=self.finish, font=font,
                                         width=90, height=32, fg_color="transparent", hover_color=HOVER,
                                         text_color=MUTED)
        self.skip_button.pack(side="left")
        self.next_button = ctk.CTkButton(buttons, text="Далі →", command=self.next, font=font,
                                         width=110, height=32, fg_color=ACCENT, hover_color=ACCENT_HOVER)
        self.next_button.pack(side="right")
        self.back_button = ctk.CTkButton(buttons, text="← Назад", command=self.back, font=font,
                                         width=90, height=32, fg_color="transparent", hover_color=HOVER,
                                         border_width=1, border_color=BORDER, text_color=TEXT)

    def _place(self):
        """Ставить затемнення навколо потрібних віджетів і картку з підказкою поруч."""
        ax, ay, aw, ah = self._last_geometry = self._app_geometry()
        widgets = self.steps[self.index][0]
        if widgets:
            x1 = max(ax, min(w.winfo_rootx() for w in widgets) - HOLE_PADDING)
            y1 = max(ay, min(w.winfo_rooty() for w in widgets) - HOLE_PADDING)
            x2 = min(ax + aw, max(w.winfo_rootx() + w.winfo_width() for w in widgets) + HOLE_PADDING)
            y2 = min(ay + ah, max(w.winfo_rooty() + w.winfo_height() for w in widgets) + HOLE_PADDING)
        else:  # без підсвітки — затемнюємо все вікно
            x1 = x2 = ax + aw // 2
            y1 = y2 = ay + ah // 2

        # Спершу картка: її новий текст уже на екрані, тож переставляємо її без затримки.
        # Ставимо під підсвіткою; якщо не влазить — над нею, інакше по центру
        self.card.update_idletasks()
        cw, ch = self.card.winfo_reqwidth(), self.card.winfo_reqheight()
        if not widgets:
            cx, cy = ax + (aw - cw) // 2, ay + (ah - ch) // 2
        else:
            cx = min(max(x1, ax + GAP), ax + aw - cw - GAP)
            if y2 + GAP + ch <= ay + ah:
                cy = y2 + GAP
            elif y1 - GAP - ch >= ay:
                cy = y1 - GAP - ch
            else:
                cy = ay + (ah - ch) // 2
        self._show_window(self.card, cx, cy)

        # 4 темні прямокутники навколо «віконця» (x1, y1)–(x2, y2)
        rects = [(ax, ay, aw, y1 - ay),            # зверху
                 (ax, y2, aw, ay + ah - y2),       # знизу
                 (ax, y1, x1 - ax, y2 - y1),       # зліва
                 (x2, y1, ax + aw - x2, y2 - y1)]  # справа
        for shade, (x, y, w, h) in zip(self.shades, rects):
            if w > 0 and h > 0:
                self._show_window(shade, x, y, f"{w}x{h}")
            else:
                shade.withdraw()
                self._positions.pop(shade, None)

        # Піднімаємо лише картку і лише тоді, коли всі вікна вже на місцях:
        # якщо викликати lift() раніше, Tkinter на Windows «забуває» переміщення,
        # а якщо піднімати й затемнення, картка на мить темніє.
        self.card.lift()

    def _show_window(self, window, x, y, size=""):
        """Показує вікно в точці (x, y). size — "ШxВ" або "", тоді розмір береться за вмістом."""
        self._positions[window] = (x, y, size)
        window.geometry(f"{size}+{x}+{y}")
        if window.state() == "withdrawn":
            window.deiconify()
            window.update_idletasks()  # даємо Tkinter створити справжнє вікно системи
            keep_above(window, self.app)
        window.update_idletasks()

    def _app_geometry(self):
        app = self.app
        return app.winfo_rootx(), app.winfo_rooty(), app.winfo_width(), app.winfo_height()

    def _follow(self):
        """Головне вікно посунули або змінили розмір — переставляємо підказки слідом."""
        if not self.active:
            return
        old, new = self._last_geometry, self._app_geometry()
        if new == old:
            return
        if old and old[2:] == new[2:]:
            # Вікно лише перетягують: зсуваємо готові вікна на ту саму відстань.
            # Це дуже швидко, тому підказки рухаються плавно разом з програмою.
            dx, dy = new[0] - old[0], new[1] - old[1]
            for window, (x, y, size) in list(self._positions.items()):
                self._positions[window] = (x + dx, y + dy, size)
                window.geometry(f"{size}+{x + dx}+{y + dy}")
            self._last_geometry = new
        else:
            self._place()  # змінився розмір вікна — розставляємо все заново
