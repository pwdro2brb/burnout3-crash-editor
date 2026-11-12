param(
    [ValidateSet('Import','Process')][string]$Mode = 'Import',
    [string]$GameRoot = $env:B3_GAME_ROOT,
    [string]$OutputRoot = $env:B3_OUTPUT_ROOT,
    [string]$GhidraDir = $env:B3_GHIDRA_DIR,
    [string]$JavaHome = $env:B3_JAVA_HOME,
    [string]$Config,
    [string]$ProjectDir,
    [string]$ProjectName = 'Burnout3',
    [string]$Executable = 'SLUS_210.50',
    [string]$PostScript = 'CrashTriage.java',
    [string[]]$PostArgs = @()
)
$ErrorActionPreference = 'Stop'
if ($Config) {
    $settings = Get-Content -LiteralPath $Config -Raw | ConvertFrom-Json
    if (-not $GameRoot) { $GameRoot = $settings.game_root }
    if (-not $OutputRoot) { $OutputRoot = $settings.output_root }
    if (-not $GhidraDir) { $GhidraDir = $settings.ghidra_dir }
    if (-not $JavaHome) { $JavaHome = $settings.java_home }
}
$repoRoot = Split-Path (Split-Path $PSScriptRoot -Parent) -Parent
if (-not $OutputRoot) { $OutputRoot = Join-Path $repoRoot 'outputs' }
function Full-Path([string]$Value) { return [IO.Path]::GetFullPath($Value) }
function Within([string]$Child, [string]$Parent) {
    $prefix = $Parent.TrimEnd('\','/') + [IO.Path]::DirectorySeparatorChar
    return $Child.Equals($Parent, [StringComparison]::OrdinalIgnoreCase) -or
        $Child.StartsWith($prefix, [StringComparison]::OrdinalIgnoreCase)
}
$OutputRoot = Full-Path $OutputRoot
if ($GameRoot) {
    $GameRoot = Full-Path $GameRoot
    if (-not (Test-Path -LiteralPath $GameRoot -PathType Container)) { throw 'GameRoot must be an existing extracted-game directory.' }
    if ((Within $OutputRoot $GameRoot) -or (Within $GameRoot $OutputRoot)) { throw 'GameRoot and OutputRoot must be separate, non-overlapping trees.' }
}
if (-not $GhidraDir -or -not $JavaHome) { throw 'Set GhidraDir/JavaHome or B3_GHIDRA_DIR/B3_JAVA_HOME.' }
$GhidraDir = Full-Path $GhidraDir
$JavaHome = Full-Path $JavaHome
$javaPath = Join-Path $JavaHome 'bin\java.exe'
$launchProperties = Join-Path $GhidraDir 'support\launch.properties'
if (-not (Test-Path -LiteralPath $javaPath -PathType Leaf)) { throw 'Java executable not found in JavaHome.' }
if (-not (Test-Path -LiteralPath $launchProperties -PathType Leaf)) { throw 'Ghidra launch.properties not found.' }
$runtimeDir = Join-Path $OutputRoot 'runtime'
$reportDir = Join-Path $OutputRoot 'reports'
if (-not $ProjectDir) { $ProjectDir = Join-Path $OutputRoot 'ghidra' }
$ProjectDir = Full-Path $ProjectDir
if ($GameRoot -and (Within $ProjectDir $GameRoot)) { throw 'ProjectDir must not be inside the game directory.' }
if ($PostScript -and $PostScript -ne 'CrashTriage.java' -and -not $PostArgs.Count) { throw 'This PostScript requires explicit PostArgs.' }
if ($PostArgs.Count -and $PostScript -in @('CrashTriage.java','ExportAddressRefs.java','ExportFunctions.java')) {
    $postOutput = Full-Path $PostArgs[0]
    if (-not (Within $postOutput $OutputRoot)) { throw 'The export destination in PostArgs must be inside OutputRoot.' }
}
New-Item -ItemType Directory -Path $ProjectDir,$reportDir,$runtimeDir -Force | Out-Null
$vmArgs = @(Get-Content -LiteralPath $launchProperties |
    Where-Object { $_ -match '^VMARGS(?:_WINDOWS)?=' } |
    ForEach-Object { $_ -replace '^VMARGS(?:_WINDOWS)?=', '' })
$headlessArgs = @($ProjectDir, $ProjectName)
if ($Mode -eq 'Import') {
    if (-not $GameRoot) { throw 'Import requires GameRoot or B3_GAME_ROOT.' }
    $source = Full-Path (Join-Path $GameRoot $Executable)
    if (-not (Within $source $GameRoot)) { throw 'Executable must be inside GameRoot.' }
    if (-not (Test-Path -LiteralPath $source -PathType Leaf)) { throw 'Input executable not found.' }
    $headlessArgs += @('-import', $source, '-processor', 'r5900:LE:32:default',
        '-cspec', 'default', '-analysisTimeoutPerFile', '600')
} else {
    $headlessArgs += @('-process', $Executable, '-noanalysis', '-readOnly')
}
$headlessArgs += @('-max-cpu', '2', '-scriptPath', $PSScriptRoot,
    '-log', (Join-Path $reportDir 'ghidra.log'), '-scriptlog', (Join-Path $reportDir 'scripts.log'))
if ($PostScript) {
    $headlessArgs += @('-postScript', $PostScript)
    if ($PostArgs.Count) { $headlessArgs += $PostArgs }
    else { $headlessArgs += @($reportDir, (Join-Path $OutputRoot 'candidate_strings.tsv')) }
}
& $javaPath @vmArgs '-Xmx4G' "-Duser.home=$runtimeDir" "-Dapplication.settingsdir=$runtimeDir\settings" `
    "-Dapplication.cachedir=$runtimeDir\cache" "-Dapplication.tempdir=$runtimeDir\temp" `
    -cp (Join-Path $GhidraDir 'Ghidra\Framework\Utility\lib\Utility.jar') `
    ghidra.Ghidra ghidra.app.util.headless.AnalyzeHeadless @headlessArgs
exit $LASTEXITCODE
