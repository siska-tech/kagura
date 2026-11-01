"""Original PROJECT STARFALL USB serial controller. Requires pyserial.
Usage: python keyboard.py COM5 (WASD/arrows + space fire + X/Shift equip).
"""
import sys
import tkinter as tk
import serial

port = serial.Serial(sys.argv[1], 115200, timeout=0, write_timeout=0.1)
root = tk.Tk()
root.title("PROJECT STARFALL controller")
tk.Label(root, text="WASD / arrows: move     Space: fire\nX / Shift: activate selected power-up\nKeep this window focused", padx=32, pady=32).pack()
held = {}
mapping = {"a": 1, "Left": 1, "d": 2, "Right": 2, "w": 4, "Up": 4,
           "s": 8, "Down": 8, "space": 16, "Return": 16, "x": 32, "X": 32,
           "Shift_L": 32, "Shift_R": 32}
def on_press(event):
    held[event.keycode] = mapping.get(event.keysym, mapping.get(event.keysym.lower(), 0))


def on_release(event):
    held.pop(event.keycode, None)


root.bind("<KeyPress>", on_press)
root.bind("<KeyRelease>", on_release)
root.bind("<FocusOut>", lambda e: held.clear())


def send():
    mask = 0
    for value in held.values():
        mask |= value
    port.write(bytes((ord('@'), ord('A') + mask)))
    data = port.read(port.in_waiting)
    if data:
        print(data.decode('ascii', errors='replace'), end='', flush=True)
    root.after(33, send)


try:
    send()
    root.mainloop()
finally:
    port.write(b'@A')
    port.close()
