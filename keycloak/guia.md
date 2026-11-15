Como obtener un token:

function Get-Token($user) {
  (Invoke-RestMethod -Method Post `
    -Uri "http://localhost:8080/realms/medicitas/protocol/openid-connect/token" `
    -Body @{ grant_type="password"; client_id="medicitas-api"; username=$user; password='Medicitas123!' }
  ).access_token
}

Get-Token plataforma  