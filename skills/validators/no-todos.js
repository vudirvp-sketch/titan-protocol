/**
 * TITAN FUSE Custom Validator: no-todos
 * Rejects files containing TODO/FIXME markers
 *
 * Usage: Place in skills/validators/ directory
 * The protocol will automatically load and run this validator
 */

module.exports = {
  name: 'no-todos',
  version: '1.0.0',
  description: 'Rejects files containing TODO, FIXME, XXX, or HACK markers',

  // Patterns to detect
  patterns: [
    /\bTODO\b/i,
    /\bFIXME\b/i,
    /\bXXX\b/i,
    /\bHACK\b/i
  ],

  // Severity for violations
  severity: 'SEV-3', // Medium - maintainability risk

  /**
   * Validate a chunk of content
   * @param {string} content - The content to validate
   * @param {object} context - Additional context (chunk_id, file_path, etc.)
   * @returns {object} Validation result
   */
  validate(content, context = {}) {
    const violations = [];

    for (const pattern of this.patterns) {
      const matches = content.match(new RegExp(pattern, 'g'));
      if (matches) {
        // Find line numbers
        const lines = content.split('\n');
        lines.forEach((line, index) => {
          if (pattern.test(line)) {
            violations.push({
              line: index + 1,
              pattern: pattern.toString(),
              content: line.trim().substring(0, 100),
              severity: this.severity
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
        ? `Found ${violations.length} TODO/FIXME marker(s)`
        : 'No TODO/FIXME markers found'
    };
  },

  /**
   * Generate fix suggestion
   * @param {object} violation - The violation object
   * @returns {string} Suggested fix
   */
  suggestFix(violation) {
    return `Consider removing or resolving the marker at line ${violation.line}: "${violation.content}"`;
  }
};
