# PR merge troubleshooting (emoji-toggle change)

If GitHub shows **"Unable to merge"** for this change, the issue is usually branch drift
against the target branch head, not test/runtime failures.

Recommended recovery flow:

1. Create a fresh branch from the latest target branch HEAD.
2. Cherry-pick only feature commits related to emoji toggle:
   - admin handler + router registration
   - keyboard fallback logic
   - startup setting load
   - focused regression test file
3. Push the fresh branch and open a new PR.
4. Verify "This branch has no conflicts with the base branch" before requesting review.
