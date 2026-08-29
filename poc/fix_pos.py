import sys, os, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import find_window
from poc1c_drag_probe import restore_via_ax
w = find_window()
print('trước:', (w['x'], w['y']))
print('AX set:', restore_via_ax(w['pid'], 1029, 30))
time.sleep(0.4)
w = find_window(); print('sau  :', (w['x'], w['y']))
