Set oWS = WScript.CreateObject("WScript.Shell")
sDesktop = oWS.SpecialFolders("Desktop")
sLinkFile = sDesktop & "\AI Manager Dashboard.lnk"
Set oLink = oWS.CreateShortcut(sLinkFile)
sCurrentDir = oWS.CurrentDirectory
oLink.TargetPath = sCurrentDir & "\start.bat"
oLink.WorkingDirectory = sCurrentDir
oLink.WindowStyle = 1
oLink.IconLocation = "shell32.dll,14"
oLink.Description = "Launch AI Manager Dashboard"
oLink.Save
WScript.Echo "Shortcut created at: " & sLinkFile
