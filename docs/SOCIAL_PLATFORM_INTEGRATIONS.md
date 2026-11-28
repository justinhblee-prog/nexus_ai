# NEXUS social platform and multi-account integrations

## Product behavior

NEXUS uses one NEXUS user login and one or more workspaces. Each workspace can connect multiple accounts from each supported social provider. Customers do not create developer apps or configure OAuth redirect URIs; NEXUS operates the provider applications centrally and each customer authorizes their own account from the NEXUS account hub.

Social connections and publishing destinations are scoped to the workspace. Provider credentials remain server-side and encrypted. A workspace owner or admin manages connections. Do not expose access or refresh tokens to the browser.

## Current implementation status

| Platform | Account connection | Multiple accounts | Publishing status |
| --- | --- | --- | --- |
| YouTube | Google Web OAuth | Supported by the workspace connection model | Existing private-upload workflow; final human approval remains required |
| TikTok | TikTok Login Kit Web OAuth v2 | Supported by the workspace connection model | Account/profile connection only. Video publishing is not enabled |
| Instagram | Not enabled | Schema/catalog prepared | Planned; Meta app and Instagram publishing permissions required |
| Facebook | Not enabled | Schema/catalog prepared | Planned; Meta Page and Reels permissions required |
| LinkedIn | Not enabled | Schema/catalog prepared | Planned; LinkedIn app and posting permissions required |

The provider catalogue must never mark a provider connectable unless its server-side OAuth adapter is implemented and the required environment variables are present. A connected account does not imply that the corresponding publishing API has been approved.

## TikTok operator setup (Preview first)

1. In TikTok for Developers, create one NEXUS application and enable Login Kit for Web.
2. Register this exact Preview redirect URI in the app's Web redirect URI list:

   `https://neural-network-git-feat-nexus-user-onbo-509390-justinhblee-9540.vercel.app/api/hosted/tiktok/callback`

3. In Vercel, set these variables for the NEXUS Preview project/branch only:
   - `NEXUS_TIKTOK_CLIENT_KEY`
   - `NEXUS_TIKTOK_CLIENT_SECRET`
   - `NEXUS_TIKTOK_OAUTH_REDIRECT_URI` = the exact URI above
   - `NEXUS_HOSTED_APP_URL` = `https://neural-network-git-feat-nexus-user-onbo-509390-justinhblee-9540.vercel.app`
4. Keep the client secret in Vercel's encrypted environment-variable store. Never commit it or paste it into chat.
5. Test with an owner/admin account. The NEXUS UI should change TikTok from “운영자 설정 필요” to “연결 가능”; then the owner/admin can add more than one TikTok account to the same workspace.

TikTok OAuth initially requests only `user.info.basic` for account identity. It does not request or imply publishing permission. Before enabling TikTok publishing, implement the Content Posting API flow, obtain the required `video.publish` scope and provider approval, and keep the NEXUS human approval gate before every publish operation.

## Customer experience

1. Sign up or log in to NEXUS once.
2. Open the workspace's **멀티 플랫폼 계정 관리** section.
3. Choose a platform and select **계정 추가**.
4. Sign in to that provider and grant the requested permissions.
5. Repeat to add additional accounts. The customer never opens Google Cloud Console, TikTok for Developers, Meta Developer Console, or LinkedIn Developer Portal.

## Production rollout gates

- Choose and verify the permanent customer-facing domain before registering production OAuth redirect URIs.
- Register the production callback separately with each provider and configure Production environment variables only after explicit production approval.
- Complete provider app review, tenant-isolation tests, token refresh/revocation tests, and platform-specific private/draft publishing tests.
- Do not enable public publishing or scheduled posting until provider permissions, audit requirements, rate limits, privacy settings, and rollback behavior are verified.
- Do not apply the new Supabase migration to the live project as part of Preview development. Keep it in the Draft PR until the migration review gate is explicitly passed.
