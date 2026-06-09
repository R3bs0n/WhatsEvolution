param(
    [string]$EnvFile = ".env"
)

$ErrorActionPreference = "Stop"

function Read-DotEnv {
    param([string]$Path)

    $values = @{}
    Get-Content $Path | ForEach-Object {
        $line = $_.Trim()
        if (-not $line -or $line.StartsWith("#") -or -not $line.Contains("=")) {
            return
        }

        $key, $value = $line.Split("=", 2)
        $values[$key.Trim()] = $value.Trim().Trim('"').Trim("'")
    }

    return $values
}

$envValues = Read-DotEnv $EnvFile

$requiredKeys = @(
    "EVOLUTION_API_KEY",
    "EVOLUTION_API_URL",
    "EVOLUTION_INSTANCE_NAME",
    "CHATWOOT_URL",
    "CHATWOOT_ACCOUNT_ID",
    "CHATWOOT_TOKEN",
    "CHATWOOT_INBOX_NAME"
)

foreach ($key in $requiredKeys) {
    if (-not $envValues[$key] -or $envValues[$key] -like "SEU_*") {
        throw "Configure $key no arquivo $EnvFile antes de executar este script."
    }
}

$headers = @{
    "apikey" = $envValues["EVOLUTION_API_KEY"]
    "Content-Type" = "application/json"
}

$body = @{
    enabled = $true
    accountId = $envValues["CHATWOOT_ACCOUNT_ID"]
    token = $envValues["CHATWOOT_TOKEN"]
    url = $envValues["CHATWOOT_URL"].TrimEnd("/")
    signMsg = $true
    reopenConversation = $true
    conversationPending = $false
    nameInbox = $envValues["CHATWOOT_INBOX_NAME"]
    mergeBrazilContacts = $true
    importContacts = $true
    importMessages = $true
    daysLimitImportMessages = 2
    signDelimiter = "`n"
    autoCreate = $true
    organization = $envValues["CHATWOOT_ORGANIZATION"]
    logo = $envValues["CHATWOOT_LOGO"]
    ignoreJids = @()
} | ConvertTo-Json -Depth 5

$instance = $envValues["EVOLUTION_INSTANCE_NAME"]
$evolutionApiUrl = $envValues["EVOLUTION_API_URL"].TrimEnd("/")
$uri = "$evolutionApiUrl/chatwoot/set/$instance"

Invoke-RestMethod -Method POST -Uri $uri -Headers $headers -Body $body
Write-Host "Chatwoot configurado na instancia '$instance'."
