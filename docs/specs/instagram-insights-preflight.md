# Owner guide for the Instagram Insights preflight

Phase 4B1A prepares **one identity GET** for a future owner decision after ChatGPT reviews the PR. Anyone can preview the plan offline. A matching professional account is the most this command can establish. The current Insights grant and metric availability remain unknown.

## Prepare the account and app

Consulted Meta's public documentation on **2026-11-19**. Account setup and credential issuance below are later owner actions. This phase performed neither.

1. In Instagram, open the intended profile's settings and account tools. Confirm the professional dashboard and Business or Creator account type. If the profile is personal, the owner must separately decide whether to switch it to a public professional account. Record the local numeric destination configuration ID and independently identify its expected numeric Instagram professional **user_id**. A username, Facebook Page ID and the Instagram app-scoped **id** identify different things. Stop if the mapping is unavailable. [Instagram Login and professional accounts](https://developers.facebook.com/documentation/instagram-platform/instagram-api-with-instagram-login) · [Identity fields](https://developers.facebook.com/documentation/instagram-platform/instagram-api-with-instagram-login/get-started)
2. In the Meta App Dashboard create or select a dedicated Business app, add Instagram and choose **API setup with Instagram login**. Record its **Instagram App ID** from Business login settings. Add the owned or managed account, assign the appropriate app role and have the account accept any tester invitation. Check app mode and eligibility for that account. Standard Access applies to eligible accounts owned or managed and added to the app. For other users, stop and resolve Advanced Access, App Review and any business verification in the dashboard. Observe Meta's Platform Terms, data use, privacy, deletion and revocation requirements. [App setup](https://developers.facebook.com/documentation/instagram-platform/create-an-instagram-app) · [Access levels](https://developers.facebook.com/documentation/instagram-platform/insights) · [Platform Terms](https://developers.facebook.com/terms/)
3. Configure Business Login for Instagram with the exact HTTPS redirect URI you control and validate OAuth state in your private server-side flow. Request **only** `instagram_business_basic` and `instagram_business_manage_insights`. Read the actual returned permissions. A role, the requested scope list or an existing publishing token is insufficient. If the dashboard or consent flow cannot issue exactly this pair, stop. Keep app secrets in that server's secret store. This CLI cannot perform OAuth. [Business Login and token exchange](https://developers.facebook.com/documentation/instagram-platform/instagram-api-with-instagram-login/business-login) · [Insights permissions](https://developers.facebook.com/documentation/instagram-platform/insights)
4. Capture the granted permissions and issuance time from that flow, then the long-lived exchange's actual bearer token type and expiration. Associate both responses with the same account, app and credential generation in the owner-controlled secret store. The short-lived login token normally lasts one hour and a long-lived exchange can yield about 60 days. Use the actual expiry. The preflight accepts a grant record at most one hour old. Refreshing a long-lived token does not refresh evidence of grants. If the necessary fields or their provenance are missing, obtain a fresh dedicated grant under a separate setup decision. [Token fields and lifetimes](https://developers.facebook.com/documentation/instagram-platform/instagram-api-with-instagram-login/business-login)

## Provision one private credential record

Use a local password manager or the login Keychain. Reserve a dedicated generic-password item named `content-factory/instagram-insights-preflight` for this purpose, with the Instagram App ID as its Keychain account. Store the following JSON object as the item's secret value using your private provisioning flow or Keychain Access. The field descriptions below are a format reference. Keep the actual record out of files, shell command arguments, history, chat, screenshots, reports, tests and Git.

| JSON fields | Values and source |
| --- | --- |
| `destination_id`, `account_id`, `app_id` | Decimal strings from the owner's destination mapping, expected professional user_id and Instagram App Dashboard. Verify the namespace independently. |
| `credential_revision` | New nonsecret, random 32-character lowercase hex identifier for each issuance. Generate with `python3 -c 'import secrets; print(secrets.token_hex(16))'`. Use the same revision in the preview. |
| `login`, `token_type`, `access_token` | String `instagram_login`, observed `bearer`, and the private Instagram User access token from that exchange. |
| `permissions` | Array of exactly the two **granted** scope strings listed above, parsed from the issuance response. Preserve extra or missing grants so the tool can refuse them. |
| `issued_at`, `expires_at` | Integer Unix seconds in UTC. Use original grant issuance time and the bearer token's actual absolute expiration (exchange time plus returned lifetime). |

Rotation means replacing the entire item, assigning a new revision and reviewing a new plan. To revoke, remove the app's access in Instagram's Apps and Websites settings, delete the Keychain item and discard outstanding approvals. Removing a local item alone does not revoke the grant at Meta. Abort on a stale record, unexpected permissions, revoked access or ambiguous ownership. A fresh grant record describes provisioning only. [Instagram app permissions](https://help.instagram.com/1144624522593085/)

## Preview and review

From the repository root, the following command works with no configuration and prints the plan. It reads no credential, opens no database and makes no network request.

```sh
.venv/bin/python scripts/instagram_insights_preflight.py
```

For the owner-specific preview, set the four **nonsecret** shell variables below from the independently verified mapping. Use Bash or zsh. Run the preview without loading the Keychain item.

```sh
plan_args=(--destination-id "$DESTINATION_ID" --account-id "$IG_USER_ID"
           --app-id "$IG_APP_ID" --credential-revision "$REVISION" --max-gets 1)
.venv/bin/python scripts/instagram_insights_preflight.py "${plan_args[@]}"
```

Review the exact binding, URL, grant pair, exclusions, time/byte budgets and `plan_sha256` in the JSON. Every run uses the same single allowlisted target:

```text
GET https://graph.instagram.com/v27.0/me?fields=user_id,account_type
```

The target follows Meta's v27 Instagram Login identity guide. Its example uses a query token. Meta documents the long-lived Instagram Login token type as bearer. This tool accepts that token type and uses the standard HTTPS Authorization header exclusively. The owner-specific result of header authentication, response version, namespace, shape and fields remains unverified. Rejection ends the attempt. The Phase 3B2 publishing candidate uses a separately gated v26 profile. [Identity request and fields](https://developers.facebook.com/documentation/instagram-platform/instagram-api-with-instagram-login/get-started) · [Bearer exchange response](https://developers.facebook.com/documentation/instagram-platform/instagram-api-with-instagram-login/business-login) · [Bearer header transport](https://www.rfc-editor.org/rfc/rfc6750#section-2.1)

**Local readiness report.** Dry-run is available. External prerequisites are pending. The request budget is one GET, with a three-second socket timeout, eight-second wall deadline including DNS/TLS/body, and 16 KiB each for accepted response headers and body. No redirects, retries, pagination, media or Insights requests. No storage, publication, quota, billing or measurement operations. A source hash and allowlisted classifications are the only response evidence in stdout. The tool retains no replies or reports.

## Later owner-authorized verification

After PR review, the owner must separately approve **one manual invocation**, the reviewed code revision, plan digest, destination, Instagram app/account, credential revision, budgets and time of execution. A dry run or PR approval grants no permission to call the API. Use a private, trusted POSIX terminal on the owner's workstation. Check app/account rate status and system time first. Abort before confirmation with Ctrl-C if any input has changed.

For that future run only, set `REVIEWED_DIGEST` to the reviewed preview hash. The macOS example injects the dedicated item into the CLI process via a subshell. Shell tracing is disabled before secret retrieval. Use the Keychain UI for entry and restrict access to the owner's login. Do not use a shared terminal recorder, environment dump, debugger or TLS inspection proxy.

```sh
(
  set +x
  ulimit -c 0 || exit 1
  CONTENT_FACTORY_IG_PREFLIGHT_RECORD="$(/usr/bin/security find-generic-password \
    -s content-factory/instagram-insights-preflight -a "$IG_APP_ID" -w)" || exit 1
  export CONTENT_FACTORY_IG_PREFLIGHT_RECORD
  exec .venv/bin/python scripts/instagram_insights_preflight.py "${plan_args[@]}" \
    --execute --confirm-reviewed-plan "$REVIEWED_DIGEST"
)
```

The CLI reprints the plan, compares its digest, and asks the owner to type a fresh plan-bound challenge within 120 seconds. Piped input is refused. Only then does it resolve the injected record and validate binding, grant age, exact scopes, token type and expiry. It attempts one verified-TLS GET with an empty body. It accepts a single matching Business or Creator node (or a one-row data envelope), JSON and the exact v27.0 response-version header. It reports the expected binding, identity/token/permission states, timestamp and bounded response hash where available. Exit 0 means the preview printed or identity matched. Inspect the explicit mode/status. A blocked run exits 2.

Stop on any refusal, mismatch, deadline, malformed response, missing field, 401/403, rate limit or server error. Ctrl-C during a request may arrive after Meta received it. No automatic replay. After a throttle consult the account's recovery information before considering a separately approved fresh plan. Share only the safe report as needed and keep account identifiers private.

| Gate | Acceptance |
| --- | --- |
| 4B1A implementation | Pure preview, one-shot owner confirmation and constrained HTTPS execution tested offline using fake responses. No verified owner account. |
| Current grants and token introspection | Blocked. Meta's documented debug endpoint uses graph.facebook.com, an input-token parameter and an app or app-developer credential. It is outside the allowlist. Owner/reviewer must establish a documented current grant, app and expiry readback compatible with Instagram Login and the credential boundary. The CLI cannot substitute an issuance record or identity success for this proof. [Debug Token](https://developers.facebook.com/docs/graph-api/reference/debug_token/) |
| 4B1B authenticated read-only evidence | Separate review and owner authorization for any grant-validation change and any first account reach GET, metric window or receipt verification. Metric support remains untested. |
| 4B2 authenticated issuer | Separate schema-v20 issuer review. The existing measurement writer accepts synthetic platform observations only. [Measurement contract](measurement.md) |
