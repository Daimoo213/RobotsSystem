# Changelog

All notable changes are recorded here. Versions follow Semantic Versioning.

## [Unreleased]

### Changed

- Group compatible Dependabot updates and require manual review for major dependency upgrades.
- Keep all five O&M device health indicators on one row and reserve space for the deck scrollbar.
- Show every connected device in the bottom deck and highlight the selected card.
- Treat missing or offline device health values as unknown instead of displaying them as healthy.
- Define a right-handed, Z-up project map-frame contract and reject mismatched device or map coordinates.
- Preserve coordinate handedness when converting project map data into the Three.js scene.
- Generate map point and region codes with `crypto.getRandomValues()` so saving works over LAN HTTP addresses.

### Added

- Add per-device authenticated map manifests, stable revisions, conditional requests, and versioned complete point-cloud downloads for robot gateways.

## [0.1.1] - 2026-07-21

### Fixed

- Install pnpm before enabling the GitHub Actions pnpm cache.
- Isolate production-secret tests from CI process environment values.

## [0.1.0] - 2026-07-21

### Added

- Real PostgreSQL/Redis-backed backend and PM/O&M applications.
- Authenticated device gateway contracts for real robots and external simulators.
- Container deployment, health checks, backup/restore, and portable release bundles.
- GitHub Actions CI, versioned GHCR images, and GitHub Release automation.
