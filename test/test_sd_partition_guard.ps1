$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest
$source = Join-Path $PSScriptRoot "../deploy/robot/pinky_pro/sd/prepare-rosy-sd.ps1"
$tokens = $null; $errors = $null
$ast = [System.Management.Automation.Language.Parser]::ParseFile($source, [ref]$tokens, [ref]$errors)
if ($errors.Count) { throw "writer parse failed" }
foreach ($name in @("Find-ExistingBundle", "Resolve-BootMount")) {
    $definition = $ast.Find({ param($node) $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and $node.Name -eq $name }, $true)
    Invoke-Expression $definition.Extent.Text
}
function Fail([string]$Message) { throw $Message }
function Test-Path { return $true }
function Resolve-Path { return [pscustomobject]@{ Path = "Z:\" } }
function Get-Partition { return [pscustomobject]@{ DiskNumber = 8; DriveLetter = "Z"; MbrType = 12; GptType = "" } }
$DiskNumber = 7; $DiskInventoryJson = $null; $BootMountPath = "Z:\"
$refused = $false
try { Find-ExistingBundle | Out-Null } catch { $refused = $_.Exception.Message -match "selected physical disk" }
if (-not $refused) { throw "wrong-disk boot path accepted" }
$BootMountPath = $null
function Get-Partition { return [pscustomobject]@{ DiskNumber = 7; DriveLetter = $null; MbrType = 12; GptType = "" } }
$refused = $false
try { Find-ExistingBundle | Out-Null } catch { $refused = $_.Exception.Message -match "inspect" }
if (-not $refused) { throw "unmounted partition accepted without inspection" }
function Get-Partition { return [pscustomobject]@{ DiskNumber = 7; DriveLetter = $null; MbrType = 131; GptType = "" } }
if ($null -ne (Find-ExistingBundle)) { throw "Linux root partition treated as boot bundle" }
function Get-Partition { return [pscustomobject]@{ DiskNumber = 7; DriveLetter = "Z"; MbrType = 12; GptType = "" } }
if ((Find-ExistingBundle) -ne "Z:\rosy-provision") { throw "mounted boot bundle not found" }
function Get-Partition { throw "partition inventory unavailable" }
$refused = $false
try { Find-ExistingBundle | Out-Null } catch { $refused = $true }
if (-not $refused) { throw "partition inventory failure accepted" }
Write-Output "PASS: wrong disk, unmounted partition, failed inventory are refused before erase"
