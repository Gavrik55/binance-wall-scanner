import sys, os, tempfile
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import tkinter as tk
import gui as guimod

guimod.CONFIG_FILE = os.path.join(tempfile.gettempdir(), "test_movers_live_config.json")
if os.path.exists(guimod.CONFIG_FILE):
    os.remove(guimod.CONFIG_FILE)

# ускоряем опрос для теста, чтобы не ждать реальные 15 сек
import market_scan
market_scan.POLL_INTERVAL_SEC = 5.0

root = tk.Tk()
app = guimod.App(root)

def check():
    gainers = app.gainers_tree.get_children()
    losers = app.losers_tree.get_children()
    print(f"gainers rows: {len(gainers)}, losers rows: {len(losers)}")
    if gainers:
        print("top gainer:", app.gainers_tree.item(gainers[0], "values"))
    if losers:
        print("top loser:", app.losers_tree.item(losers[0], "values"))
    root.destroy()

root.after(12000, check)
root.mainloop()
print("EXIT OK")
