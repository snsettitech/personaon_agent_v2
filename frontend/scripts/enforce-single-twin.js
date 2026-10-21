#!/usr/bin/env node
/* eslint-disable @typescript-eslint/no-require-imports */
/**
 * Enforce Single Twin Rule - Final Implementation
 * 
 * MODES:
 * --mode strict: No user-facing "twin" anywhere
 * --mode single-twin: Allow "twin" singular, block "twins" plural + multi-twin UI
 * 
 * Usage:
 *   node enforce-single-twin.js --mode strict
 *   node enforce-single-twin.js --mode single-twin
 *   TWIN_ENFORCEMENT_MODE=single-twin node enforce-single-twin.js
 * 
 * Default: single-twin
 */

const fs = require('fs');
const path = require('path');

// ============================================================================
// Mode Detection
// ============================================================================

const args = process.argv.slice(2);
let MODE = 'single-twin'; // Default

// Check CLI args
const modeIndex = args.indexOf('--mode');
if (modeIndex !== -1 && args[modeIndex + 1]) {
  MODE = args[modeIndex + 1];
}

// Check ENV var (CLI takes precedence)
if (process.env.TWIN_ENFORCEMENT_MODE) {
  MODE = process.env.TWIN_ENFORCEMENT_MODE;
}

const isStrictMode = MODE === 'strict';
const isSingleTwinMode = MODE === 'single-twin';

if (!isStrictMode && !isSingleTwinMode) {
  console.error(`❌ Invalid mode: ${MODE}`);
  console.error('Valid modes: strict, single-twin');
  process.exit(1);
}

// ============================================================================
// Configuration
// ============================================================================

const TARGET_DIRS = [
  'frontend/app',
  'frontend/components',
  'frontend/lib'
];

const FILE_EXTENSIONS = ['.tsx', '.ts', '.jsx', '.js'];

// Internal code patterns - ALWAYS allowed in both modes
const INTERNAL_PATTERNS = [
  /twin_id/,                 // twin_id parameter
  /twinId/,                  // camelCase twinId  
  /TwinContext/,             // Context name
  /TwinProvider/,            // Provider name
  /useTwin/,                 // Hook name
  /TwinSelector/,            // Component name (we check separately)
  /\.twin\b/,               // object property .twin
  /twin\?\./,               // optional chaining twin?.
  /twin\./,                 // object access twin.
  /\/twins\//,              // API route /twins/
  /\/twin\//,               // API route /twin/
  /twins\./,                // object property twins.
  /twins\?\./,              // optional chaining twins?.
  /twins\[/,                // array access twins[
  /twins\.length/,          // array length check
  /twins\.map/,             // array methods
  /twins\.filter/,
  /twins\.find/,
  /twins\.forEach/,
  /twins\s*===/,            // comparisons
  /twins\s*!==/,
  /['"]twins['"]/,          // string literal "twins"
  /['"]twin['"]/,           // string literal "twin"
  /\/\/.*twin/i,            // comments
  /\/\*.*twin.*\*\//is,     // block comments
  /\btwin\?\?\b/,           // nullish coalescing
  /\btwin\s*\?\s*\./,       // optional chaining start
];

// Multi-twin UI phrases - DISALLOWED in single-twin mode
const MULTI_TWIN_PHRASES = [
  { pattern: /\bcreate another twin\b/i, reason: "Multi-twin: 'create another twin'" },
  { pattern: /\bnew twin\b/i, reason: "Multi-twin: 'new twin'" },
  { pattern: /\badd twin\b/i, reason: "Multi-twin: 'add twin'" },
  { pattern: /\bswitch twin\b/i, reason: "Multi-twin: 'switch twin'" },
  { pattern: /\bselect twin\b/i, reason: "Multi-twin: 'select twin'" },
  { pattern: /\bmanage twins\b/i, reason: "Multi-twin: 'manage twins'" },
  { pattern: /\bmy twins\b/i, reason: "Multi-twin: 'my twins'" },
  { pattern: /\ball twins\b/i, reason: "Multi-twin: 'all twins'" },
  { pattern: /\btwins\b/i, reason: "Plural: 'twins'" },
];

// Strict mode - any "twin" word
const STRICT_PATTERN = /\btwin\b/i;

// User-facing content indicators
const USER_FACING_INDICATORS = [
  /label\s*=\s*["'][^"']*twin/i,         // label prop
  /title\s*=\s*["'][^"']*twin/i,         // title prop
  /description\s*=\s*["'][^"']*twin/i,   // description prop
  /placeholder\s*=\s*["'][^"']*twin/i,   // placeholder
  /alt\s*=\s*["'][^"']*twin/i,           // alt text
  /toast\([^)]*twin/i,                   // toast messages
  /showToast\([^)]*twin/i,               // showToast calls
  /alert\([^)]*twin/i,                   // alert messages
];

// ============================================================================
// Utility Functions
// ============================================================================

function shouldCheckFile(filePath) {
  const ext = path.extname(filePath);
  return FILE_EXTENSIONS.includes(ext) && !filePath.includes('node_modules');
}

function isInternalCode(line) {
  return INTERNAL_PATTERNS.some(pattern => pattern.test(line));
}

function hasUserFacingIndicator(line) {
  return USER_FACING_INDICATORS.some(pattern => pattern.test(line));
}

function isLikelyUserFacing(content, lineIndex) {
  const lines = content.split('\n');
  const line = lines[lineIndex];
  
  // Check for JSX text content patterns
  const prevLine = lineIndex > 0 ? lines[lineIndex - 1] : '';
  const nextLine = lineIndex < lines.length - 1 ? lines[lineIndex + 1] : '';
  
  // If previous line has an opening tag and this line has text
  if (/<[a-zA-Z][^>]*>$/.test(prevLine) && /^\s+\w/.test(line)) {
    return true;
  }
  
  // If this line is mostly text (indented content)
  if (/^\s{2,}[A-Z]/.test(line) && !line.includes('//') && !line.includes('/*')) {
    return true;
  }
  
  // Check for user-facing indicators on this line
  if (hasUserFacingIndicator(line)) {
    return true;
  }
  
  // Check for JSX expression with string containing twin
  if (/\{\s*["'][^"']*twin[^"']*["']\s*\}/i.test(line)) {
    return true;
  }
  
  return false;
}

function findStrictViolations(content, filePath) {
  const violations = [];
  const lines = content.split('\n');
  
  lines.forEach((line, index) => {
    // Skip internal code references
    if (isInternalCode(line)) {
      return;
    }
    
    // Must contain "twin"
    if (!STRICT_PATTERN.test(line)) {
      return;
    }
    
    // Check for user-facing indicators
    if (hasUserFacingIndicator(line)) {
      violations.push({
        line: index + 1,
        content: line.trim(),
        reason: "Strict: 'twin' in UI prop"
      });
      return;
    }
    
    // Check if likely user-facing content
    if (isLikelyUserFacing(content, index)) {
      violations.push({
        line: index + 1,
        content: line.trim(),
        reason: "Strict: 'twin' in content"
      });
      return;
    }
    
    // If line has "twin" and is mostly text (not code)
    const codeIndicators = /[{}();=]|function|const|let|var|import|export/;
    if (!codeIndicators.test(line) && /\btwin\b/i.test(line)) {
      violations.push({
        line: index + 1,
        content: line.trim(),
        reason: "Strict: 'twin' in text"
      });
    }
  });
  
  return violations;
}

function findSingleTwinViolations(content, filePath) {
  const violations = [];
  const lines = content.split('\n');
  
  lines.forEach((line, index) => {
    // Skip internal code references
    if (isInternalCode(line)) {
      return;
    }
    
    // Check for multi-twin phrases
    for (const { pattern, reason } of MULTI_TWIN_PHRASES) {
      if (pattern.test(line)) {
        violations.push({
          line: index + 1,
          content: line.trim(),
          reason: reason
        });
        return; // Only report first match per line
      }
    }
  });
  
  return violations;
}

function findTwinSelectorUsage(content, filePath) {
  const violations = [];
  const lines = content.split('\n');
  
  lines.forEach((line, index) => {
    // Check for TwinSelector import
    if (/import.*TwinSelector/.test(line)) {
      violations.push({
        line: index + 1,
        content: line.trim(),
        reason: "TwinSelector import"
      });
    }
    
    // Check for TwinSelector JSX usage
    if (/<TwinSelector/.test(line)) {
      violations.push({
        line: index + 1,
        content: line.trim(),
        reason: "TwinSelector component"
      });
    }
  });
  
  return violations;
}

function checkNavigationConfig(filePath) {
  const violations = [];
  
  if (!fs.existsSync(filePath)) {
    return violations;
  }
  
  const content = fs.readFileSync(filePath, 'utf-8');
  const lines = content.split('\n');
  
  lines.forEach((line, index) => {
    const trimmed = line.trim();
    
    // Skip comments
    if (trimmed.startsWith('//') || trimmed.startsWith('*')) {
      return;
    }
    
    // Extract nav labels
    const navLabelMatch = line.match(/name:\s*['"]([^'"]*)['"]/i);
    if (!navLabelMatch) return;
    
    const label = navLabelMatch[1];
    
    if (isStrictMode) {
      // Strict: any "twin" in nav labels
      if (/\btwin\b/i.test(label)) {
        violations.push({
          line: index + 1,
          content: line.trim(),
          reason: "Strict: 'twin' in nav"
        });
      }
    } else {
      // Single-twin: check for plural/multi-twin
      if (/\bmy twins\b/i.test(label)) {
        violations.push({ line: index + 1, content: line.trim(), reason: "Multi-twin: 'My Twins' nav" });
      } else if (/\bmanage twins\b/i.test(label)) {
        violations.push({ line: index + 1, content: line.trim(), reason: "Multi-twin: 'Manage Twins' nav" });
      } else if (/\bswitch twin\b/i.test(label)) {
        violations.push({ line: index + 1, content: line.trim(), reason: "Multi-twin: 'Switch Twin' nav" });
      } else if (/\btwins\b/i.test(label)) {
        violations.push({ line: index + 1, content: line.trim(), reason: "Plural: 'twins' in nav" });
      }
    }
  });
  
  return violations;
}

function walkDir(dir, callback) {
  if (!fs.existsSync(dir)) {
    return;
  }
  
  const files = fs.readdirSync(dir);
  files.forEach(file => {
    const filePath = path.join(dir, file);
    const stat = fs.statSync(filePath);
    
    if (stat.isDirectory() && !file.includes('node_modules')) {
      walkDir(filePath, callback);
    } else if (stat.isFile()) {
      callback(filePath);
    }
  });
}

// ============================================================================
// Main
// ============================================================================

console.log(`🔍 Mode: ${MODE.toUpperCase()}`);
console.log('');

const allViolations = [];
let totalViolations = 0;

// Check target directories
TARGET_DIRS.forEach(dir => {
  if (!fs.existsSync(dir)) {
    return;
  }
  
  walkDir(dir, filePath => {
    if (!shouldCheckFile(filePath)) {
      return;
    }
    
    try {
      const content = fs.readFileSync(filePath, 'utf-8');
      
      // Find violations based on mode
      const modeViolations = isStrictMode 
        ? findStrictViolations(content, filePath)
        : findSingleTwinViolations(content, filePath);
      
      // Always check for TwinSelector (both modes)
      const selectorViolations = findTwinSelectorUsage(content, filePath);
      
      const allFileViolations = [...modeViolations, ...selectorViolations];
      
      if (allFileViolations.length > 0) {
        allViolations.push({
          file: filePath,
          violations: allFileViolations
        });
        totalViolations += allFileViolations.length;
      }
    } catch (err) {
      // Skip files that can't be read
    }
  });
});

// Check navigation config
const navConfigPath = 'frontend/lib/navigation/config.ts';
const navViolations = checkNavigationConfig(navConfigPath);

if (navViolations.length > 0) {
  allViolations.push({
    file: navConfigPath,
    violations: navViolations
  });
  totalViolations += navViolations.length;
}

// ============================================================================
// Report
// ============================================================================

console.log(`Total violations: ${totalViolations}`);
console.log('');

if (totalViolations > 0) {
  allViolations.forEach(({ file, violations }) => {
    console.log(`${file}:`);
    violations.forEach(v => {
      console.log(`  Line ${v.line}: ${v.reason}`);
      console.log(`    ${v.content.substring(0, 100)}${v.content.length > 100 ? '...' : ''}`);
    });
    console.log('');
  });
  
  process.exit(1);
} else {
  console.log('✅ All checks passed');
  process.exit(0);
}
