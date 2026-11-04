"""
Оформлення: кольори, шрифти й іконки — спільні для головного вікна та інструкції.

Шрифт Montserrat і іконки лежать у папці assets, тож програма виглядає однаково
на будь-якому комп'ютері, навіть якщо там такого шрифту не встановлено.
"""

import ctypes
import sys
import tkinter as tk
from pathlib import Path

import customtkinter as ctk

ASSETS = Path(__file__).parent / "assets"

BG = "#1a1a19"          # фон вікна
CARD = "#151515"        # картки статистики, доріжка прогрес-бару
PANEL = "#222221"       # картка з підказкою в інструкції
BORDER = "#3a3a38"
HOVER = "#262625"
TEXT = "#f0efec"
SECONDARY = "#c3c2b7"   # підписи й заголовки
MUTED = "#898781"       # другорядне: «—», «без стиснення»
ACCENT = "#2a78d6"
ACCENT_HOVER = "#2368bd"
GREEN = "#0ca311"


FONT_NAME = "Montserrat"  # файли assets/fonts/<назва>-Regular.ttf, -Medium.ttf, -SemiBold.ttf


def _load_fonts():
    """Підключає шрифт з assets/fonts лише для цієї програми (у систему його не встановлює)."""
    names = (f"{FONT_NAME}-Regular.ttf", f"{FONT_NAME}-Medium.ttf", f"{FONT_NAME}-SemiBold.ttf")
    return all(ctk.FontManager.load_font(str(ASSETS / "fonts" / name)) for name in names)


# Насиченість задаємо назвою шрифту: Tkinter знає лише «звичайний» і «жирний»
if _load_fonts():
    FONT, FONT_MEDIUM, FONT_SEMIBOLD = FONT_NAME, f"{FONT_NAME} Medium", f"{FONT_NAME} SemiBold"
elif sys.platform == "win32":  # запасний варіант, якщо файлів шрифту немає
    FONT, FONT_MEDIUM, FONT_SEMIBOLD = "Segoe UI", "Segoe UI Semibold", "Segoe UI Semibold"
else:
    FONT = FONT_MEDIUM = FONT_SEMIBOLD = "Roboto"  # входить у customtkinter


# Іконки Tabler Icons намальовані заздалегідь у кількох розмірах, під масштаб екрана 100–200 %
ICON_SCALES = (1, 1.25, 1.5, 1.75, 2)


def load_icon(widget, name, size=16):
    """Картинка assets/icons/<name>-<висота в пікселях>.png, найближча до потрібного розміру на цьому екрані."""
    wanted = size * ctk.ScalingTracker.get_widget_scaling(widget)
    pixels = min({round(size * scale) for scale in ICON_SCALES}, key=lambda px: abs(px - wanted))
    return tk.PhotoImage(master=widget, file=ASSETS / "icons" / f"{name}-{pixels}.png")


def set_window_icon(window):
    """Значок у заголовку вікна і на панелі задач."""
    if sys.platform == "win32":
        window.iconbitmap(ASSETS / "app.ico")
    else:
        window.iconphoto(True, tk.PhotoImage(master=window, file=ASSETS / "app.png"))


def smooth_resize(window):
    """
    Windows: Tkinter створює вікна зі стилем «при будь-якій зміні розміру перемалювати все».
    Тоді під час розтягування вікна кожна кнопка малюється заново на кожному кроці,
    навіть якщо вона не змінилась, і вікно тягнеться ривками (~12 кадрів за секунду).
    Прибираємо цей стиль: віджети, розмір яких справді змінився, Tkinter перемальовує й сам.
    """
    if sys.platform != "win32":
        return
    user32 = ctypes.WinDLL("user32")
    get_style = getattr(user32, "GetClassLongPtrW", None) or user32.GetClassLongW  # 64 / 32 біти
    set_style = getattr(user32, "SetClassLongPtrW", None) or user32.SetClassLongW
    get_style.restype = set_style.restype = ctypes.c_size_t
    get_style.argtypes = [ctypes.c_void_p, ctypes.c_int]
    set_style.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_size_t]
    user32.GetParent.restype = ctypes.c_void_p
    user32.GetParent.argtypes = [ctypes.c_void_p]
    GCL_STYLE, CS_VREDRAW, CS_HREDRAW = -26, 0x1, 0x2
    # Стиль належить «класу» вікон, тож досить змінити його один раз для рамки вікна
    # і один раз для внутрішніх віджетів — це діє на всі вікна програми
    for hwnd in (user32.GetParent(window.winfo_id()), window.winfo_id()):
        set_style(hwnd, GCL_STYLE, get_style(hwnd, GCL_STYLE) & ~(CS_HREDRAW | CS_VREDRAW))


def match_titlebar(window):
    """Windows 11: фарбує заголовок вікна в колір фону, щоб він не виділявся. На інших системах нічого не робить."""
    if sys.platform != "win32":
        return
    DWMWA_CAPTION_COLOR = 35
    red, green, blue = (int(BG[i:i + 2], 16) for i in (1, 3, 5))
    color = ctypes.c_int(red | green << 8 | blue << 16)  # формат Windows: 0x00BBGGRR
    hwnd = ctypes.windll.user32.GetParent(window.winfo_id())
    ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, DWMWA_CAPTION_COLOR, ctypes.byref(color), ctypes.sizeof(color))
