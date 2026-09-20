# X Integration

**Owner:** Implemented single-post delivery and readiness behavior.
**Code:** `src/workflow/delivery.py`, `src/workflow/readiness.py`.
X delivery is on hold. Synthetic X planning bindings do not require X credentials
and cannot publish.

## Configuration and protocol

Production freezes a numeric account ID, `X_USER_ACCESS_TOKEN` secret reference,
`https://api.x.com` origin, image-byte limit and account posting policy.
Readiness calls `GET /2/users/me` and requires the exact configured identity.

The adapter:

1. revalidates the reviewed single JPEG and locally weighted post text;
2. uploads base64 media to `POST /2/media/upload`, requiring numeric `data.id`;
3. sends frozen alt text to `POST /2/media/metadata`;
4. receives permission from the Posting Agent's durable final-marker transaction;
5. sends immutable text/media ID to `POST /2/tweets`.

There is no R2 dependency for X. Local configuration uses a 5 MB image ceiling.
[Platform outputs](../specs/platform-outputs.md#x--x_static_post_v1) owns copy
limits and the incomplete `twitter-text` compatibility boundary;
[visual rendering](../specs/visual-rendering.md) owns image geometry.
A possibly sent final request is unknown, never automatically retried.

## Reconciliation and limits

Explicit reconciliation reads at most ten recent posts and compares exact text.
All results require human resolution; a missing match is not proof of absence.
[Posting](../specs/posting.md#reconciliation) owns authorization and recovery.

X threads are unsupported. The application has no per-post thread state,
published-prefix recovery or multi-post cadence accounting. Those are future
requirements, not a disabled working feature.

Before enabling delivery, verify user-context permissions, account entitlements,
current provider limits, upload/alt-text behavior, costs/rate limits and weighted
text boundary strings. A successful local test does not establish any of them.
Only an exact human Post now command authorizes a real post.

## External references for activation

- [Upload media](https://docs.x.com/x-api/media/upload-media)
- [Create a post](https://docs.x.com/x-api/posts/create-or-edit-post)
- [Media and metadata](https://docs.x.com/x-api/media/introduction)
- [API access](https://docs.x.com/x-api/getting-started/getting-access)
- [Character counting](https://docs.x.com/fundamentals/counting-characters)
- [twitter-text configuration](https://github.com/twitter/twitter-text/blob/master/config/v3.json)
