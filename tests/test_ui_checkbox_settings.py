import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import tkinter as tk

import gui as guimod

tmp = tempfile.gettempdir()
guimod.HEDGEHOG_BOOTSTRAP_ENABLED = False
guimod.CONFIG_FILE = os.path.join(tmp, "test_ui_checkbox_config.json")
guimod.UI_SETTINGS_FILE = os.path.join(tmp, "test_ui_checkbox_settings.json")
guimod.IMPULSE_SETTINGS_FILE = os.path.join(tmp, "test_ui_impulse_settings.json")
guimod.HEDGEHOG_EVENT_SETTINGS_FILE = os.path.join(tmp, "test_ui_hedgehog_event_settings.json")
guimod.PRINT_SETTINGS_FILE = os.path.join(tmp, "test_ui_print_settings.json")
for path in (
    guimod.CONFIG_FILE,
    guimod.UI_SETTINGS_FILE,
    guimod.IMPULSE_SETTINGS_FILE,
    guimod.HEDGEHOG_EVENT_SETTINGS_FILE,
    guimod.PRINT_SETTINGS_FILE,
):
    if os.path.exists(path):
        os.remove(path)


root = tk.Tk()
app = guimod.App(root)
app.sound_enabled.set(False)
app.impulse_popup_enabled.set(False)
app.impulse_sound_enabled.set(False)
app.early_alerts_enabled.set(False)
app.early_exclusive_only.set(False)
app.hedgehog_event_popup_enabled.set(False)
app.hedgehog_event_sound_enabled.set(False)
app.alert_filter_vars["APPEARED"].set(False)
app.alert_filter_vars["PUSH"].set(False)
app.hedgehog_event_filter_vars["HEDGEHOG_BOOK"].set(False)
app._save_ui_settings()
app._on_close()
print("OK: первая сессия сохранила ui_settings.json")

root2 = tk.Tk()
app2 = guimod.App(root2)
assert app2.sound_enabled.get() is False
assert app2.impulse_popup_enabled.get() is False
assert app2.impulse_sound_enabled.get() is False
assert app2.early_alerts_enabled.get() is False
assert app2.early_exclusive_only.get() is False
assert app2.hedgehog_event_popup_enabled.get() is False
assert app2.hedgehog_event_sound_enabled.get() is False
assert app2.alert_filter_vars["APPEARED"].get() is False
assert app2.alert_filter_vars["PUSH"].get() is False
assert app2.alert_filter_vars["MAGNET"].get() is True
assert app2.hedgehog_event_filter_vars["HEDGEHOG_BOOK"].get() is False
assert app2.hedgehog_event_filter_vars["HEDGEHOG_NEEDLES"].get() is True
print("OK: вторая сессия восстановила состояния всех основных галочек")

app2.alert_filter_vars["APPEARED"].set(True)
app2._on_alert_filter_changed()
with open(guimod.UI_SETTINGS_FILE, encoding="utf-8") as f:
    saved = json.load(f)
assert saved["alert_filters"]["APPEARED"] is True
print("OK: изменение галочки фильтра сразу записывается на диск")

app2._on_close()
print("\nALL UI CHECKBOX SETTINGS TESTS PASSED")
