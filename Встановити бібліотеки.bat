@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo Встановлення бібліотек для Huffman Archiver...
echo.
py -m pip install -r requirements.txt
if errorlevel 1 (
    echo.
    echo Не вдалося. Перевірте, що встановлено Python 3.10 або новіший: https://www.python.org/downloads/
) else (
    echo.
    echo Готово! Тепер двічі клацніть по файлу main.pyw
)
echo.
pause
