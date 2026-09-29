from pathlib import Path
from PyInstaller.utils.hooks import collect_all
root=Path(SPECPATH)
source=root.parent/'jev-chat-desktop'
datas,binaries,hidden=[],[],['app.settings','core.engine','main','direct_data','wechat_db','uiautomation','cryptography','zstandard']
for pkg in ('uiautomation','cryptography','zstandard'):
 d,b,h=collect_all(pkg);datas+=d;binaries+=b;hidden+=h
a=Analysis([str(root/'worker'/'view_worker.py')],pathex=[str(root/'worker'),str(source)],binaries=binaries,datas=datas,hiddenimports=hidden,
 excludes=['PySide6','shiboken6','PyQt5','PyQt6','tkinter','matplotlib','scipy','pandas','rapidocr_onnxruntime','onnxruntime','windows_capture'],noarchive=False)
pyz=PYZ(a.pure)
exe=EXE(pyz,a.scripts,[],exclude_binaries=True,name='TalkHelperNativeWorker-v13r2',console=False,disable_windowed_traceback=True)
coll=COLLECT(exe,a.binaries,a.datas,name='TalkHelperNativeWorker-v13r2')
