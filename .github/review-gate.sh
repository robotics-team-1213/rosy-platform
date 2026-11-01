#!/usr/bin/env bash
# Review gate that asks for a teammate only where work meets.
# Others' files = files that other people (not the PR author, not IGNORE agents) changed on main in the
# last WINDOW_DAYS days or are changing in their open PRs. A PR that touches none of them passes;
# one that touches any needs a non-author's latest review to approve.
# Env: GH_TOKEN, REPO (owner/name), PR (number), AUTHOR (PR author login),
#      WINDOW_DAYS (default 14), IGNORE (space-separated logins that are agents, not people).
# shortcut: evaluated on this PR's events only; a later overlapping PR by someone else gates that PR, not this one.
set -euo pipefail
since=$(date -u -d "${WINDOW_DAYS:-14} days ago" +%Y-%m-%dT%H:%M:%SZ)
skip=" $AUTHOR ${IGNORE:-} "
others_files=$(
  gh api "repos/$REPO/commits?sha=main&since=$since&per_page=100" --paginate \
    --jq '.[] | select(.author != null and .author.type == "User") | "\(.author.login) \(.sha)"' |
  while read -r login sha; do
    [[ "$skip" == *" $login "* ]] && continue
    git show --format= --name-only "$sha" | sed "s/^/$login /"   # needs a full-history checkout
  done
  gh api "repos/$REPO/pulls?state=open&per_page=100" --paginate \
    --jq '.[] | select(.user.type == "User") | "\(.user.login) \(.number)"' |
  while read -r login number; do
    [[ "$skip" == *" $login "* || "$number" == "$PR" ]] && continue
    gh api "repos/$REPO/pulls/$number/files?per_page=100" --paginate --jq ".[].filename | \"$login \" + ."
  done
)
pr_files=$(gh api "repos/$REPO/pulls/$PR/files?per_page=100" --paginate --jq '.[].filename' | sort -u)
overlap=$(awk 'NR == FNR { mine[$0] = 1; next } ($2 in mine) { print $2 " (" $1 ")" }' \
  <(echo "$pr_files") <(echo "$others_files") | sort -u)
if [ -z "$overlap" ]; then
  echo "no overlap with others' recent work: review not required"
  exit 0
fi
echo "files shared with others' recent work:"; echo "$overlap"
{ echo "### review-gate: files shared with others' recent work"; sed 's/^/- /' <<<"$overlap"; } >> "${GITHUB_STEP_SUMMARY:-/dev/null}"
approvers=$(AUTHOR="$AUTHOR" gh api "repos/$REPO/pulls/$PR/reviews?per_page=100" --jq '
  map(select(.state == "APPROVED" or .state == "CHANGES_REQUESTED" or .state == "DISMISSED"))
  | group_by(.user.login) | map(last) | .[]
  | select(.state == "APPROVED" and .user.login != env.AUTHOR) | .user.login')
if [ -z "$approvers" ]; then
  # Ask the people whose work it meets; a failed request (no write access, read-only token) only loses the hint.
  for login in $(sed -E 's/.*\((.*)\)$/\1/' <<<"$overlap" | sort -u); do
    gh api -X POST "repos/$REPO/pulls/$PR/requested_reviewers" -f "reviewers[]=$login" >/dev/null 2>&1 &&
      echo "requested review from $login" || echo "could not request review from $login"
  done
  echo "::error::this PR changes files others worked on recently, so someone other than $AUTHOR must approve"
  exit 1
fi
echo "approved by: $approvers"
