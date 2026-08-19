Option Explicit

Dim shell, fso, folder, pythonw, script, command
Set shell = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
folder = fso.GetParentFolderName(WScript.ScriptFullName)
shell.CurrentDirectory = folder
pythonw = folder & "\.venv\Scripts\pythonw.exe"
script = folder & "\main.py"
command = Chr(34) & pythonw & Chr(34) & " " & Chr(34) & script & Chr(34)
shell.Run command, 1, False
