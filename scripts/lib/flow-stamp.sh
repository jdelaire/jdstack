flow_paths() {
  printf '%s\n' "skills/$1" "docs/flows/$1.html" "docs/flows/$1-light.png" "docs/flows/$1-dark.png" scripts/render-flows.sh scripts/lib/flow-stamp.sh
}

flow_stamp() {
  local skill=$1 source=$2 line meta path
  local paths=()
  while IFS= read -r path; do paths+=("$path"); done < <(flow_paths "$skill")
  case $source in
    worktree)
      git ls-files -z --cached --others --exclude-standard -- "${paths[@]}" | while IFS= read -r -d '' path; do
        if [ -L "$path" ]; then
          printf '%s %s\n' "$path" "$(printf '%s' "$(readlink "$path")" | git hash-object --stdin)"
        elif [ -f "$path" ]; then
          printf '%s %s\n' "$path" "$(git hash-object "$path")"
        fi
      done
      ;;
    index)
      git ls-files -z -s -- "${paths[@]}" | while IFS= read -r -d '' line; do
        meta=${line%%$'\t'*}
        meta=${meta#* }
        printf '%s %s\n' "${line#*$'\t'}" "${meta%% *}"
      done
      ;;
    *)
      git ls-tree -r -z "$source" -- "${paths[@]}" | while IFS= read -r -d '' line; do
        meta=${line%%$'\t'*}
        printf '%s %s\n' "${line#*$'\t'}" "${meta##* }"
      done
      ;;
  esac | LC_ALL=C sort
}

flow_read() {
  case $2 in
    worktree) cat "docs/flows/$1.stamp" 2>/dev/null || true ;;
    index) git show ":docs/flows/$1.stamp" 2>/dev/null || true ;;
    *) git show "$2:docs/flows/$1.stamp" 2>/dev/null || true ;;
  esac
}

flow_skills() {
  case $1 in
    worktree) git ls-files --cached --others --exclude-standard -- docs/flows ;;
    index) git ls-files -- docs/flows ;;
    *) git ls-tree -r --name-only "$1" -- docs/flows ;;
  esac | sed -nE 's#^docs/flows/([^/]+)(\.html|\.stamp|-light\.png|-dark\.png)$#\1#p' | LC_ALL=C sort -u
}
