"""
Алгоритм Хаффмана: стиснення і розпакування байтів.

Ідея: байти, які трапляються часто, кодуємо короткими бітовими кодами,
а рідкісні — довгими. Коди беремо з дерева Хаффмана.

Формат стиснених даних:
    [довжина оригіналу: 8 байт]
    [кількість різних байтів N: 2 байти]
    N разів: [байт: 1 байт][скільки разів він трапився: 4 байти]
    [закодовані біти, доповнені нулями до цілого байта]
"""

import heapq
import struct
from collections import Counter

HEADER = struct.Struct("<QH")      # довжина оригіналу, кількість різних байтів
FREQ_ENTRY = struct.Struct("<BI")  # байт, його частота
CHUNK_SIZE = 256 * 1024            # обробляємо дані шматками, щоб показувати прогрес


def build_tree(freq):
    """
    Будує дерево Хаффмана за таблицею частот {байт: кількість}.

    Лист дерева — просто число (байт), внутрішній вузол — пара (лівий, правий).
    Беремо два найрідші вузли, об'єднуємо в новий з сумарною частотою
    і повторюємо, поки не залишиться один вузол — корінь.
    """
    # Сортуємо, щоб дерево будувалося однаково і при стисненні, і при розпакуванні.
    # Номер order потрібен, щоб при рівних частотах heapq не порівнював самі вузли.
    heap = [(count, order, symbol) for order, (symbol, count) in enumerate(sorted(freq.items()))]
    heapq.heapify(heap)

    if len(heap) == 1:
        # Особливий випадок: у даних лише один різний байт (наприклад, "aaaa").
        # Робимо корінь з двома однаковими листками, щоб код мав довжину 1 біт.
        symbol = heap[0][2]
        return (symbol, symbol)

    order = len(heap)
    while len(heap) > 1:
        count1, _, left = heapq.heappop(heap)
        count2, _, right = heapq.heappop(heap)
        heapq.heappush(heap, (count1 + count2, order, (left, right)))
        order += 1
    return heap[0][2]


def make_codes(node, prefix="", codes=None):
    """Обходить дерево і повертає коди {байт: "0101..."}: крок вліво — "0", вправо — "1"."""
    if codes is None:
        codes = {}
    if isinstance(node, int):
        codes[node] = prefix
    else:
        make_codes(node[0], prefix + "0", codes)
        make_codes(node[1], prefix + "1", codes)
    return codes


def compress(data, on_progress=None):
    """
    Стискає байти data. Повертає None, якщо стиснення не зменшить розмір
    (порожні файли або вже стиснуті формати: JPG, MP4, ZIP).
    on_progress(частка) викликається з числом від 0 до 1.
    """
    if not data:
        return None

    freq = Counter(data)
    codes = make_codes(build_tree(freq))
    header = HEADER.pack(len(data), len(freq))
    table = b"".join(FREQ_ENTRY.pack(symbol, count) for symbol, count in sorted(freq.items()))

    # Розмір результату відомий ще до кодування: кожен байт займе
    # стільки бітів, яка довжина його коду. Якщо виграшу немає — не стискаємо.
    total_bits = sum(count * len(codes[symbol]) for symbol, count in freq.items())
    if len(header) + len(table) + (total_bits + 7) // 8 >= len(data):
        return None

    code_of = [""] * 256  # список швидший за словник: code_of[байт] -> "0101"
    for symbol, code in codes.items():
        code_of[symbol] = code

    out = bytearray(header + table)
    leftover = ""  # біти, яких не вистачило на цілий байт, переносимо в наступний шматок
    for start in range(0, len(data), CHUNK_SIZE):
        chunk = data[start:start + CHUNK_SIZE]
        bits = leftover + "".join([code_of[byte] for byte in chunk])
        whole = len(bits) // 8 * 8
        if whole:
            # Рядок з "0" і "1" -> число -> байти
            out += int(bits[:whole], 2).to_bytes(whole // 8, "big")
        leftover = bits[whole:]
        if on_progress:
            on_progress(min(1.0, (start + CHUNK_SIZE) / len(data)))

    if leftover:
        out += int(leftover.ljust(8, "0"), 2).to_bytes(1, "big")
    return bytes(out)


def decompress(blob, on_progress=None):
    """
    Розпаковує дані, стиснуті функцією compress().

    Класичне декодування йде по одному біту: від кореня вліво/вправо до листа.
    У Python це повільно, тому ми читаємо одразу цілий байт (8 бітів)
    і запам'ятовуємо результат у таблиці steps: «стоячи у вузлі node
    і прочитавши байт byte, отримаємо такі-то символи й опинимося у вузлі X».
    Кожна така комбінація обчислюється лише один раз.
    """
    length, symbol_count = HEADER.unpack_from(blob, 0)
    if length == 0:
        return b""

    pos = HEADER.size
    freq = {}
    for _ in range(symbol_count):
        symbol, count = FREQ_ENTRY.unpack_from(blob, pos)
        freq[symbol] = count
        pos += FREQ_ENTRY.size

    # Відновлюємо те саме дерево, що було при стисненні, — для цього й зберігали частоти.
    nodes = _flatten(build_tree(freq))
    body = blob[pos:]

    out = bytearray()
    steps = [None] * (len(nodes) * 256)
    node = 0  # корінь
    for start in range(0, len(body), CHUNK_SIZE):
        for byte in body[start:start + CHUNK_SIZE]:
            key = node * 256 + byte
            step = steps[key]
            if step is None:
                step = steps[key] = _walk(nodes, node, byte)
            symbols, node = step
            out += symbols
        if on_progress:
            on_progress(min(1.0, (start + CHUNK_SIZE) / len(body)))

    if len(out) < length:
        raise ValueError("Стиснені дані пошкоджено")
    # Біти-доповнення в останньому байті могли дати «зайві» символи — відрізаємо їх.
    return bytes(out[:length])


def _flatten(root):
    """
    Перетворює дерево на список вузлів nodes[i] = (лівий, правий).
    Дитина >= 0 — номер іншого вузла, дитина < 0 — лист з байтом (-дитина - 1).
    Корінь завжди має номер 0.
    """
    nodes = []

    def visit(node):
        if isinstance(node, int):
            return -node - 1
        index = len(nodes)
        nodes.append(None)  # резервуємо місце, щоб батьківський вузол мав менший номер
        nodes[index] = (visit(node[0]), visit(node[1]))
        return index

    visit(root)
    return nodes


def _walk(nodes, node, byte):
    """
    Проходить деревом 8 бітів одного байта, починаючи з вузла node.
    Повертає (розкодовані байти, вузол, на якому зупинились).
    """
    found = bytearray()
    for shift in range(7, -1, -1):
        child = nodes[node][(byte >> shift) & 1]
        if child < 0:  # дійшли до листа — це один розкодований байт
            found.append(-child - 1)
            node = 0   # наступний код знову читаємо від кореня
        else:
            node = child
    return bytes(found), node
