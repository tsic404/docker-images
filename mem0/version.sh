#!/bin/bash

LAST_VERSION=v1.0.11
OWNER=mem0ai
REPO=mem0

if date -d "1970-01-01" +%s >/dev/null 2>&1; then
    date_cmd="date -d"
    now_cmd="date +%s"
    cutoff_cmd="date -d '3 days ago' +%s"
else
    date_cmd="date -j -f '%Y-%m-%dT%H:%M:%SZ'"
    now_cmd="date +%s"
    cutoff_cmd="date -v -3d +%s"
fi

cutoff=$(eval $cutoff_cmd)

query='
{
  repository(owner: "'"${OWNER}"'", name: "'"${REPO}"'") {
    refs(refPrefix: "refs/tags/", first: 20, orderBy: {field: TAG_COMMIT_DATE, direction: DESC}) {
      nodes {
        name
        target {
          ... on Commit {
            committedDate
          }
          ... on Tag {
            target {
              ... on Commit {
                committedDate
              }
            }
          }
        }
      }
    }
  }
}
'

VERSION=$(
curl -s -H "Authorization: Bearer $GITHUB_TOKEN" \
     -H "Content-Type: application/json" \
     https://api.github.com/graphql \
     -d "$(jq -n --arg q "$query" '{query: $q}')" \
| jq -r '
.data.repository.refs.nodes[]
| .name as $name
| (
    .target.committedDate
    // .target.target.committedDate
  ) as $date
| select($date != null)
| "\($date) \($name)"
' \
| while read date tag; do
    if [[ "$date_cmd" == "date -d" ]]; then
        ts=$(date -d "$date" +%s)
    else
        ts=$(date -j -f "%Y-%m-%dT%H:%M:%SZ" "$date" +%s)
    fi

    if [ "$ts" -le "$cutoff" ]; then
        echo "$tag"
        break
    fi
done
)
echo "last_version=${LAST_VERSION}"
echo "current_version=${VERSION}"
