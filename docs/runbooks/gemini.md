# Gemini Runbook

Gemini is used only by determination and pipeline-owned generation.

## Required Environment

```text
GOOGLE_CLOUD_PROJECT
GOOGLE_CLOUD_LOCATION
GEMINI_MODEL
```

The local Python client uses Application Default Credentials (ADC). Check the
currently authenticated account without printing credentials:

```powershell
gcloud auth application-default print-access-token
```

To replace ADC with the intended Google account:

```powershell
gcloud auth application-default login your-account@example.com
```

## Verification

Run a minimal project request through the normal client configuration. A
successful request verifies environment configuration, ADC, Vertex IAM, model
availability, and network access. Do not put credentials or access tokens in
logs, commits, or issue text.

If Vertex returns `aiplatform.endpoints.predict` permission denied, grant the
ADC principal an appropriate Vertex AI prediction role for the configured
project/model, then retry.
