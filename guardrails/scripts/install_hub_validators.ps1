# Requires: guardrails-ai installed and on PATH (or use python -m guardrails)
# Installs the listed Guardrails Hub validators.

$validators = @(
    "hub://groundedai/grounded_ai_hallucination",
    "hub://guardrails/valid_json",
    "hub://guardrails/unusual_prompt",
    "hub://guardrails/regex_match",
    "hub://guardrails/detect_pii",
    "hub://guardrails/toxic_language",
    "hub://guardrails/valid_url",
    "hub://guardrails/detect_jailbreak",
    "hub://tryolabs/restricttotopic",
    "hub://guardrails/guardrails_pii",
    "hub://guardrails/sensitive_topics"
)

foreach ($v in $validators) {
    Write-Host "Installing $v ..."
    # Prefer module invocation for cross-platform reliability
    python -m guardrails hub install $v
    if ($LASTEXITCODE -ne 0) {
        Write-Warning "Failed to install $v via python -m guardrails. Trying 'guardrails' CLI..."
        try {
            guardrails hub install $v
        } catch {
            Write-Error "Installation failed for $v"
        }
    }
}

Write-Host "All validators processed."