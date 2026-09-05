"""Read-only native window geometry and capture for the packaged app."""
import ctypes as c
from ctypes import wintypes as w
import json
from pathlib import Path
from PIL import ImageGrab

try: c.windll.shcore.SetProcessDpiAwareness(2)
except OSError: pass
u = c.WinDLL('user32', use_last_error=True)
u.GetWindowRect.argtypes = [w.HWND, c.POINTER(w.RECT)]
u.GetWindowTextW.argtypes = [w.HWND, w.LPWSTR, c.c_int]
u.GetClassNameW.argtypes = [w.HWND, w.LPWSTR, c.c_int]
u.GetWindowThreadProcessId.argtypes = [w.HWND, c.POINTER(w.DWORD)]
CALLBACK = c.WINFUNCTYPE(w.BOOL, w.HWND, w.LPARAM)

def info(hwnd):
    rect = w.RECT(); u.GetWindowRect(hwnd,c.byref(rect))
    title=c.create_unicode_buffer(512); u.GetWindowTextW(hwnd,title,512)
    cls=c.create_unicode_buffer(128); u.GetClassNameW(hwnd,cls,128)
    pid=w.DWORD(); u.GetWindowThreadProcessId(hwnd,c.byref(pid))
    return {'hwnd':int(hwnd),'pid':pid.value,'class':cls.value,'text':title.value,
            'rect':[rect.left,rect.top,rect.right,rect.bottom],
            'center':[(rect.left+rect.right)//2,(rect.top+rect.bottom)//2]}

windows=[]
@CALLBACK
def top(hwnd,_):
    data=info(hwnd)
    if data['text']=='Puca - A Dark Fantasy Tale' and u.IsWindowVisible(hwnd):
        windows.append(data)
    return True
u.EnumWindows(top,0)
for window in windows:
    children=[]
    @CALLBACK
    def child(hwnd,_):
        data=info(hwnd)
        if u.IsWindowVisible(hwnd): children.append(data)
        return True
    u.EnumChildWindows(window['hwnd'],child,0)
    window['children']=children
    target=Path(__file__).resolve().parents[1]/'docs/verification/exe-screen.png'
    try:
        ImageGrab.grab(window=window['hwnd']).save(target)
        window['screenshot']=str(target)
    except OSError as exc:
        window['capture_error']=str(exc)
print(json.dumps(windows,indent=2))
