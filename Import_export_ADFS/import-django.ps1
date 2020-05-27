# The directory where the relying parties should be extracted
$filePathBase = “C:\”

# location where the extracted XML files can be found
$filePathBase = “C:\”

$xmlFile = $filePathBase + "django.xml"
    

if (!(Test-Path -path $xmlFile)){
    “File not found” + $xmlFile
} 
else{
        
    $ADFSRelyingPartyTrust = Import-clixml $xmlFile
        
    $NewADFSRelyingPartyTrust = Add-ADFSRelyingPartyTrust -Identifier $ADFSRelyingPartyTrust.Identifier -Name 'suite_stage'
        
    $rpIdentifierUri = 'https://localhost:8005/saml2/metadata/'

    $rpIdentifier = 'https://localhost:8005/saml2/metadata/'

    Set-ADFSRelyingPartyTrust -TargetIdentifier $rpIdentifier -AutoUpdateEnabled $ADFSRelyingPartyTrust.AutoUpdateEnabled

    Set-ADFSRelyingPartyTrust -TargetIdentifier $rpIdentifier -AutoUpdateEnabled $ADFSRelyingPartyTrust.AutoUpdateEnabled

    Set-ADFSRelyingPartyTrust -TargetIdentifier $rpIdentifierUri -DelegationAuthorizationRules $ADFSRelyingPartyTrust.DelegationAuthorizationRules

    Set-ADFSRelyingPartyTrust -TargetIdentifier $rpIdentifierUri -EncryptionCertificateRevocationCheck $ADFSRelyingPartyTrust.EncryptionCertificateRevocationCheck.ToString()

    # note we need to do a ToString to not just get the enum number
    Set-ADFSRelyingPartyTrust -TargetIdentifier $rpIdentifier -EncryptionCertificateRevocationCheck $ADFSRelyingPartyTrust.EncryptionCertificateRevocationCheck.ToString()

    Set-ADFSRelyingPartyTrust -TargetIdentifier $rpIdentifier -IssuanceAuthorizationRules $ADFSRelyingPartyTrust.IssuanceAuthorizationRules

    # note we need to do a ToString to not just get the enum number
    Set-ADFSRelyingPartyTrust -TargetIdentifier $rpIdentifier -SigningCertificateRevocationCheck $ADFSRelyingPartyTrust.SigningCertificateRevocationCheck.ToString()

    Set-ADFSRelyingPartyTrust -TargetIdentifier $rpIdentifier -WSFedEndpoint $ADFSRelyingPartyTrust.WSFedEndpoint

    Set-ADFSRelyingPartyTrust -TargetIdentifier $rpIdentifier -IssuanceTransformRules $ADFSRelyingPartyTrust.IssuanceTransformRules

    # Note ClaimAccepted vs ClaimsAccepted (plural)
    Set-ADFSRelyingPartyTrust -TargetIdentifier $rpIdentifier -ClaimAccepted $ADFSRelyingPartyTrust.ClaimsAccepted

    ### NOTE this does not get imported
    #$ADFSRelyingPartyTrust.ConflictWithPublishedPolicy

    Set-ADFSRelyingPartyTrust -TargetIdentifier $rpIdentifier -EncryptClaims $ADFSRelyingPartyTrust.EncryptClaims

    ### NOTE this does not get imported
    #$ADFSRelyingPartyTrust.Enabled

    Set-ADFSRelyingPartyTrust -TargetIdentifier $rpIdentifier -EncryptionCertificate $ADFSRelyingPartyTrust.EncryptionCertificate

    # Identifier is actually an array but you can’t add it when
    # using Set-ADFSRelyingPartyTrust -TargetIdentifier
    # so we use -TargetRelyingParty instead
    $targetADFSRelyingPartyTrust = Get-ADFSRelyingPartyTrust -Identifier $rpIdentifier
    Set-ADFSRelyingPartyTrust -TargetRelyingParty $targetADFSRelyingPartyTrust -Identifier $ADFSRelyingPartyTrust.Identifier

    # SKIP we don’t need to import these
    # $ADFSRelyingPartyTrust.LastMonitoredTime
    # $ADFSRelyingPartyTrust.LastPublishedPolicyCheckSuccessful
    # $ADFSRelyingPartyTrust.LastUpdateTime

    Set-ADFSRelyingPartyTrust -TargetIdentifier $rpIdentifier ` -MetadataUrl $ADFSRelyingPartyTrust.MetadataUrl

    Set-ADFSRelyingPartyTrust -TargetIdentifier $rpIdentifier -MonitoringEnabled $ADFSRelyingPartyTrust.MonitoringEnabled

    # Name is already done
    #Set-ADFSRelyingPartyTrust -TargetIdentifier $rpIdentifier -Name $ADFSRelyingPartyTrust.Name

    Set-ADFSRelyingPartyTrust -TargetIdentifier $rpIdentifier -NotBeforeSkew $ADFSRelyingPartyTrust.NotBeforeSkew

    Set-ADFSRelyingPartyTrust -TargetIdentifier $rpIdentifier -Notes “$ADFSRelyingPartyTrust.Notes”

    ### NOTE this does not get imported
    #$ADFSRelyingPartyTrust.OrganizationInfo

    Set-ADFSRelyingPartyTrust -TargetIdentifier $rpIdentifier -ImpersonationAuthorizationRules $ADFSRelyingPartyTrust.ImpersonationAuthorizationRules

    Set-ADFSRelyingPartyTrust -TargetIdentifier $rpIdentifier -ProtocolProfile $ADFSRelyingPartyTrust.ProtocolProfile

    Set-ADFSRelyingPartyTrust -TargetIdentifier $rpIdentifier -RequestSigningCertificate $ADFSRelyingPartyTrust.RequestSigningCertificate

    Set-ADFSRelyingPartyTrust -TargetIdentifier $rpIdentifier -EncryptedNameIdRequired $ADFSRelyingPartyTrust.EncryptedNameIdRequired

    # Note RequireSignedSamlRequests vs SignedSamlRequestsRequired,
    #Set-ADFSRelyingPartyTrust -TargetIdentifier $rpIdentifier -RequireSignedSamlRequests $ADFSRelyingPartyTrust.SignedSamlRequestsRequired
    Set-ADFSRelyingPartyTrust -TargetIdentifier $rpIdentifier -SignedSamlRequestsRequired $ADFSRelyingPartyTrust.SignedSamlRequestsRequired

    # Note SamlEndpoint vs SamlEndpoints (plural)
    # The object comes back as a
    # [Deserialized.Microsoft.IdentityServer.PowerShell.Resources.SamlEndpoint]
    # so we will reconstitute

    # create a new empty array
    $newSamlEndPoints = @()
    foreach ($SamlEndpoint in $ADFSRelyingPartyTrust.SamlEndpoints){
        # Is ResponseLocation defined?
        if ($SamlEndpoint.ResponseLocation){
            # ResponseLocation is not null or empty
            $newSamlEndPoint = New-ADFSSamlEndpoint -Binding $SamlEndpoint.Binding -Protocol $SamlEndpoint.Protocol -Uri $SamlEndpoint.Location -Index $SamlEndpoint.Index -IsDefault $SamlEndpoint.IsDefault
            }
        else{
            $newSamlEndPoint = New-ADFSSamlEndpoint -Binding $SamlEndpoint.Binding -Protocol $SamlEndpoint.Protocol -Uri $SamlEndpoint.Location -Index $SamlEndpoint.Index -IsDefault $SamlEndpoint.IsDefault -ResponseUri $SamlEndpoint.ResponseLocation
        }
        $newSamlEndPoints += $newSamlEndPoint
    }
    Set-ADFSRelyingPartyTrust -TargetIdentifier $rpIdentifier -SamlEndpoint $newSamlEndPoints

    Set-ADFSRelyingPartyTrust -TargetIdentifier $rpIdentifier -SamlResponseSignature $ADFSRelyingPartyTrust.SamlResponseSignature

    Set-ADFSRelyingPartyTrust -TargetIdentifier $rpIdentifier -SignatureAlgorithm $ADFSRelyingPartyTrust.SignatureAlgorithm

    Set-ADFSRelyingPartyTrust -TargetIdentifier $rpIdentifier -TokenLifetime $ADFSRelyingPartyTrust.TokenLifetime

}

