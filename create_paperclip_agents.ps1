# Script pour créer Risk Manager et Head Analyst via l'API Paperclip
# Prérequis : démarrer le serveur Paperclip (npx paperclipai run) avant d'exécuter

$CompanyId = "8fe5f91f-1be8-4274-90ef-be9300d04c64"
$BaseUrl = "http://127.0.0.1:3100"
$AdapterConfig = @{
    cwd = "C:\Users\emery\NEXUS CAPITAL MATT"
    model = "claude-sonnet-4-20250514"
}

# Essayer le port 3101 si 3100 est occupé
try {
    $health = Invoke-RestMethod -Uri "$BaseUrl/api/health" -Method Get -ErrorAction Stop
} catch {
    $BaseUrl = "http://127.0.0.1:3101"
}

$agents = @(
    @{
        name = "Risk Manager"
        title = "Risk Manager"
        role = "cfo"
        adapterType = "claude_local"
        adapterConfig = $AdapterConfig
    },
    @{
        name = "Head Analyst"
        title = "Head Analyst"
        role = "researcher"
        adapterType = "claude_local"
        adapterConfig = $AdapterConfig
    }
)

foreach ($agent in $agents) {
    $body = $agent | ConvertTo-Json -Depth 5
    Write-Host "Creation de l'agent: $($agent.name)..."
    try {
        $result = Invoke-RestMethod -Uri "$BaseUrl/api/companies/$CompanyId/agents" -Method Post -Body $body -ContentType "application/json"
        Write-Host "  OK: $($agent.name) cree (id: $($result.id))" -ForegroundColor Green
    } catch {
        Write-Host "  ERREUR: $_" -ForegroundColor Red
    }
}
