# Build the Windows release: an Inno Setup installer of the PyInstaller directory.
#
#     powershell -NoProfile -ExecutionPolicy Bypass -File packaging\build_windows.ps1 [git-ref] [-Iscc <path>]
#
# Runs ON a Windows machine, in a checkout of this repo with a .venv beside it.
# The twin of build_linux.sh and deliberately the same shape: no knowledge of
# SSH, deploy.py or the website, so a GitHub Actions runner could run exactly
# this file. Glue belongs in the caller.
#
# An installer and no zip (owner's call, 2026-10-12): per-user, no admin, a
# Start menu entry, an uninstaller, .nocturne double-click. packaging\nocturne.iss
# says what it writes. Needs Inno Setup 6 on the build host (ISCC.exe, found in
# its default per-user or Program Files location, or passed as -Iscc). Unsigned,
# so SmartScreen warns on first launch.
#
# THE SELF TESTS AND THE GUI SUBSYSTEM. Nocturne.exe is built windowed
# (console=False, PE subsystem 2), so it has no console of its own: typed at an
# interactive prompt, `Nocturne.exe --check-codecs` returns at once and its
# output goes nowhere. The output is still there when stdout is REDIRECTED -- a
# GUI-subsystem process inherits the handles it is given and Python builds
# sys.stdout from them, as the --stack-job child's JSON protocol relies on. So
# every self test below runs through Invoke-Selftest, which redirects to a file,
# waits, and reads the exit code. By hand:
#
#     Start-Process dist\Nocturne\Nocturne.exe --check-codecs -Wait -NoNewWindow `
#         -RedirectStandardOutput out.txt; Get-Content out.txt
param([string]$Ref = "", [string]$Iscc = "")

$ErrorActionPreference = "Stop"
$Repo = Split-Path -Parent $PSScriptRoot
Set-Location $Repo
$Py = Join-Path $Repo ".venv\Scripts\python.exe"

function Fail([string]$msg) {
    [Console]::Error.WriteLine($msg)
    exit 1
}

function Invoke-Native {
    # $ErrorActionPreference does not apply to native programs; their exit code does.
    param([string]$Exe, [string[]]$Arguments)
    & $Exe @Arguments
    if ($LASTEXITCODE -ne 0) { Fail "failed ($LASTEXITCODE): $Exe $($Arguments -join ' ')" }
}

function Invoke-Selftest {
    # Returns @{ Code = <exit code>; Output = <lines> }. See the header for why
    # the redirect is the whole mechanism.
    #
    # Under a throwaway USERPROFILE: a self test no longer opens the session log
    # (since 2026-10-17), but it still writes ~\.nocturne\nocturne.log, and the
    # build machine may be somebody's own -- a build must not add to the log a
    # support report would carry. Tool detection is unaffected:
    # the installs it looks for live under LOCALAPPDATA and ProgramFiles.
    param([string]$Exe, [string]$Flag)
    $out = [IO.Path]::GetTempFileName()
    $err = [IO.Path]::GetTempFileName()
    $home_ = Join-Path ([IO.Path]::GetTempPath()) ("nocturne_selftest_" + [Guid]::NewGuid().ToString("N"))
    New-Item -ItemType Directory -Path $home_ | Out-Null
    $saved = $env:USERPROFILE
    try {
        $env:USERPROFILE = $home_
        $p = Start-Process -FilePath $Exe -ArgumentList $Flag -Wait -PassThru -NoNewWindow `
            -RedirectStandardOutput $out -RedirectStandardError $err
        $lines = @(Get-Content $out) + @(Get-Content $err)
        return @{ Code = $p.ExitCode; Output = $lines }
    } finally {
        $env:USERPROFILE = $saved
        Remove-Item $out, $err -ErrorAction SilentlyContinue
        Remove-Item -Recurse -Force $home_ -ErrorAction SilentlyContinue
    }
}

if ($Ref) {
    # Fetch first: the tag being built was very likely pushed seconds ago.
    #
    # NOT THE ONLY CHECKOUT A CALLER SHOULD DO. PowerShell parses this whole file
    # before running it, so a checkout here cannot corrupt the run the way it
    # did bash's (see build_linux.sh) -- but it still means THIS run is the
    # previous ref's script driving the new ref's tree, so a change to this file
    # takes effect one release late. A caller (deploy.py) should check the ref
    # out in a separate step first; then this is a no-op. Kept so the file
    # still works standalone.
    Invoke-Native git @("fetch", "--quiet", "--tags", "origin")
    Invoke-Native git @("checkout", "--quiet", $Ref)
}

$m = Select-String -Path "nocturne\__init__.py" -Pattern '^__version__ = "([^"]+)"'
if (-not $m) { Fail "could not read __version__ from nocturne\__init__.py" }
$Version = $m.Matches[0].Groups[1].Value
$Name = "Nocturne-$Version-windows-x64"

$head = (git rev-parse --short HEAD)
$subject = (git log -1 --pretty=%s)
if ($subject.Length -gt 60) { $subject = $subject.Substring(0, 60) }
Write-Output "building $Name"
Write-Output "  ref      $head  $subject"
Write-Output "  windows  $([Environment]::OSVersion.VersionString)"
Write-Output "  python   $(& $Py -V 2>&1)"

# PyInstaller is not a runtime dependency and is deliberately absent from
# pyproject's extras, so the build host installs it here.
Invoke-Native $Py @("-m", "pip", "install", "--quiet", "--upgrade", "pyinstaller")
Invoke-Native $Py @("-m", "pip", "install", "--quiet", "-e", ".[dev]")

foreach ($d in "build", "dist") {
    if (Test-Path $d) { Remove-Item -Recurse -Force $d }
}
Invoke-Native $Py @("-m", "PyInstaller", "packaging\nocturne.spec", "--noconfirm", "--clean",
                    "--log-level", "WARN")

$Exe = Join-Path $Repo "dist\Nocturne\Nocturne.exe"
if (-not (Test-Path $Exe)) { Fail "no executable at dist\Nocturne\Nocturne.exe" }

# The smoke test that matters: does the thing we just built actually start?
# --check-network returns before any window is created, so it runs headless and
# still exercises the bundle's Python, its imports and its certificate path.
# Warns, does not block: a flaky connection is not a build defect (exit 2, no
# CA bundle at all, is -- and blocks).
$net = Invoke-Selftest $Exe "--check-network"
Write-Output "  smoke    $($net.Output | Select-Object -Last 1)"
if ($net.Code -eq 2) {
    $net.Output | ForEach-Object { Write-Output "           $_" }
    Fail "the build has no usable CA bundle -- HTTPS cannot work on any machine"
}
if ($net.Code -ne 0 -and $net.Code -ne 1) {
    # Anything else means the exe did not even get as far as the check.
    $net.Output | ForEach-Object { Write-Output "           $_" }
    Fail "the build did not start (exit $($net.Code))"
}

# BLOCKING. imagecodecs imports its codecs dynamically, so a bundle can carry
# the package and none of its decoders; every macOS and Linux build from
# v0.35.0 to v0.39.0 did, and star separation failed for every user without
# RC-Astro. The codecs are in the bundle or they are not.
$codecs = Invoke-Selftest $Exe "--check-codecs"
$codecs.Output | ForEach-Object { Write-Output "  codecs   $_" }
if ($codecs.Code -ne 0) {
    Fail "the build cannot decode a compressed TIFF -- star separation and opening a user's TIFF would fail for every user"
}

# External tools as the BUILT app sees them. Blocking only on exit 2, which
# means something checkable here failed: StarNet2 is installed and the split did
# not work (the subprocess, or the bundle reading back its LZW+predictor TIFF),
# or sep is not seeded. A tool this machine does not have is not a defect.
$tools = Invoke-Selftest $Exe "--check-tools"
$tools.Output | ForEach-Object { Write-Output "  tools    $_" }
if ($tools.Code -ne 0) {
    Fail "the build's tool check failed (exit $($tools.Code)) -- see above"
}

# The installer, only after every gate above has passed.
if (-not $Iscc) {
    $Iscc = @(
        (Join-Path $env:LOCALAPPDATA "Programs\Inno Setup 6\ISCC.exe"),
        (Join-Path ${env:ProgramFiles(x86)} "Inno Setup 6\ISCC.exe"),
        (Join-Path $env:ProgramFiles "Inno Setup 6\ISCC.exe")
    ) | Where-Object { Test-Path $_ } | Select-Object -First 1
}
if (-not $Iscc -or -not (Test-Path $Iscc)) { Fail "Inno Setup 6 not found (ISCC.exe); install it or pass -Iscc" }
# VERSIONINFO wants four numbers; "0.51.1-test" -> 0.51.1.0.
$nums = @([regex]::Matches($Version, "\d+") | Select-Object -First 4 | ForEach-Object { $_.Value })
while ($nums.Count -lt 4) { $nums += "0" }
$VersionNum = $nums -join "."
Invoke-Native $Iscc @("/Q", "/DAppVersion=$Version", "/DAppVersionNum=$VersionNum", "packaging\nocturne.iss")

$Setup = Join-Path $Repo "dist\$Name-setup.exe"
if (-not (Test-Path $Setup)) { Fail "no installer at dist\$Name-setup.exe" }
$size = [math]::Round((Get-Item $Setup).Length / 1MB, 1)
$sha = (Get-FileHash -Algorithm SHA256 $Setup).Hash.ToLower()
Write-Output "  artifact dist\$Name-setup.exe  ($size MB)"
Write-Output "  sha256   $sha"
