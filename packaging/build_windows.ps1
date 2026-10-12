# Build the Windows release: a zip of the PyInstaller directory.
#
#     powershell -NoProfile -ExecutionPolicy Bypass -File packaging\build_windows.ps1 [git-ref]
#
# Runs ON a Windows machine, in a checkout of this repo with a .venv beside it.
# The twin of build_linux.sh and deliberately the same shape: no knowledge of
# SSH, deploy.py or the website, so a GitHub Actions runner could run exactly
# this file. Glue belongs in the caller.
#
# Zip rather than an installer, for the same reason the Linux build is a tarball
# and not an AppImage: nothing extra to install or debug remotely. Unsigned, so
# SmartScreen warns on first launch. Revisit when somebody actually asks.
#
# THE SELF TESTS AND THE GUI SUBSYSTEM. Nocturne.exe is built windowed
# (console=False), so started from a terminal it has no console of its own and
# a plain `Nocturne.exe --check-codecs` prints nothing -- cmd and PowerShell do
# not even wait for it. Its output is still there when stdout is REDIRECTED: a
# GUI-subsystem process inherits the handles it is given, and Python builds
# sys.stdout from them. So every self test below runs through Invoke-Selftest,
# which redirects to a file, waits, and reads the exit code. By hand:
#
#     Start-Process dist\Nocturne\Nocturne.exe --check-codecs -Wait -NoNewWindow `
#         -RedirectStandardOutput out.txt; Get-Content out.txt
#
# or from cmd:  dist\Nocturne\Nocturne.exe --check-codecs > out.txt 2>&1 & type out.txt
# (a redirected launch from cmd waits for the process too).
param([string]$Ref = "")

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
    param([string]$Exe, [string]$Flag)
    $out = [IO.Path]::GetTempFileName()
    $err = [IO.Path]::GetTempFileName()
    try {
        $p = Start-Process -FilePath $Exe -ArgumentList $Flag -Wait -PassThru -NoNewWindow `
            -RedirectStandardOutput $out -RedirectStandardError $err
        $lines = @(Get-Content $out) + @(Get-Content $err)
        return @{ Code = $p.ExitCode; Output = $lines }
    } finally {
        Remove-Item $out, $err -ErrorAction SilentlyContinue
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
# RC-Astro. The codecs are in the zip or they are not.
$codecs = Invoke-Selftest $Exe "--check-codecs"
$codecs.Output | ForEach-Object { Write-Output "  codecs   $_" }
if ($codecs.Code -ne 0) {
    Fail "the build cannot decode a compressed TIFF -- star separation and opening a user's TIFF would fail for every user"
}

# bsdtar ships with Windows 10 and later and writes a zip when the name ends in
# .zip (-a). Compress-Archive takes many minutes over a bundle this size.
$Zip = Join-Path $Repo "dist\$Name.zip"
Push-Location (Join-Path $Repo "dist")
try {
    Invoke-Native tar.exe @("-a", "-c", "-f", "$Name.zip", "Nocturne")
} finally {
    Pop-Location
}
$size = [math]::Round((Get-Item $Zip).Length / 1MB, 1)
$sha = (Get-FileHash -Algorithm SHA256 $Zip).Hash.ToLower()
Write-Output "  artifact dist\$Name.zip  ($size MB)"
Write-Output "  sha256   $sha"
