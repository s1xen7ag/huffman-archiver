"""
Точка входу.

Розширення .pyw означає, що на Windows програма відкривається без чорного вікна консолі.
Запуск: подвійний клік по файлу, або в терміналі  py main.pyw  (Linux: python3 main.pyw).

Код програми лежить у двох папках:
    core/ — логіка: Хаффман, шифрування, формат архіву
    ui/   — вікно, таблиця, інструкція, оформлення
"""

import sys

# Не створюємо службові папки __pycache__ поруч з кодом: програма маленька,
# тож без них запускається так само швидко, а в папках чисто
sys.dont_write_bytecode = True

try:
    from ui.window import App
except ImportError as error:
    if error.name in ("tkinter", "_tkinter"):
        message = "Не знайдено Tkinter.\n\nНа Linux встановіть його командою:\nsudo apt install python3-tk"
    else:
        message = (f"Не знайдено бібліотеку: {error.name}\n\n"
                   "Встановіть залежності командою:\npip install -r requirements.txt")
    print(message)
    try:
        # Консолі може не бути, тому показуємо помилку ще й у віконці
        import tkinter
        from tkinter import messagebox
        root = tkinter.Tk()
        root.withdraw()
        messagebox.showerror("Huffman Archiver", message)
    except ImportError:
        pass
    sys.exit(1)

if __name__ == "__main__":
    App().mainloop()
