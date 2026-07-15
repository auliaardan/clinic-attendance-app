# Codex task: safely harden clinic attendance controls

Work only on a new branch based on the latest `main`. Do not push directly to `main`. Open a draft pull request when finished.

## Objective

Close the highest-risk attendance loopholes without redesigning the current staff workflow or breaking existing URLs, roster pages, manager pages, Orange Pi deployment, or current database records.

## Mandatory safety process

1. Read `README.md`, `attendance/models.py`, `attendance/views.py`, `attendance/qr.py`, `attendance/urls.py`, templates, migrations, and tests before editing.
2. Run the existing test suite and `python manage.py check` before changes.
3. Add tests that reproduce each defect before fixing it.
4. Make migrations additive and reversible. Never delete or rewrite existing attendance records.
5. Preserve the current public routes and form field names unless explicitly required below.
6. Keep SQLite compatibility because production may use SQLite on an Orange Pi.
7. Run after changes:
   - `python manage.py check`
   - `python manage.py makemigrations --check --dry-run`
   - `python manage.py test`
8. Summarize migrations and any required deployment commands in the pull request.

## Phase 1 scope

### 1. Prevent stale open sessions from creating false attendance

Current risk: an open session from a previous date can overlap later scheduled shifts and be counted as `COVERED` or on time.

Required behavior:

- An attendance session may only establish attendance for the shift/date it legitimately belongs to.
- A forgotten clock-out from a previous day must never count as attendance for a later shift.
- Keep showing old open sessions under manager exceptions as `MISSING_OUT` or equivalent.
- Do not silently modify historical clock-out times.
- Extract attendance/shift matching into testable helper functions rather than duplicating rules in daily and monthly dashboard calculations.
- Correctly handle normal same-day shifts. If overnight shifts are unsupported, explicitly reject or flag them instead of calculating misleading results.

Add tests for:

- Yesterday's open session does not cover today's shift.
- A same-day session overlapping today's shift counts as covered.
- A session near the shift start is classified on time or late according to the configured grace period.
- Approved leave excludes the shift from attendance denominators.

### 2. Prevent multiple open sessions per employee

Required behavior:

- Add a conditional database uniqueness constraint so one employee cannot have more than one `AttendanceSession` where `is_open=True`.
- Before applying the constraint, include a safe data migration that resolves pre-existing duplicates deterministically without deleting events. Keep the newest legitimate session open and close/flag older duplicates in a documented manner.
- Wrap clock-in and clock-out state changes in `transaction.atomic()`.
- Lock relevant employee/session rows with `select_for_update()` where supported.
- Catch `IntegrityError` and return the existing user-friendly HTTP 409 response rather than a 500 error.

Add tests for:

- Repeated clock-in receives 409.
- Duplicate open sessions are rejected by the database.
- Clock-out closes the correct open session.

### 3. Fix photo validation order and invalid image handling

Current frontend risk: `resizeImage(photoFile)` is called before checking whether a photo exists.

Required behavior:

- Check `photoFile` before resizing it.
- Disable the submit button during submission to prevent accidental double taps, then restore it after completion.
- On the server, catch Pillow image decoding/verification errors and return HTTP 400 with a clear message rather than HTTP 500.
- Retain the current 10 MB upload cap and JPEG recompression behavior.

Add tests for:

- Missing photo returns 400.
- Invalid/non-image upload returns 400.
- Valid small image succeeds when other attendance requirements are valid.

### 4. Make attendance records append-only in Django admin

Required behavior:

- `AttendanceEvent` must be read-only after creation.
- Do not allow deletion of attendance events through Django admin.
- `AttendanceSession` timestamps and employee must not be freely editable through admin.
- Do not remove manager visibility of records and photographs.
- Future corrections should be represented by separate adjustment records, but implementing the full correction workflow is out of scope for this PR.

Add tests for the relevant admin permissions where practical.

### 5. Lock approved rosters

Current risk: roster submission deletes and recreates assignments for each employee/day, including assignments that may already be approved.

Required behavior:

- Non-manager roster editors must not modify or delete approved assignments.
- A submitted or approved week must show a clear locked/read-only state.
- Managers retain the ability to approve submitted assignments.
- Do not implement silent post-approval replacement.
- Preserve existing roster URLs and general layout.

Add tests for:

- Division editor cannot alter an approved assignment.
- Division editor can modify a non-approved assignment in their permitted division.
- User cannot edit another division.
- Manager approval still works.

### 6. Add conservative PIN attempt throttling

Implement a database-backed solution compatible with one Orange Pi process and SQLite; do not add Redis or Celery in this phase.

Required behavior:

- Track failed PIN attempts by employee and client IP.
- Default policy: 5 failures within 15 minutes causes a 15-minute lockout.
- Successful authentication clears or resets the relevant failure state.
- Return HTTP 429 during lockout with a generic message that does not reveal whether a PIN was almost correct.
- Proxy subject and witness PINs must be throttled independently.
- Store only operational metadata; never store raw PINs.
- Add indexes and cleanup strategy for old attempt records.

Add tests for threshold, lockout expiry, successful reset, and witness isolation.

## Explicitly out of scope for this pull request

Do not implement these yet:

- Facial recognition or biometric identity matching
- Random liveness prompts
- WhatsApp/Telegram integration
- Payroll calculations
- Full HR correction workflow
- Multi-clinic architecture
- Major UI redesign
- Replacing all current QR behavior
- Removing the employee selector

These should be separate pull requests after Phase 1 is stable.

## Code quality requirements

- Prefer small named services/helpers over enlarging `manager_dashboard()` further.
- Avoid hard-coded business constants inside templates.
- Use Django timezone-aware datetimes.
- Keep error responses consistent: `{ "ok": false, "error": "..." }`.
- Do not expose raw exception details to clients.
- Avoid unnecessary dependencies.
- Document any changed attendance interpretation in README.

## Definition of done

- All old and new tests pass.
- Migration applies successfully on a copy of an existing database.
- Existing home, QR display, manager, roster, admin login, clock-in, clock-out, and proxy workflows still load.
- No historical attendance event is deleted.
- A stale open session cannot credit attendance on a later date.
- Database prevents multiple open sessions for one employee.
- Approved rosters cannot be silently overwritten by division editors.
- Invalid photo uploads do not produce server errors.
- Repeated PIN guessing is throttled.
- Draft PR clearly lists risks, migration effects, validation performed, and manual deployment steps.
