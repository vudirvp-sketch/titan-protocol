/**
 * TITAN FUSE Custom Validator: api-version
 * Enforces API version format in documentation
 *
 * Usage: Place in skills/validators/ directory
 *
 * INVAR-05: Sandbox configuration
 * @sandbox_type: subprocess
 * @timeout_ms: 5000
 * @allowed_commands: ["node", "npm"]
 * @max_memory_mb: 128
 */

module.exports = {
  name: 'api-version',
  version: '1.0.0',
  description: 'Enforces consistent API version format (vX.Y.Z)',

  // Valid version patterns
  validPatterns: [
    /v\d+\.\d+\.\d+/g,           // vX.Y.Z
    /version:\s*\d+\.\d+\.\d+/gi  // version: X.Y.Z
  ],

  // Invalid patterns to flag
  invalidPatterns: [
    /v\d+(?!\.\d)/g,              // vX without minor/patch
    /version\s*=\s*['"][^'"]+['"]/gi  // version = "..." (non-standard)
  ],

  severity: 'SEV-4', // Low - style issue

  /**
   * Validate a chunk of content
   */
  validate(content, context = {}) {
    const violations = [];

    // Check for invalid patterns
    for (const pattern of this.invalidPatterns) {
      const matches = content.match(pattern);
      if (matches) {
        const lines = content.split('\n');
        lines.forEach((line, index) => {
          if (pattern.test(line)) {
            violations.push({
              line: index + 1,
              type: 'invalid_format',
              content: line.trim().substring(0, 100),
              severity: this.severity,
              suggestion: 'Use format: vX.Y.Z (e.g., v1.2.3)'
            });
          }
        });
      }
    }

    return {
      valid: violations.length === 0,
      validator: this.name,
      violations,
      summary: violations.length > 0
        ? `Found ${violations.length} non-standard version format(s)`
        : 'All version formats are valid'
    };
  }
};
