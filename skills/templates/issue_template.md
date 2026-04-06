# ISSUE Template

Use this template for classifying issues found during Phase 2.

```text
ISSUE_ID: [AUTO-GENERATED]
SEVERITY: [SEV-1|SEV-2|SEV-3|SEV-4]
LOCATION: file:line_start-line_end | chunk_id
CATEGORY: [Structural|Logical|Performance|Security|Style]
EVIDENCE: <exact code snippet>
CONFLICT_WITH: <other section/file if applicable>
ROOT_CAUSE: <why this exists>
IMPACT: <what breaks if unfixed>
FIX_STRATEGY: [Refactor|Rewrite|Delete|Document|Defer|KEEP]
ESTIMATED_TOKENS: <cost to fix>
KEEP_VETO: [TRUE|FALSE]
```

## Severity Definitions

| Level | Name | Criteria |
|-------|------|----------|
| SEV-1 | CRITICAL | Silent data loss, security vulnerability, undefined behavior |
| SEV-2 | HIGH | Architectural debt, API breakage risk, performance cliff |
| SEV-3 | MEDIUM | Logic errors, maintainability risk, non-obvious side effects |
| SEV-4 | LOW | Style, cosmetic issues, minor technical debt |

## Category Definitions

| Category | Description |
|----------|-------------|
| Structural | Issues with document/code structure |
| Logical | Logic errors, incorrect behavior |
| Performance | Inefficiencies, resource issues |
| Security | Vulnerabilities, exposure risks |
| Style | Formatting, naming, conventions |

## Fix Strategy Definitions

| Strategy | When to Use |
|----------|-------------|
| Refactor | Restructure without changing behavior |
| Rewrite | Replace with new implementation |
| Delete | Remove unnecessary code/content |
| Document | Add documentation/comments |
| Defer | Postpone to future iteration |
| KEEP | Protected by KEEP marker, cannot modify |

## Example

```text
ISSUE_ID: ISSUE-0047
SEVERITY: SEV-2
LOCATION: example.md:1234-1256 | C5
CATEGORY: Structural
EVIDENCE:
  ```
  ## Section A
  Content here...

  ## Section A (duplicate)
  More content...
  ```
CONFLICT_WITH: Section A at line 1200
ROOT_CAUSE: Copy-paste error during document merge
IMPACT: Confuses readers, search returns multiple results
FIX_STRATEGY: Delete
ESTIMATED_TOKENS: 150
KEEP_VETO: FALSE
```
