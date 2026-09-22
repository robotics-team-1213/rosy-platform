Describe "prepare-rosy-sd.ps1 edge cases" {
    BeforeAll {
        $global:scriptPath = Resolve-Path "deploy/sd/prepare-rosy-sd.ps1"
        $global:testDir = Join-Path $pwd "deploy/sd/test/tmp"
        if (Test-Path $global:testDir) { Remove-Item $global:testDir -Recurse -Force }
        New-Item -ItemType Directory -Path $global:testDir | Out-Null
    }
    
    AfterAll {
        if (Test-Path $global:testDir) { Remove-Item $global:testDir -Recurse -Force }
    }

    Context "Validation edge cases" {
        It "Fails when RegistryJson is missing" {
            { & $scriptPath -DiskNumber 1 -RobotNumber 1 -WifiProfile "test" -WifiSsid "test" -ImagePath "img" -ImageSha256 "sha" -ImageSignaturePath "sig" -ReleasePublicKey "pub" -ReleaseId "rel" -FleetEndpoint "http" -FleetTrustProfile "trust" -DeviceName "dev" -DeviceUid "uid" -RegistryJson "missing.json" -ReceiptPath "receipt.json" -PlanOnly } | Should Throw "identity registry is missing"
        }
        
        It "Fails when RpiImager is unavailable" {
            $reg = Join-Path $global:testDir "registry.json"
            Set-Content -Path $reg -Value "{}"
            $pub = Join-Path $global:testDir "pub.pem"
            Set-Content -Path $pub -Value "mock"
            
            { & $scriptPath -DiskNumber 1 -RobotNumber 1 -WifiProfile "test" -WifiSsid "test" -ImagePath "img" -ImageSha256 "sha" -ImageSignaturePath "sig" -ReleasePublicKey $pub -ReleaseId "rel" -FleetEndpoint "http" -FleetTrustProfile "trust" -DeviceName "dev" -DeviceUid "uid" -RegistryJson $reg -ReceiptPath "receipt.json" -RpiImager "non_existent_imager.exe" -PlanOnly } | Should Throw "Raspberry Pi Imager CLI is unavailable"
        }
    }
}
