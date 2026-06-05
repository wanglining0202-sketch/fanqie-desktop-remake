# PowerShell script: auto-deploy to Render
Add-Type @"
using System;
using System.Runtime.InteropServices;
public class KB {
    [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr h);
    [DllImport("user32.dll")] public static extern IntPtr GetForegroundWindow();
    [DllImport("user32.dll")] public static extern void keybd_event(byte vk, byte sc, uint f, IntPtr ex);
}
"@

$VK_TAB = 0x09
$VK_RETURN = 0x0D
$KEYEVENTF_KEYUP = 2

# Wait for browser to load
Start-Sleep -Seconds 5

# Bring browser to front
$wshell = New-Object -ComObject WScript.Shell
$wshell.SendKeys('%')  # Alt to focus
Start-Sleep 1

# Tab through the form to reach Deploy/Create button
# Typically 8-10 tabs to reach the submit button
for ($i=0; $i -lt 10; $i++) {
    [KB]::keybd_event($VK_TAB, 0, 0, [IntPtr]::Zero)
    Start-Sleep -Milliseconds 200
    [KB]::keybd_event($VK_TAB, 0, $KEYEVENTF_KEYUP, [IntPtr]::Zero)
    Start-Sleep -Milliseconds 300
}

# Press Enter
Start-Sleep 1
[KB]::keybd_event($VK_RETURN, 0, 0, [IntPtr]::Zero)
Start-Sleep -Milliseconds 100
[KB]::keybd_event($VK_RETURN, 0, $KEYEVENTF_KEYUP, [IntPtr]::Zero)

Write-Host "Done"
