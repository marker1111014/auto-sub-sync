import os
import subprocess
import shutil

desktop = os.path.join(os.path.expanduser("~"), "Desktop")
lnk_path = os.path.join(desktop, "電影字幕自動同步.lnk")
cur_dir = os.path.abspath(os.path.dirname(__file__))
gui_py = os.path.join(cur_dir, "gui_app.py")
pythonw_path = shutil.which("pythonw") or "pythonw.exe"

ps_content = f"""
$WshShell = New-Object -ComObject WScript.Shell
$Shortcut = $WshShell.CreateShortcut('{lnk_path}')
$Shortcut.TargetPath = '{pythonw_path}'
$Shortcut.Arguments = '"{gui_py}"'
$Shortcut.WorkingDirectory = '{cur_dir}'
$Shortcut.IconLocation = 'imageres.dll,18'
$Shortcut.Description = '電影字幕自動同步器'
$Shortcut.Save()
"""

ps_path = os.path.join(cur_dir, "temp_make_shortcut.ps1")
with open(ps_path, "w", encoding="utf-8-sig") as f:
    f.write(ps_content)


try:
    subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", ps_path], check=True)
    print(f"成功！已在桌面建立捷徑: {lnk_path}")
finally:
    if os.path.exists(ps_path):
        os.remove(ps_path)
