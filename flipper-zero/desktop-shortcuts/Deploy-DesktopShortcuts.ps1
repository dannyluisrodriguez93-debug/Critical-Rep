<#
.SYNOPSIS
    Creates Windows desktop URL shortcuts (.url icons) for clinical web apps.

.DESCRIPTION
    Writes one .url shortcut per entry to the current user's Desktop.
    Nothing is hidden or encoded -- this is a plain, auditable script meant
    to be reviewed by IT/security and deployed through normal channels:

        - Group Policy:  User Configuration > Logon script
        - Intune:        Devices > Scripts (or a Win32 app)
        - SCCM/ConfigMgr: Package/Program or Configuration Item

    Re-running it is safe: existing shortcuts are simply overwritten.

.NOTES
    Edit the $Shortcuts table below with the real names and URLs, then have
    IT deploy it. Test on one workstation first.
#>

# --- Edit this list: 'Icon label' = 'https://url' ----------------------------
$Shortcuts = [ordered]@{
    'Epic Hyperspace' = 'https://epic.example-hospital.org'
    'PACS Imaging'    = 'https://pacs.example-hospital.org'
    'Lab Results'     = 'https://lab.example-hospital.org'
    'Pharmacy'        = 'https://rx.example-hospital.org'
}
# -----------------------------------------------------------------------------

$desktop = [Environment]::GetFolderPath('Desktop')

foreach ($entry in $Shortcuts.GetEnumerator()) {
    $label = $entry.Key
    $url   = $entry.Value
    $path  = Join-Path $desktop ($label + '.url')

    # A .url file is a tiny plain-text INI; this is all Windows needs.
    $content = "[InternetShortcut]`r`nURL=$url"
    Set-Content -LiteralPath $path -Value $content -Encoding ASCII

    Write-Host "Created: $path  ->  $url"
}

Write-Host "Done. $($Shortcuts.Count) shortcut(s) written to $desktop"
