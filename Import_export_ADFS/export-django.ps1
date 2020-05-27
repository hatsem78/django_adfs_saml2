# The directory where the relying parties should be extracted
$filePathBase = “C:\”

$AdfsRelyingPartyTrusts = Get-AdfsRelyingPartyTrust -Name 'django'


foreach ($AdfsRelyingPartyTrust in $AdfsRelyingPartyTrusts){
    Write-Host $AdfsRelyingPartyTrust
    $rpIdentifier = $AdfsRelyingPartyTrust.Identifier[0]
    $fileNameSafeIdentifier = 'django'
    Write-Host $fileNameSafeIdentifier
    $filePath = $filePathBase + $fileNameSafeIdentifier + ‘.xml’
    $AdfsRelyingPartyTrust | Export-Clixml $filePath

}