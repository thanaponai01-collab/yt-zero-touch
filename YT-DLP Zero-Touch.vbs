' Opens YT-DLP Zero-Touch with no terminal window. Output goes to app.log.
' Uses the first python.exe on PATH (the same one run.bat and install.bat use),
' because a bare pythonw here can resolve to a different Python install.
Set fso = CreateObject("Scripting.FileSystemObject")
Set sh = CreateObject("WScript.Shell")
here = fso.GetParentFolderName(WScript.ScriptFullName)
pyw = ""
For Each d In Split(sh.ExpandEnvironmentStrings("%PATH%"), ";")
  If d <> "" And InStr(LCase(d), "\windowsapps") = 0 Then
    If fso.FileExists(fso.BuildPath(d, "python.exe")) And fso.FileExists(fso.BuildPath(d, "pythonw.exe")) Then
      pyw = fso.BuildPath(d, "pythonw.exe")
      Exit For
    End If
  End If
Next
If pyw = "" Then
  MsgBox "Python was not found on PATH. Run install.bat first.", 16, "YT-DLP Zero-Touch"
  WScript.Quit 1
End If
sh.CurrentDirectory = here
sh.Run """" & pyw & """ """ & here & "\app.pyw""", 0, False
