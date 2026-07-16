# Document-discussion comment body rendering regression pattern

## Symptom

Den Web can show that a document discussion has comments, but no readable root comment bodies appear in the Discussion tab.

## Durable cause pattern

The raw API response may be valid while the UI render tree drops records because it assumes nullable fields are always present. For document discussion comments, Core can omit `parent_comment_id` for root comments. A strict root filter like:

```ts
comment.parent_comment_id === null
```

excludes root comments where `parent_comment_id` is `undefined`. The comment count may still be correct if it comes from the raw comments array, creating a confusing "comments exist but bodies are invisible" failure.

## Debugging sequence

1. Fetch the document discussion endpoint directly from the browser or API client and inspect the first comment's keys and `body_markdown` length.
2. Compare the wire payload to Den Web TypeScript types. Treat omitted nullable fields as a real wire-shape possibility, not as missing data.
3. Inspect component grouping/filtering logic before changing markdown rendering or CSS.
4. Check CSS only after confirming records enter the render tree.

## Fix shape

- Update the API/client type to reflect the wire format, e.g. `parent_comment_id?: number | null`.
- Normalize comments in the API client so missing `parent_comment_id` becomes `null` for downstream consumers.
- Make component threading tolerant with nullish checks:
  - roots: `comment.parent_comment_id == null`
  - replies: `comment.parent_comment_id != null`
- Preserve explicit reply parent IDs.

## Regression coverage

Add a focused Vitest/client test with a Core-style payload where a root comment has `body_markdown` but omits `parent_comment_id`, plus a reply that includes a parent ID. Assert that the normalized root has `parent_comment_id: null`, the body text is preserved, and reply threading/source checks would catch a stale `=== null` root filter.

## Verification

After tests/build pass and the app is deployed, browser-verify the actual affected document Discussion tab: the target author, timestamp, and body text should be visible, not just the comment count.
