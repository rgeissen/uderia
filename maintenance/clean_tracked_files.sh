#!/bin/bash
#
# This script removes files and directories from git tracking that should be ignored
# according to the project's .gitignore file. Run this script from the root of
# the repository.
#
# It's useful for cleaning up a repository after files have been accidentally
# committed.

set -e

# Add any other files or directories that should be ignored here.
IGNORED_PATHS=(
    ".chromadb_rag_cache"
    "src/.chromadb_rag_cache"
    "tda_auth.db"
    "tda_auth.db-journal"
    "logs"
    ".vscode"
)

echo "Checking for tracked files that should be ignored..."

for path in "${IGNORED_PATHS[@]}"; do
    # The `git ls-files --error-unmatch` command returns a non-zero exit code
    # if the path is not tracked. We redirect stdout and stderr to /dev/null
    # to suppress output.
    if git ls-files --error-unmatch "$path" >/dev/null 2>&1; then
        echo "Removing '$path' from git tracking..."
        git rm -r --cached "$path"
    else
        echo "'$path' is not tracked by git. Skipping."
    fi
done

echo ""
echo "Cleanup complete."
echo "Please review the changes with 'git status' and then commit them."
