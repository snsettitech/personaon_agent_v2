#!/usr/bin/env node
/**
 * Regression-prevention: enforce that the onboarding/auth PostHog events
 * dropped by PR #37 (and restored 2026-07) stay wired up in the frontend
 * source.
 *
 * If anyone deletes or renames a call site here in the future, this check
 * fails loudly in CI rather than silently breaking the
 * signup_started -> published -> first_chat funnel like PR #37 did.
 *
 * Backend events (onboarding_extraction_complete) are covered by
 * backend/tests/test_training_jobs_enrichment.py, not this script.
 *
 * Known limitation: this only checks that the pattern is PRESENT somewhere
 * in the file — a commented-out or dead call site still passes. Catching an
 * accidental deletion (this script's actual job) is the common case; catching
 * a deliberate no-op edit is a code-review problem, not a CI-guard problem.
 * An AST-based check would close that gap but is disproportionate here.
 *
 * Usage:
 *   node scripts/enforce-onboarding-analytics.mjs
 *
 * Exits 0 on success, 1 on any missing call site.
 */

import { readFileSync } from 'node:fs';
import { resolve, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';

const __filename = fileURLToPath(import.meta.url);
const __dirname = dirname(__filename);
const FRONTEND_ROOT = resolve(__dirname, '..');

/**
 * Each rule asserts: in the given file (relative to frontend/), look for the
 * pattern. If any rule fails, the build fails. Patterns are JS regexes so
 * they tolerate whitespace/quote differences but still match the call site.
 */
const RULES = [
    {
        event: 'auth_signup_started',
        file: 'app/auth/login/page.tsx',
        // Single-page flow handles signup AND login - both *_started events fire on entry.
        pattern: /analytics\.authSignupStarted\s*\(/,
    },
    {
        event: 'auth_signup_completed',
        file: 'app/auth/login/page.tsx',
        // Fired only when sync-user reports a brand-new user (syncStatus === 'created').
        pattern: /analytics\.authSignupCompleted\s*\(/,
    },
    {
        event: 'onboarding_started',
        file: 'app/onboarding/page.tsx',
        pattern: /analytics\.onboardingStarted\s*\(/,
    },
    {
        event: 'onboarding_step_viewed',
        file: 'app/onboarding/page.tsx',
        pattern: /analytics\.onboardingStepViewed\s*\(/,
    },
    {
        event: 'onboarding_published',
        file: 'app/onboarding/page.tsx',
        pattern: /analytics\.onboardingPublished\s*\(/,
    },
    // onboarding_extraction_complete - fires from the backend
    // (backend/modules/training_jobs.py). Covered by pytest, not this script.
];

let failures = 0;

for (const rule of RULES) {
    const fullPath = resolve(FRONTEND_ROOT, rule.file);
    let source;
    try {
        source = readFileSync(fullPath, 'utf8');
    } catch (err) {
        console.error(`FAIL [${rule.event}]: cannot read ${rule.file} (${err.message})`);
        failures += 1;
        continue;
    }
    if (!rule.pattern.test(source)) {
        console.error(
            `FAIL [${rule.event}]: pattern ${rule.pattern} not found in ${rule.file}.\n` +
                '       This event powers the signup/onboarding funnel - restore it before merging.\n' +
                '       See PostHog project 359355 for the funnel that depends on it.',
        );
        failures += 1;
    } else {
        console.log(`OK   [${rule.event}]: present in ${rule.file}`);
    }
}

if (failures > 0) {
    console.error(`\n${failures} required PostHog event(s) missing from the source. Aborting.`);
    process.exit(1);
}

console.log('\nAll required onboarding/auth PostHog events are wired.');
process.exit(0);
