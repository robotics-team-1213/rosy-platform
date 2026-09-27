# Runs the existing image signer without network access. The host must be
# physically offline if this is used as the production offline signing station.
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$ReleaseDir,
    [string]$PrivateKeyPath = (Join-Path $env:LOCALAPPDATA 'Rosy\signing\rosy-release-2026-01.private.pem'),
    [string]$DockerImage = 'python:3.12-slim'
)

$ErrorActionPreference = 'Stop'
$repo = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..\..')).ProviderPath
$release = (Resolve-Path -LiteralPath $ReleaseDir).ProviderPath
$key = (Resolve-Path -LiteralPath $PrivateKeyPath).ProviderPath
$public = Join-Path $repo 'deploy\release\public-keys\rosy-release-2026-01.pem'
if (-not (Test-Path -LiteralPath $public -PathType Leaf)) { throw 'Trusted public key is missing.' }
if (-not (Test-Path -LiteralPath $release -PathType Container)) { throw 'Release directory is missing.' }
if (-not (Test-Path -LiteralPath $key -PathType Leaf)) { throw 'Private key is missing.' }
if ([IO.Path]::GetFullPath($key).StartsWith([IO.Path]::GetFullPath($release).TrimEnd('\') + '\', [StringComparison]::OrdinalIgnoreCase)) {
    throw 'Private key must stay outside the release directory.'
}

$manifestPath = Join-Path $release 'manifest.json'
$manifest = Get-Content -LiteralPath $manifestPath -Raw -Encoding UTF8 | ConvertFrom-Json
$releaseId = [string]$manifest.release_id
$imageName = [string]$manifest.image.filename
if ($releaseId -notmatch '^\d{4}\.\d{2}\.\d{2}-\d{3}$' -or
    $imageName -ne "rosy-os-pinky-pro-$releaseId-arm64.img.xz" -or
    -not (Test-Path -LiteralPath (Join-Path $release $imageName) -PathType Leaf)) {
    throw 'Image manifest identity or filename is invalid.'
}

$imageId = (& docker image inspect $DockerImage --format '{{.Id}}').Trim()
if ($LASTEXITCODE -ne 0 -or -not $imageId.StartsWith('sha256:')) { throw 'Signing container image is unavailable.' }
$isolation = @('--rm', '--network', 'none', '--read-only', '--tmpfs', '/tmp:rw,noexec,nosuid,size=64m',
    '--cap-drop', 'ALL', '--security-opt', 'no-new-privileges', '--user', '65534:65534')

& docker run @isolation `
    --mount "type=bind,source=$release,target=/release" `
    --mount "type=bind,source=$key,target=/key/private.pem,readonly" `
    --mount "type=bind,source=$repo,target=/repo,readonly" `
    $imageId python /repo/deploy/release/sign_image_release.py /release `
    --private-key /key/private.pem --public-key /repo/deploy/release/public-keys/rosy-release-2026-01.pem
if ($LASTEXITCODE -ne 0) { throw 'Image release signing failed.' }

# Verify in a second container that has no private-key mount.
& docker run @isolation `
    --mount "type=bind,source=$release,target=/release,readonly" `
    --mount "type=bind,source=$repo,target=/repo,readonly" `
    $imageId python /repo/deploy/sd/verify-image-release.py `
    --release-root /release --public-key /repo/deploy/release/public-keys/rosy-release-2026-01.pem `
    --image "/release/$imageName" --release-id $releaseId
if ($LASTEXITCODE -ne 0) { throw 'Signed image release verification failed.' }
