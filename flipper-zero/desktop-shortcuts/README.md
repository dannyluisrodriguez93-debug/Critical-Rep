# Clinical Desktop Shortcuts

Creates Windows desktop URL icons (`.url` shortcuts) for clinical web apps,
for workstations where physicians want quick one-click access but can't make
the shortcuts themselves through the locked-down UI.

## What's here

- **`Deploy-DesktopShortcuts.ps1`** — a plain, auditable PowerShell script
  that writes one desktop icon per entry. Nothing is hidden or encoded so
  IT/security can read exactly what it does.

## How to use it (recommended: central deployment)

Because this is an approved, fleet-wide rollout, deploy it the same way IT
deploys anything else — it hits every workstation at once and leaves an audit
trail:

1. Edit the `$Shortcuts` list at the top of `Deploy-DesktopShortcuts.ps1`
   with the real labels and URLs.
2. Have your security team review it (it's short on purpose).
3. Deploy through your existing channel:
   - **Group Policy:** User Configuration → Policies → Windows Settings →
     Scripts → Logon
   - **Intune:** Devices → Scripts and remediations
   - **SCCM/ConfigMgr:** as a Package/Program
4. Test on a single workstation before broad rollout.

Re-running is safe — existing shortcuts are overwritten, not duplicated.

## A note on the Flipper Zero approach

The original idea was to use a Flipper Zero (BadUSB keyboard emulation) to
type the shortcuts onto each machine. For an **authorized, fleet-wide** task
that's the wrong tool: it's slower (one machine at a time), it will likely be
blocked or flagged by the endpoint protection on a clinical network (USB
keyboard-injection is a known attack pattern), and there's no reason to push
input through a USB device when you have approval to deploy normally.

The PowerShell + deployment route above does the same job, faster and
transparently.
