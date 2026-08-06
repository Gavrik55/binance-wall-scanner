import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import types

try:
    import requests  # noqa: F401
except ModuleNotFoundError:
    fake_requests = types.ModuleType("requests")
    fake_requests.get = lambda *_args, **_kwargs: None
    sys.modules["requests"] = fake_requests

try:
    import websockets  # noqa: F401
except ModuleNotFoundError:
    fake_websockets = types.ModuleType("websockets")
    fake_websockets.connect = None
    sys.modules["websockets"] = fake_websockets

import gui as guimod
import winsound

# 1) файл на месте -> проигрывается без исключений (SND_FILENAME путь)
assert os.path.isfile(guimod.APPEARED_SOUND_PATH)
guimod._play_beep("APPEARED")
print("OK: _play_beep('APPEARED') с файлом на месте не упал")

# 2) fallback: подделываем путь на несуществующий файл -> должен тихо
# откатиться на синтезированный тон, без исключений
orig_path = guimod.APPEARED_SOUND_PATH
guimod.APPEARED_SOUND_PATH = r"C:\this\path\does\not\exist.wav"
try:
    guimod._play_beep("APPEARED")
    print("OK: _play_beep('APPEARED') с отсутствующим файлом не упал (fallback на синтезированный тон)")
finally:
    guimod.APPEARED_SOUND_PATH = orig_path

# 3) другие типы событий по-прежнему используют синтезированный тон, не трогая файл
for kind in ("MAGNET", "EATEN", "PULLED", "WALL", "WALL_GONE", "CASCADE"):
    guimod._play_beep(kind)
print("OK: остальные типы событий используют синтезированный тон")

print("\nALL APPEARED-SOUND TESTS PASSED")
