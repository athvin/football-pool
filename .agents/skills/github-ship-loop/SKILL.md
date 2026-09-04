---
name: github-ship-loop
description: Shepherd an explicitly requested GitHub change through pull request creation, CI repair, merge, deployment repair, review-note follow-up, and production verification. Use only when the user explicitly invokes $github-ship-loop; do not use for ordinary coding, PR creation alone, CI inspection alone, or deployments that the user has not authorized.
---

# GitHub Ship Loop

Ship the current change all the way to a verified production result. Use the
GitHub CLI for GitHub state and preserve one evidence trail across the original
pull request and any post-merge repair pull requests.

## Scope and authority

This skill is explicit-only. When the user invokes it to ship a change, that
invocation authorizes the normal mutations needed for this workflow: create or
update a feature branch and pull request, push tested commits, merge after
repository requirements pass, and create fresh repair pull requests for
repository-fixable post-merge or production failures. Respect any narrower
scope in the user's invocation.

It does not authorize:

- pushing directly to the default branch;
- force-pushing, bypassing branch protection, using administrator overrides,
  dismissing reviews, or weakening required checks;
- changing repository or organization secrets, permissions, billing, DNS, or
  external infrastructure;
- discarding unrelated or pre-existing local changes;
- broadening a repair beyond the requested change and its delivery path.

Stop and ask for direction when one of those actions is required.

## Completion contract

Do not call the work complete merely because CI is green or a merge command
returned successfully. Completion requires all of the following:

1. Every pull request created by this run is merged.
2. Required checks passed without bypasses.
3. The deployment containing the final merge completed successfully.
4. The requested behavior was verified in the deployed environment.
5. Actionable review notes on every involved pull request were addressed and
   the behavior they concern was retested.

Keep the user informed during waits. Poll in bounded intervals and provide a
concise update at least once per minute during active monitoring.

## 1. Establish the delivery context

Before mutating GitHub state:

- Read applicable `AGENTS.md` files and repository contribution/deployment
  guidance.
- Inspect `git status`, the current branch, remotes, upstream tracking, and the
  diff. Preserve unrelated changes.
- Run `gh auth status` and use `gh repo view` to identify the repository and
  default branch. Do not assume the default branch is named `main`.
- Inspect `.github/workflows/`, branch-protection expectations visible through
  the PR, and repository test/build commands.
- Locate the pull request template in the standard root, `.github/`, or `docs/`
  locations, including template directories.
- Determine whether the current branch or commits already have an open pull
  request. Reuse it when it represents this change; never create a duplicate
  merely because the PR number was not supplied.

If the current work is on the default branch, create a feature branch before
committing or pushing. If local state cannot be moved safely, pause instead of
stashing, resetting, or overwriting the user's work without permission.

## 2. Validate locally and prepare the pull request

Review the complete diff against the user's acceptance criteria. Add or update
tests when needed, then run the repository's relevant formatting, lint, type,
test, build, and smoke checks. Fix local failures before pushing.

Commit only intended files. Use a clear branch and commit message consistent
with repository conventions. Push the feature branch with an upstream when
needed.

For a new pull request:

- Target the actual default branch unless the user or repository specifies a
  different base.
- Preserve the selected pull request template's headings, comments, and
  checklists. Fill every applicable section from observed work and test output;
  mark genuinely irrelevant sections `N/A` with a short reason.
- Include the problem, solution, validation performed, deployment or migration
  implications, and any residual risk.
- Write the filled body to a safely created temporary file and pass it with
  `gh pr create --body-file`; avoid shell interpolation of untrusted text.

If a matching pull request already exists, inspect its title and body and use
`gh pr edit --body-file` only when the template is missing or the content is
stale. Do not erase useful human-authored context.

Record the pull request number and URL. Maintain a list if repair pull requests
are later required.

## 3. Run the PR feedback and CI loop

Inspect the pull request's state, required checks, reviews, issue comments, and
inline review comments with `gh pr view`, `gh pr checks`, and `gh api` as
needed. Do not rely on the web summary alone when inline notes may exist.

While the pull request is open:

1. Wait for required checks to settle.
2. When a check fails, identify its workflow run and inspect failed job logs
   with `gh run view`, limiting output to the relevant failure when practical.
3. Classify the failure before editing: product defect, test expectation,
   formatting/type issue, merge conflict, transient runner failure, or external
   configuration/credential failure.
4. For a repository-fixable failure, reproduce it locally, make the smallest
   correct fix, add regression coverage when appropriate, and rerun the
   relevant local checks.
5. Review the new diff, commit, and push to the same pull request. Return to
   step 1.
6. Rerun a failed workflow without a code change only when evidence indicates
   a transient failure. Never keep rerunning an unexplained failure.

Address actionable review feedback in this same loop. Do not silently resolve
or dismiss a comment; implement and test it, or explain with evidence why no
change is appropriate. Re-check for late-arriving reviews before merge.

If checks require a human approval, unavailable secret, permission change, or
external service repair, report the exact blocker and the run URL. Do not
change code to conceal an infrastructure failure.

## 4. Merge safely

Merge only when the pull request is ready, required checks pass, required
approvals are present, merge conflicts are resolved and retested, and no
actionable review thread remains outstanding.

Use the repository's established merge method. If no convention is discoverable,
use a method GitHub permits without bypassing protection. Never use an admin
override. After `gh pr merge`, verify through GitHub that the PR state is
`MERGED` and record the merge commit SHA; command success alone is insufficient.

## 5. Monitor deployment and repair through new PRs

Identify the deployment workflows and environments associated with the merge
commit. Monitor the workflow chain and deployment status, including follow-on
workflows that may not be attached directly to the original pull request. Do
not treat unrelated green runs as proof that this commit deployed.

If deployment fails:

- Inspect the failed jobs and deployment logs and classify the failure.
- If it is repository-fixable, update from the remote default branch, create a
  fresh repair branch, implement and locally validate the fix, and open a new
  pull request. Link the failed deployment and prior pull request in its body.
- Put that repair pull request through the complete feedback, CI, merge, and
  deployment loop above.
- If the failure requires secrets, permissions, external infrastructure, or a
  manual approval, stop and report the exact required intervention.

Never patch the default branch directly after a failed deployment.

## 6. Verify production and sweep every PR

Determine the deployed URL from repository or deployment metadata rather than
guessing it. After a successful deployment:

- Confirm the deployed revision corresponds to the final merge.
- Exercise the original acceptance criteria in production with the most direct
  reliable method available: HTTP assertions, an existing smoke test, or a
  browser interaction for client-side behavior. A 200 response alone is not
  enough for a behavioral change.
- Revisit issue comments, reviews, and inline comments on the original pull
  request and every repair pull request. Retest the behavior implicated by each
  actionable note.
- If production verification fails and the cause is repository-fixable, create
  another repair pull request and restart the full loop.

## Retry and stopping rules

Continue while each iteration makes evidence-based progress. Never repeat the
same merge, rerun, or code edit blindly. Stop and ask the user when:

- the same root cause remains after three correctly targeted repair attempts;
- GitHub rate limits, missing authentication, missing permissions, required
  manual approval, unavailable secrets, or external infrastructure prevent
  progress;
- the next repair materially expands scope or risk;
- production behavior cannot be observed reliably enough to claim success.

On stopping, leave the repository in a safe state and report the failing PR or
run, evidence gathered, attempts made, and the smallest next human action.

## Final report

Report:

- every pull request URL and merge commit;
- the required checks and deployment run that passed;
- the deployed URL and behavior verified;
- review notes addressed and the tests covering them;
- any residual caveat.
