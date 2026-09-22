Describe "prepare-rosy-sd.ps1 edge cases" {
    BeforeAll {
        $global:scriptPath = Resolve-Path "deploy/sd/prepare-rosy-sd.ps1"
        $global:testDir = Join-Path $pwd "deploy/sd/test/tmp"
        if (Test-Path $global:testDir) { Remove-Item $global:testDir -Recurse -Force }
        New-Item -ItemType Directory -Path $global:testDir | Out-Null
        
        $invPath = Join-Path $global:testDir "inventory.json"
        '[{"Number": 1, "FriendlyName": "Mock Disk", "SerialNumber": "123", "Size": 16000000000, "BusType": "USB", "IsBoot": false, "IsSystem": false, "IsOffline": false, "IsReadOnly": false}]' | Set-Content $invPath
    }
    
    AfterAll {
        if (Test-Path $global:testDir) { Remove-Item $global:testDir -Recurse -Force }
    }

    Context "Validation edge cases" {
        BeforeEach {
            # Let's create the profile using the exact same path logic as the script:
            $credPath = Join-Path ([Environment]::GetFolderPath("LocalApplicationData")) "rosy-os\wifi\test_profile.xml"
            $directory = Split-Path -Parent $credPath
            if (-not (Test-Path $directory)) { New-Item -ItemType Directory -Path $directory -Force | Out-Null }
            $pass = ConvertTo-SecureString "mockpassword" -AsPlainText -Force
            $cred = New-Object System.Management.Automation.PSCredential ("mockssid", $pass)
            $cred | Export-Clixml -Path $credPath -Force
        }
        
        It "Fails when RegistryJson is missing" {
            $inv = Join-Path $global:testDir "inventory.json"
            { & $scriptPath -DiskNumber 1 -RobotNumber 1 -WifiProfile "test_profile" -WifiSsid "test" -ImagePath "img" -ImageSha256 "sha" -ImageSignaturePath "sig" -ReleasePublicKey "pub" -ReleaseId "2026.09.22-001" -FleetEndpoint "https://fleet.local" -FleetTrustProfile "trust" -DeviceName "rosy-pinky-a2cd" -DeviceUid "84b72624-95e5-47df-8f5f-f32a392b45ba" -RegistryJson "missing.json" -ReceiptPath "receipt.json" -DiskInventoryJson $inv -PlanOnly } | Should Throw "identity registry is missing"
        }
        
        It "Fails when RpiImager is unavailable" {
            $inv = Join-Path $global:testDir "inventory.json"
            $reg = Join-Path $global:testDir "registry.json"
            Set-Content -Path $reg -Value "{}"
            $pub = Join-Path $global:testDir "pub.pem"
            Set-Content -Path $pub -Value "mock"
            
            { & $scriptPath -DiskNumber 1 -RobotNumber 1 -WifiProfile "test_profile" -WifiSsid "test" -ImagePath "img" -ImageSha256 "sha" -ImageSignaturePath "sig" -ReleasePublicKey $pub -ReleaseId "2026.09.22-001" -FleetEndpoint "https://fleet.local" -FleetTrustProfile "trust" -DeviceName "rosy-pinky-a2cd" -DeviceUid "84b72624-95e5-47df-8f5f-f32a392b45ba" -RegistryJson $reg -ReceiptPath "receipt.json" -DiskInventoryJson $inv -RpiImager "non_existent_imager.exe" -PlanOnly } | Should Throw "Raspberry Pi Imager CLI is unavailable"
        }
    }
}
