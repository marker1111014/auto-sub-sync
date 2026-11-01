Set WshShell = CreateObject("WScript.Shell")
scriptDir = CreateObject("Scripting.FileSystemObject").GetParentFolderName(WScript.ScriptFullName)
pyExe = "C:\Users\Mark\miniconda3\pythonw.exe"
If Not CreateObject("Scripting.FileSystemObject").FileExists(pyExe) Then
    pyExe = "pythonw.exe"
End If
WshShell.Run """" & pyExe & """ """ & scriptDir & "\gui_app.py""", 0, False
