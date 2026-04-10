#!/bin/bash
# =============================================================================
# TITAN Protocol Repository Cleanup Script
# Generated: 2026-04-11
# Purpose: Remove duplicate/obsolete files after Plan A, B, C completion
# =============================================================================

set -e

echo "=========================================="
echo "TITAN Protocol Repository Cleanup"
echo "=========================================="

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Counters
REMOVED=0
SKIPPED=0

# Function to safely remove a file/directory
safe_remove() {
    local path="$1"
    local reason="$2"

    if [ -e "$path" ]; then
        echo -e "${YELLOW}Removing:${NC} $path"
        echo "  Reason: $reason"
        rm -rf "$path"
        ((REMOVED++))
    else
        echo -e "${GREEN}Skipped:${NC} $path (not found)"
        ((SKIPPED++))
    fi
}

# Function to check if path is in git
is_tracked() {
    git ls-files --error-unmatch "$1" >/dev/null 2>&1
}

echo ""
echo "Phase 1: Remove duplicate utils/ directory"
echo "-------------------------------------------"
# utils/ at root is a duplicate of src/utils/
# src/utils/ is the canonical location
if [ -d "utils" ] && [ -d "src/utils" ]; then
    # Verify they are actually duplicates (optional safety check)
    echo "Checking if utils/ and src/utils/ are duplicates..."
    if diff -rq utils src/utils >/dev/null 2>&1; then
        safe_remove "utils" "Duplicate of src/utils/ (verified identical)"
    else
        echo -e "${YELLOW}WARNING: utils/ and src/utils/ differ - manual review required${NC}"
        echo "Contents of utils/:"
        ls -la utils/ 2>/dev/null || echo "  (empty or not accessible)"
    fi
elif [ -d "utils" ] && [ ! -d "src/utils" ]; then
    echo -e "${YELLOW}WARNING: utils/ exists but src/utils/ doesn't${NC}"
    echo "Keeping utils/ - it may be the only copy"
fi

echo ""
echo "Phase 2: Clean up temporary/backup files"
echo "-------------------------------------------"
# Remove Python cache
find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
find . -type f -name "*.pyc" -delete 2>/dev/null || true
find . -type f -name "*.pyo" -delete 2>/dev/null || true

# Remove backup files
find . -type f -name "*.bak" -delete 2>/dev/null || true
find . -type f -name "*.backup" -delete 2>/dev/null || true
find . -type f -name "*~" -delete 2>/dev/null || true

# Remove .DS_Store files (macOS)
find . -type f -name ".DS_Store" -delete 2>/dev/null || true

echo "Cleaned: Python cache, backup files, .DS_Store"

echo ""
echo "Phase 3: Clean up old checkpoint files (if any)"
echo "-------------------------------------------"
# Keep only the official checkpoint files
# Remove any temporary checkpoint files
find . -type f -name "checkpoint_*.tmp.yaml" -delete 2>/dev/null || true
find . -type f -name "checkpoint_*.bak.yaml" -delete 2>/dev/null || true

echo "Cleaned: temporary checkpoint files"

echo ""
echo "Phase 4: Verify remaining structure"
echo "-------------------------------------------"
echo "Checking critical files..."

CRITICAL_FILES=(
    "VERSION"
    "PROTOCOL.md"
    "config.yaml"
    "config/prompt_registry.yaml"
    "config/tool_activation.yaml"
    "src/orchestrator/chain_composer.py"
    "src/orchestrator/universal_router.py"
    "src/security/execution_gate.py"
    "src/context/context_graph.py"
    "src/pipeline/content_pipeline.py"
    "src/schema/canonical_patterns.yaml"
    "src/gap_events/serializer.py"
    ".ai/nav_map.json"
    ".ai/shortcuts.yaml"
    ".ai/path_corrections.yaml"
    "checkpoint_PHASE_A.yaml"
    "checkpoint_PHASE_B.yaml"
    "checkpoint_PHASE_C.yaml"
)

MISSING=0
for file in "${CRITICAL_FILES[@]}"; do
    if [ -f "$file" ]; then
        echo -e "  ${GREEN}✓${NC} $file"
    else
        echo -e "  ${RED}✗${NC} $file (MISSING)"
        ((MISSING++))
    fi
done

echo ""
echo "=========================================="
echo "Cleanup Summary"
echo "=========================================="
echo -e "Files/directories removed: ${RED}$REMOVED${NC}"
echo -e "Items skipped: ${YELLOW}$SKIPPED${NC}"
echo -e "Critical files missing: ${RED}$MISSING${NC}"
echo ""

if [ $MISSING -gt 0 ]; then
    echo -e "${RED}WARNING: Some critical files are missing!${NC}"
    echo "Please verify the repository state before proceeding."
    exit 1
else
    echo -e "${GREEN}All critical files present.${NC}"
    echo "Repository cleanup completed successfully."
fi

echo ""
echo "Next steps:"
echo "  1. Run: git status"
echo "  2. Run: git add -A"
echo "  3. Run: git commit -m 'chore: cleanup after Plan A, B, C completion'"
echo "  4. Run: git push origin main"
