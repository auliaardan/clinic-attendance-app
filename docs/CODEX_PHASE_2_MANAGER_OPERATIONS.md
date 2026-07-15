# Phase 2: Manager Operations

Implement this phase on a new branch from the latest `main`. Do not push directly to `main`. Open a draft pull request.

## Objective

Make the manager experience visibly more useful without changing the employee clock-in/clock-out workflow.

## Required features

### 1. Manager dashboard redesign

Keep the existing manager URL and authentication rules. Improve the dashboard with:

- Date selector, defaulting to today.
- Division filter, with an All Divisions option.
- KPI cards for scheduled shifts, attended shifts, on-time, late, no-show, currently open sessions, missing clock-outs, proxy events, and locked PIN attempts.
- A prominent Exception Inbox showing actionable items only.
- Existing attendance statistics must remain available.
- Responsive design that works on desktop and mobile.
- Do not add external frontend frameworks or new CDN dependencies.

### 2. Exception Inbox

Compute and display these exceptions:

- No show: approved shift has no qualifying attendance after the configured no-show threshold.
- Late arrival.
- Missing clock-out: session remains open beyond shift end plus a configurable tolerance.
- Open session longer than 10 hours when no usable approved shift is available.
- Proxy attendance event.
- PIN currently locked after repeated failures.
- Attendance without an approved roster.

Each row must show employee, division, date/time, exception type, relevant shift, and a concise explanation.

Do not modify historical attendance automatically from the dashboard.

### 3. Correct session/shift calculations

- An open session must not cover a later shift simply because it remains open.
- Attendance coverage for a shift must be bounded to the relevant shift window, with configurable early and late tolerances.
- Missing clock-out must be treated as an exception, not as unlimited attendance.
- Overnight shifts must remain supported.
- Keep raw attendance records separate from calculated attendance status.

Put reusable calculation logic in services rather than duplicating it in views.

### 4. CSV export

Add a manager-only CSV export using the same date and division filters.

Include:

- Employee
- Division
- Shift date
- Shift start and end
- First qualifying clock-in
- Qualifying clock-out
- Calculated status
- Minutes late
- Missing clock-out flag
- Proxy flag
- Attendance event IDs or session ID for audit reference

CSV export must not include photo paths, PIN data, hashes, IP addresses, or user-agent data.

### 5. Protected attendance photos

Attendance photos must not be accessible through a public predictable media URL.

- Add a manager-authenticated photo-serving view.
- Confirm the requesting user has manager access.
- Stream the file safely or return 404 when it has been removed.
- Update manager templates to use this protected endpoint.
- Preserve compatibility when older attendance records have an empty photo field.
- Do not expose absolute filesystem paths.

### 6. Photo retention command

Add a Django management command:

```bash
python manage.py purge_attendance_photos --older-than-days 90
```

Requirements:

- Default dry-run mode. It reports count and estimated bytes without deleting.
- Require `--confirm` for actual deletion.
- Delete only the stored image and clear the `photo` field.
- Never delete AttendanceEvent, AttendanceSession, Employee, roster, or leave records.
- Support `--older-than-days`, `--before YYYY-MM-DD`, and `--limit`.
- Continue after an individual file error and print a failure summary.
- Be safe when the file is already missing.
- Add tests for dry-run, confirmed deletion, missing file, and record retention.

### 7. Configuration

Move operational thresholds to Django settings with safe defaults:

- Attendance early window minutes
- Grace period minutes
- No-show threshold minutes
- Missing clock-out tolerance minutes
- Long open-session threshold hours

Read environment variables where appropriate, but defaults must preserve current behavior as closely as possible.

### 8. Tests

Add tests proving:

- Manager dashboard requires authentication and manager permission.
- Filters work by date and division.
- Open sessions do not cover later shifts.
- Overnight shifts calculate correctly.
- Missing clock-out is flagged.
- CSV export excludes sensitive fields.
- Photo endpoint rejects unauthenticated and unauthorized users.
- Deleted/missing photos return 404 without deleting attendance records.
- Purge command is dry-run by default and deletes only with `--confirm`.
- Existing clock-in/clock-out tests continue to pass.

## Non-goals for this phase

Do not implement:

- WhatsApp, Telegram, email, or push notifications.
- Employee accounts or employee self-service.
- Payroll calculations.
- Facial recognition or liveness detection.
- Multi-site architecture.
- A new JavaScript framework.

## Migration safety

- Do not rewrite or replace migrations `0001` through `0005`.
- Any new database migration must start after the latest existing migration.
- Prefer no new database model unless clearly required.
- Migrations must support PostgreSQL production and SQLite tests.
- Never drop production tables or historical attendance records.

## Validation

Run:

```bash
python manage.py check
python manage.py makemigrations --check --dry-run
python manage.py test attendance
```

Also inspect the generated migration plan if a migration is introduced.

## Pull request requirements

The draft PR description must include:

- Visible manager-facing changes.
- Any new URL routes.
- Calculation rules and thresholds.
- Privacy/security impact.
- Tests executed.
- Orange Pi deployment commands.
- Rollback instructions.
