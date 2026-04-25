# Mobile Release Checklist — Day 1

## 1) Build/Config

- [ ] Verify app identifiers (bundle ID / package name).
- [ ] Verify signing credentials (iOS cert/profile, Android keystore).
- [ ] Verify EAS environment variables for `preview`/`production`.
- [ ] Verify production API base URL.

## 2) Functional Smoke (must pass)

- [ ] App launch + onboarding.
- [ ] Auth flow.
- [ ] Core user flow #1.
- [ ] Core user flow #2.
- [ ] Network error fallback.
- [ ] Session restore after app restart.

## 3) Non-functional

- [ ] Crash-free startup on target devices.
- [ ] Analytics events fire in key steps.
- [ ] Performance sanity (no obvious lag/blocking in critical screens).

## 4) Distribution

- [ ] Android internal testing build uploaded.
- [ ] iOS TestFlight build uploaded.
- [ ] Test notes distributed to reviewers.

## 5) Store Readiness Draft

- [ ] App icon/splash final.
- [ ] Screenshots draft complete.
- [ ] Privacy policy URL final.
- [ ] Support email/URL final.
- [ ] Release notes draft.

## 6) Exit Criteria Day 1

- [ ] At least one installable build per platform.
- [ ] All P0 smoke checks green.
- [ ] Known issues logged with priority and owner.
