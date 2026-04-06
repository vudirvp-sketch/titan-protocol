/**
 * TITAN FUSE Custom Validator: security
 * Checks for secrets, credentials, and sensitive data
 *
 * Usage: Place in skills/validators/ directory
 * IMPORTANT: This validator is for detection only.
 * Never auto-fix security issues - flag for human review.
 */

module.exports = {
  name: 'security',
  version: '1.0.0',
  description: 'Detects potential secrets, credentials, and sensitive data',

  // Critical patterns (SEV-1)
  criticalPatterns: [
    // AWS Keys
    /AKIA[0-9A-Z]{16}/g,
    /aws_secret_access_key\s*=\s*['"][^'"]+['"]/gi,

    // Private Keys
    /-----BEGIN (?:RSA |DSA |EC |OPENSSH )?PRIVATE KEY-----/g,

    // API Keys (generic)
    /api[_-]?key\s*=\s*['"][^'"]{20,}['"]/gi,
    /secret[_-]?key\s*=\s*['"][^'"]{20,}['"]/gi,

    // Database URLs with credentials
    /(?:mysql|postgres|mongodb|redis):\/\/[^:]+:[^@]+@/gi
  ],

  // Warning patterns (SEV-2)
  warningPatterns: [
    // Generic passwords
    /password\s*=\s*['"][^'"]+['"]/gi,

    // Tokens
    /token\s*=\s*['"][^'"]{16,}['"]/gi,

    // Base64 encoded (potential secrets)
    /['"][A-Za-z0-9+/]{40,}={0,2}['"]/g,

    // Email addresses in config
    /[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}/g
  ],

  // Info patterns (SEV-3)
  infoPatterns: [
    // IP addresses
    /\b(?:\d{1,3}\.){3}\d{1,3}\b/g,

    // URLs with potential sensitive paths
    /https?:\/\/[^\s'"]+(?:admin|config|secret|private)/gi
  ],

  severity: {
    critical: 'SEV-1',
    warning: 'SEV-2',
    info: 'SEV-3'
  },

  /**
   * Validate a chunk of content
   * IMPORTANT: Security violations should NEVER be auto-fixed
   */
  validate(content, context = {}) {
    const violations = [];

    // Check critical patterns
    for (const pattern of this.criticalPatterns) {
      pattern.lastIndex = 0; // FIX: Reset lastIndex for global regex
      const matches = content.match(pattern);
      if (matches) {
        const lines = content.split('\n');
        lines.forEach((line, index) => {
          pattern.lastIndex = 0; // FIX: Reset before each test() call
          if (pattern.test(line)) {
            violations.push({
              line: index + 1,
              type: 'critical_secret',
              pattern: pattern.toString().substring(0, 50),
              severity: this.severity.critical,
              autoFixable: false, // NEVER auto-fix security issues
              requiresHumanReview: true
            });
          }
        });
      }
    }

    // Check warning patterns
    for (const pattern of this.warningPatterns) {
      pattern.lastIndex = 0; // FIX: Reset lastIndex for global regex
      const matches = content.match(pattern);
      if (matches) {
        const lines = content.split('\n');
        lines.forEach((line, index) => {
          pattern.lastIndex = 0; // FIX: Reset before each test() call
          if (pattern.test(line)) {
            violations.push({
              line: index + 1,
              type: 'potential_secret',
              pattern: pattern.toString().substring(0, 50),
              severity: this.severity.warning,
              autoFixable: false,
              requiresHumanReview: true
            });
          }
        });
      }
    }

    // Check info patterns
    for (const pattern of this.infoPatterns) {
      pattern.lastIndex = 0; // FIX: Reset lastIndex for global regex
      const matches = content.match(pattern);
      if (matches) {
        const lines = content.split('\n');
        lines.forEach((line, index) => {
          pattern.lastIndex = 0; // FIX: Reset before each test() call
          if (pattern.test(line)) {
            violations.push({
              line: index + 1,
              type: 'sensitive_data',
              pattern: pattern.toString().substring(0, 50),
              severity: this.severity.info,
              autoFixable: false
            });
          }
        });
      }
    }

    return {
      valid: violations.filter(v => v.severity === 'SEV-1' || v.severity === 'SEV-2').length === 0,
      validator: this.name,
      violations,
      summary: violations.length > 0
        ? `Found ${violations.length} potential security issue(s)`
        : 'No security issues detected',
      recommendation: violations.some(v => v.requiresHumanReview)
        ? 'SECURITY: Manual review required before proceeding'
        : null
    };
  },

  /**
   * Security issues should NEVER be auto-fixed
   */
  suggestFix(violation) {
    return `[SECURITY] Line ${violation.line}: Review and remove sensitive data manually. Do not auto-fix.`;
  }
};
