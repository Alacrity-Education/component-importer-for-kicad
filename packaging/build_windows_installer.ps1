$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $PSScriptRoot
$AppName = "KiCadComponentImporter"
$InnoCompiler = "C:\Program Files (x86)\Inno Setup 6\ISCC.exe"
$BuildStamp = Get-Date -Format "yyyyMMdd_HHmmss"
$TempRoot = Join-Path ([System.IO.Path]::GetTempPath()) (Join-Path "KiCadComponentImporterBuild" $BuildStamp)
$FinalArtifactRoot = Join-Path (Join-Path $Root "release_builds") $BuildStamp
$InstallerDir = Join-Path $TempRoot "installer"
$DistDir = Join-Path $TempRoot "dist"
$BuildDir = Join-Path $TempRoot "build"
$SpecDir = Join-Path $FinalArtifactRoot "spec"
$SourceDir = Join-Path $DistDir $AppName
$InnoScript = Join-Path $PSScriptRoot "KiCadComponentImporter.iss"
$SrcRoot = Join-Path $Root "src"
$PackageDir = Join-Path $SrcRoot "component_importer"
$GuiAssetsDir = Join-Path $PackageDir "gui_assets"
$AppIconPath = Join-Path $GuiAssetsDir "app_icon.ico"
$EntryPoint = Join-Path $PackageDir "gui_main.pyw"
$CliName = "kicad-importer"
$CliEntryPoint = Join-Path $PackageDir "cli.py"
$CliSourceDir = Join-Path $DistDir $CliName
$CliBundleSubdir = "cli"

if (-not (Test-Path -LiteralPath $InnoCompiler)) {
    throw "Inno Setup compiler not found: $InnoCompiler"
}

New-Item -ItemType Directory -Force -Path $InstallerDir | Out-Null
New-Item -ItemType Directory -Force -Path $SpecDir | Out-Null
New-Item -ItemType Directory -Force -Path $FinalArtifactRoot | Out-Null

Push-Location $Root
try {
    python -m PyInstaller `
        --noconfirm `
        --clean `
        --windowed `
        --onedir `
        --name $AppName `
        --distpath $DistDir `
        --workpath $BuildDir `
        --specpath $SpecDir `
        --paths $SrcRoot `
        --icon $AppIconPath `
        --add-data "$GuiAssetsDir;gui_assets" `
        $EntryPoint

    if (-not (Test-Path -LiteralPath (Join-Path $SourceDir "$AppName.exe"))) {
        throw "PyInstaller build did not create $AppName.exe"
    }

    # Second PyInstaller target: the Qt-free command line interface.
    # PyQt6 is excluded so this binary stays small and never pulls in Qt.
    python -m PyInstaller `
        --noconfirm `
        --clean `
        --console `
        --onedir `
        --name $CliName `
        --distpath $DistDir `
        --workpath $BuildDir `
        --specpath $SpecDir `
        --paths $SrcRoot `
        --exclude-module PyQt6 `
        $CliEntryPoint

    if (-not (Test-Path -LiteralPath (Join-Path $CliSourceDir "$CliName.exe"))) {
        throw "PyInstaller build did not create $CliName.exe"
    }

    # Ship the CLI onedir as a subfolder of the GUI bundle so the installer
    # (which recurses SourceDir) carries both the GUI and the CLI executable.
    $CliDestDir = Join-Path $SourceDir $CliBundleSubdir
    if (Test-Path -LiteralPath $CliDestDir) {
        Remove-Item -LiteralPath $CliDestDir -Recurse -Force
    }
    Move-Item -LiteralPath $CliSourceDir -Destination $CliDestDir

    & $InnoCompiler `
        "/DSourceDir=$SourceDir" `
        "/DOutputDir=$InstallerDir" `
        $InnoScript

    $SetupPath = Join-Path $InstallerDir "KiCadComponentImporter_Setup.exe"

    if (-not (Test-Path -LiteralPath $SetupPath)) {
        throw "Inno Setup did not create installer: $SetupPath"
    }

    $FinalSetupPath = Join-Path $FinalArtifactRoot "KiCadComponentImporter_Setup.exe"
    Copy-Item -LiteralPath $SetupPath -Destination $FinalSetupPath -Force

    Write-Host "Built app folder: $SourceDir"
    Write-Host "Built installer: $FinalSetupPath"
}
finally {
    Pop-Location
}
