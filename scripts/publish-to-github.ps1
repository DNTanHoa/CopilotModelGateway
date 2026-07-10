[CmdletBinding()]
param(
    [string]$Owner = "DNTanHoa",
    [string]$Repository = "CopilotModelGateway",
    [ValidateSet("private", "public")]
    [string]$Visibility = "private",
    [string]$Description = "Secure local multi-provider model gateway for GitHub Copilot BYOM clients"
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$FullName = "$Owner/$Repository"
$RemoteUrl = "https://github.com/$FullName.git"

function Invoke-NativeChecked {
    param(
        [Parameter(Mandatory = $true)]
        [scriptblock]$Command,
        [Parameter(Mandatory = $true)]
        [string]$FailureMessage
    )

    # Windows PowerShell 5 can turn expected native stderr output into a
    # terminating NativeCommandError when ErrorActionPreference is Stop.
    # Run native commands with Continue, then trust their exit code instead.
    $previousPreference = $ErrorActionPreference
    try {
        $ErrorActionPreference = "Continue"
        & $Command
        $exitCode = $LASTEXITCODE
    }
    finally {
        $ErrorActionPreference = $previousPreference
    }

    if ($exitCode -ne 0) {
        throw "$FailureMessage (exit code $exitCode)."
    }
}

function Test-NativeCommand {
    param(
        [Parameter(Mandatory = $true)]
        [scriptblock]$Command
    )

    $previousPreference = $ErrorActionPreference
    try {
        $ErrorActionPreference = "SilentlyContinue"
        & $Command *> $null
        $exitCode = $LASTEXITCODE
    }
    finally {
        $ErrorActionPreference = $previousPreference
    }

    return ($exitCode -eq 0)
}

function Initialize-LocalRepository {
    Push-Location $Root
    try {
        if (-not (Test-Path ".git")) {
            Invoke-NativeChecked -Command { git init } -FailureMessage "git init failed"
        }

        # Configure an identity only for this repository when Git has none.
        if (-not (Test-NativeCommand { git config --get user.name })) {
            Invoke-NativeChecked -Command { git config user.name $Owner } -FailureMessage "Unable to configure Git user.name"
        }
        if (-not (Test-NativeCommand { git config --get user.email })) {
            Invoke-NativeChecked -Command { git config user.email "$Owner@users.noreply.github.com" } -FailureMessage "Unable to configure Git user.email"
        }

        Invoke-NativeChecked -Command { git add . } -FailureMessage "git add failed"

        $hasHead = Test-NativeCommand { git rev-parse --verify HEAD }
        $changes = git status --porcelain
        if ($LASTEXITCODE -ne 0) {
            throw "git status failed (exit code $LASTEXITCODE)."
        }

        if ($changes) {
            $commitMessage = if ($hasHead) {
                "chore: update gateway"
            }
            else {
                "feat: initial Copilot Model Gateway"
            }

            Invoke-NativeChecked -Command { git commit -m $commitMessage } -FailureMessage "git commit failed"
        }
        elseif (-not $hasHead) {
            throw "There are no files available for the initial commit."
        }

        Invoke-NativeChecked -Command { git branch -M main } -FailureMessage "Unable to rename the branch to main"

        if (Test-NativeCommand { git remote get-url origin }) {
            Invoke-NativeChecked -Command { git remote set-url origin $RemoteUrl } -FailureMessage "Unable to update origin"
        }
        else {
            Invoke-NativeChecked -Command { git remote add origin $RemoteUrl } -FailureMessage "Unable to add origin"
        }
    }
    finally {
        Pop-Location
    }
}

if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
    throw "Git was not found on PATH."
}

Initialize-LocalRepository

if (Get-Command gh -ErrorAction SilentlyContinue) {
    if (Test-NativeCommand { gh auth status }) {
        Push-Location $Root
        try {
            $repoExists = Test-NativeCommand { gh repo view $FullName }

            if (-not $repoExists) {
                $visibilityFlag = "--$Visibility"
                Invoke-NativeChecked `
                    -Command { gh repo create $FullName $visibilityFlag --description $Description } `
                    -FailureMessage "Unable to create GitHub repository"
            }

            Invoke-NativeChecked -Command { git push -u origin main } -FailureMessage "git push failed"
            Write-Host "Published: https://github.com/$FullName" -ForegroundColor Green
            exit 0
        }
        finally {
            Pop-Location
        }
    }
}

Write-Host "GitHub CLI is unavailable or not authenticated." -ForegroundColor Yellow
Write-Host "Enter a fine-grained/classic token that can create and push repositories."
$SecureToken = Read-Host "GitHub token" -AsSecureString
$Bstr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($SecureToken)
$Token = $null
try {
    $Token = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($Bstr)
    $Headers = @{
        Authorization = "Bearer $Token"
        Accept = "application/vnd.github+json"
        "X-GitHub-Api-Version" = "2022-11-28"
        "User-Agent" = "CopilotModelGateway-Publisher"
    }

    $repoExists = $true
    try {
        Invoke-RestMethod -Uri "https://api.github.com/repos/$FullName" -Headers $Headers -Method Get | Out-Null
    }
    catch {
        $statusCode = 0
        if ($_.Exception.Response -and $_.Exception.Response.StatusCode) {
            $statusCode = [int]$_.Exception.Response.StatusCode
        }

        if ($statusCode -eq 404) {
            $repoExists = $false
        }
        else {
            throw
        }
    }

    if (-not $repoExists) {
        $Body = @{
            name = $Repository
            description = $Description
            private = ($Visibility -eq "private")
            auto_init = $false
        } | ConvertTo-Json

        Invoke-RestMethod `
            -Uri "https://api.github.com/user/repos" `
            -Headers $Headers `
            -Method Post `
            -Body $Body `
            -ContentType "application/json" | Out-Null
    }

    $Basic = [Convert]::ToBase64String([Text.Encoding]::ASCII.GetBytes("x-access-token:$Token"))
    Push-Location $Root
    try {
        Invoke-NativeChecked `
            -Command { git -c "http.extraHeader=Authorization: Basic $Basic" push -u origin main } `
            -FailureMessage "git push failed"
    }
    finally {
        Pop-Location
    }

    Write-Host "Published: https://github.com/$FullName" -ForegroundColor Green
}
finally {
    if ($Bstr -ne [IntPtr]::Zero) {
        [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($Bstr)
    }
    $Token = $null
}
