param([string]$Destination = (Split-Path -Parent $PSScriptRoot))
$ErrorActionPreference = 'Stop'
$taskRoot = Split-Path -Parent $PSScriptRoot
$taskDestination = (Resolve-Path -LiteralPath $Destination).Path
$taskIconPath = Join-Path $PSScriptRoot 'PyLiBStudy.ico'
# Draw a code-native battery icon; ICO embeds a PNG at 256 px.
Add-Type -AssemblyName System.Drawing
$taskBitmap = New-Object System.Drawing.Bitmap(256, 256)
$taskGraphics = [System.Drawing.Graphics]::FromImage($taskBitmap)
$taskBackground = New-Object System.Drawing.SolidBrush([System.Drawing.Color]::FromArgb(23, 38, 58))
$taskAccent = New-Object System.Drawing.SolidBrush([System.Drawing.Color]::FromArgb(61, 214, 170))
$taskWhite = New-Object System.Drawing.SolidBrush([System.Drawing.Color]::White)
$taskPng = New-Object System.IO.MemoryStream
try {
    $taskGraphics.Clear([System.Drawing.Color]::Transparent)
    $taskGraphics.FillEllipse($taskBackground, 4, 4, 248, 248)
    $taskGraphics.FillRectangle($taskWhite, 104, 39, 48, 17)
    $taskGraphics.FillRectangle($taskWhite, 77, 56, 102, 151)
    $taskGraphics.FillRectangle($taskBackground, 87, 66, 82, 131)
    $taskGraphics.FillRectangle($taskAccent, 96, 119, 64, 69)
    $taskGraphics.FillRectangle($taskAccent, 96, 82, 64, 27)
    $taskBitmap.Save($taskPng, [System.Drawing.Imaging.ImageFormat]::Png)
    $taskBytes = $taskPng.ToArray()
    $taskFile = [System.IO.File]::Create($taskIconPath)
    $taskWriter = New-Object System.IO.BinaryWriter($taskFile)
    try {
        $taskWriter.Write([uint16]0); $taskWriter.Write([uint16]1); $taskWriter.Write([uint16]1)
        $taskWriter.Write([byte]0); $taskWriter.Write([byte]0)
        $taskWriter.Write([byte]0); $taskWriter.Write([byte]0)
        $taskWriter.Write([uint16]1); $taskWriter.Write([uint16]32)
        $taskWriter.Write([uint32]$taskBytes.Length); $taskWriter.Write([uint32]22)
        $taskWriter.Write($taskBytes)
    } finally { $taskWriter.Dispose(); $taskFile.Dispose() }
} finally {
    $taskPng.Dispose(); $taskGraphics.Dispose(); $taskBitmap.Dispose()
    $taskBackground.Dispose(); $taskAccent.Dispose(); $taskWhite.Dispose()
}
$taskShell = New-Object -ComObject WScript.Shell
$taskLink = $taskShell.CreateShortcut((Join-Path $taskDestination 'PyLiBStudy.lnk'))
$taskLink.TargetPath = Join-Path $taskRoot 'start.cmd'
$taskLink.WorkingDirectory = $taskRoot
$taskLink.IconLocation = "$taskIconPath,0"
$taskLink.Description = 'PyLiBStudy - battery simulation workbench'
$taskLink.WindowStyle = 1
$taskLink.Save()
Write-Host "Created: $(Join-Path $taskDestination 'PyLiBStudy.lnk')"
