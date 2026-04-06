#!/bin/bash
# =============================================================================
# TITAN FUSE Protocol Assembly Script
# Version: 1.0.0
# Purpose: Deterministically assembles PROTOCOL.md from base and extension files
# =============================================================================

set -e

# Configuration
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(dirname "$SCRIPT_DIR")"
BASE_FILE="${ROOT_DIR}/PROTOCOL.base.md"
EXT_FILE="${ROOT_DIR}/PROTOCOL.ext.md"
OUTPUT_FILE="${ROOT_DIR}/PROTOCOL.md"
VERSION_FILE="${ROOT_DIR}/VERSION"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Separator marker for protocol boundary
SEPARATOR="\n---\n<!-- PROTOCOL EXTENSION BOUNDARY -->\n---\n\n"

# Logging functions
log_info() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

log_warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# Validation functions
validate_file() {
    local file="$1"
    local description="$2"

    if [ ! -f "$file" ]; then
        log_error "$description not found: $file"
        return 1
    fi

    if [ ! -r "$file" ]; then
        log_error "$description not readable: $file"
        return 1
    fi

    # Check for empty file
    if [ ! -s "$file" ]; then
        log_error "$description is empty: $file"
        return 1
    fi

    log_info "$description validated: $file"
    return 0
}

# Check for duplicate sections between base and extension
check_duplicate_sections() {
    log_info "Checking for duplicate sections..."

    local base_sections=$(grep -E "^#{1,3} " "$BASE_FILE" | sed 's/^[#]* //' | sort)
    local ext_sections=$(grep -E "^#{1,3} " "$EXT_FILE" | sed 's/^[#]* //' | sort)

    local duplicates=$(comm -12 <(echo "$base_sections") <(echo "$ext_sections"))

    if [ -n "$duplicates" ]; then
        log_warn "Duplicate sections detected (extension will override base):"
        echo "$duplicates" | while read -r section; do
            echo "  - $section"
        done
    else
        log_info "No duplicate sections found"
    fi
}

# Validate YAML frontmatter in both files
validate_frontmatter() {
    log_info "Validating YAML frontmatter..."

    for file in "$BASE_FILE" "$EXT_FILE"; do
        if head -1 "$file" | grep -q "^---$"; then
            # Check if frontmatter is properly closed
            if ! sed -n '1,/^---$/p' "$file" | tail -1 | grep -q "^---$"; then
                log_error "Malformed frontmatter in: $file"
                return 1
            fi
            log_info "Valid frontmatter in: $file"
        else
            log_warn "No frontmatter found in: $file"
        fi
    done

    return 0
}

# Main assembly function
assemble_protocol() {
    log_info "Starting protocol assembly..."

    # Read version
    if [ -f "$VERSION_FILE" ]; then
        VERSION=$(cat "$VERSION_FILE" | tr -d '[:space:]')
        log_info "Protocol version: $VERSION"
    else
        VERSION="unknown"
        log_warn "VERSION file not found, using 'unknown'"
    fi

    # Create output file with header
    {
        echo "# TITAN FUSE PROTOCOL - ASSEMBLED"
        echo ""
        echo "<!-- Generated: $(date -u +%Y-%m-%dT%H:%M:%SZ) -->"
        echo "<!-- Version: $VERSION -->"
        echo "<!-- Components: PROTOCOL.ext.md + PROTOCOL.base.md -->"
        echo ""
    } > "$OUTPUT_FILE"

    # Append extension (TIER -1 comes first)
    log_info "Appending TIER -1 extension..."
    cat "$EXT_FILE" >> "$OUTPUT_FILE"

    # Add separator
    printf "$SEPARATOR" >> "$OUTPUT_FILE"

    # Append base protocol
    log_info "Appending base protocol..."
    cat "$BASE_FILE" >> "$OUTPUT_FILE"

    # Add assembly footer
    {
        echo ""
        echo "---"
        echo "<!-- END OF ASSEMBLED PROTOCOL -->"
        echo "<!-- Assembly timestamp: $(date -u +%Y-%m-%dT%H:%M:%SZ) -->"
    } >> "$OUTPUT_FILE"

    # Auto-fix unbalanced code blocks: if odd number of fences, append closing ```
    local fence_count=$(grep -c '^\s*```' "$OUTPUT_FILE" || true)
    if [ $((fence_count % 2)) -ne 0 ]; then
        log_warn "Odd fence count ($fence_count) detected after assembly — appending closing \`\`\`"
        echo '```' >> "$OUTPUT_FILE"
    fi

    log_info "Protocol assembled successfully: $OUTPUT_FILE"

    # Report file stats
    local lines=$(wc -l < "$OUTPUT_FILE")
    local chars=$(wc -c < "$OUTPUT_FILE")
    log_info "Output: $lines lines, $chars bytes"
}

# Verify assembled protocol
verify_assembly() {
    log_info "Verifying assembled protocol..."

    # Check for required sections
    local required_sections=(
        "TIER 0"
        "TIER 1"
        "TIER 2"
        "TIER 3"
        "TIER 4"
        "TIER 5"
        "TIER 6"
        "EXECUTION DIRECTIVE"
    )

    for section in "${required_sections[@]}"; do
        if grep -q "$section" "$OUTPUT_FILE"; then
            log_info "Found section: $section"
        else
            log_error "Missing required section: $section"
            return 1
        fi
    done

    # Check for TIER -1 (extension)
    if grep -q "TIER -1" "$OUTPUT_FILE"; then
        log_info "Found TIER -1 extension"
    else
        log_warn "TIER -1 extension not found (optional)"
    fi

    # Verify no broken markdown syntax
    # Count ALL lines starting with ``` (with or without language tag) — same pattern as CI
    local block_count=$(grep -c '^\s*```' "$OUTPUT_FILE" || true)

    if [ $((block_count % 2)) -eq 0 ]; then
        log_info "Code blocks balanced ($block_count fences = $((block_count / 2)) pairs)"
    else
        log_error "Unbalanced code blocks! Total fences: $block_count (must be even)"
        log_error "Offending lines:"
        grep -n '^\s*```' "$OUTPUT_FILE" | tail -20
        return 1
    fi

    log_info "Verification complete"
    return 0
}

# Main execution
main() {
    echo "============================================"
    echo "TITAN FUSE Protocol Assembly Tool v1.0.0"
    echo "============================================"
    echo ""

    # Validate input files
    validate_file "$BASE_FILE" "Base protocol file" || exit 1
    validate_file "$EXT_FILE" "Extension protocol file" || exit 1

    # Run pre-assembly checks
    validate_frontmatter || exit 1
    check_duplicate_sections

    # Assemble protocol
    assemble_protocol || exit 1

    # Verify assembly
    verify_assembly || exit 1

    echo ""
    echo "============================================"
    log_info "Assembly completed successfully!"
    echo "============================================"
}

# Run main function
main "$@"
