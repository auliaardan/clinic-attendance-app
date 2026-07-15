# Phase 5 — Fixed Schedules and Operational Alerts

## Objective

Extend the attendance application so the same codebase supports both:

1. **Roster-based divisions**, such as the clinic, where approved shifts vary by employee and date.
2. **Fixed-hours divisions**, such as an office, where active employees normally work the same recurring hours on selected weekdays.

Also add reliable manager notifications for operational events without blocking attendance submissions or requiring Celery/Redis.

This phase must preserve all existing attendance, QR, employee portal, manager dashboard, roster, leave, correction, photo, and PostgreSQL data.

---

## Core design decision

Do not create a second attendance calculation engine for fixed-office workers.

The existing manager dashboard, employee portal, no-show calculations, late calculations, and missing-clock-out logic already operate on approved `ShiftAssignment` rows. Fixed schedules must therefore generate ordinary approved `ShiftAssignment` rows automatically.

This provides one shared source of expected attendance:

- Clinic roster → manager-created approved `ShiftAssignment`
- Office fixed hours → system-generated approved `ShiftAssignment`

Historical generated shifts remain snapshots, so changing a fixed schedule later must not silently rewrite past attendance expectations.

---

## 1. Division scheduling modes

Add a scheduling mode to `Division`:

- `ROSTER` — existing manual roster workflow
- `FIXED` — recurring fixed-hours workflow

Requirements:

- Existing divisions must default to `ROSTER` in the migration.
- Existing clinic behaviour must remain unchanged.
- A deployment for an office may set its divisions to `FIXED`.
- The same installation may contain both roster and fixed divisions.
- Do not infer a mode from the division name.

Suggested field:

```python
schedule_mode = models.CharField(
    max_length=12,
    choices=(("ROSTER", "Roster-based"), ("FIXED", "Fixed hours")),
    default="ROSTER",
)
```

---

## 2. Fixed weekly schedule rules

Add `FixedScheduleRule`.

Suggested fields:

- `division` — foreign key to `Division`
- `weekday` — integer `0` through `6`, Monday through Sunday
- `is_workday` — boolean
- `start_time` — nullable when `is_workday=False`
- `end_time` — nullable when `is_workday=False`
- `created_at`
- `updated_at`

Requirements:

- Unique rule per division and weekday.
- Workday rules require start and end times.
- Non-workday rules must not generate shifts.
- Overnight fixed schedules are allowed when `end_time <= start_time`.
- Rules are relevant only when the division is in `FIXED` mode.

Example office configuration:

| Day | Workday | Start | End |
|---|---:|---:|---:|
| Monday | Yes | 08:00 | 17:00 |
| Tuesday | Yes | 08:00 | 17:00 |
| Wednesday | Yes | 08:00 | 17:00 |
| Thursday | Yes | 08:00 | 17:00 |
| Friday | Yes | 08:00 | 17:00 |
| Saturday | No | — | — |
| Sunday | No | — | — |

---

## 3. Calendar exceptions

Add `ScheduleException` so fixed offices do not produce false no-shows on holidays or special working days.

Suggested fields:

- `division` — foreign key to `Division`
- `date`
- `is_workday`
- `start_time` — nullable override
- `end_time` — nullable override
- `note` — short manager-visible explanation
- `created_at`
- `updated_at`

Requirements:

- Unique exception per division and date.
- `is_workday=False` represents a holiday or office closure.
- `is_workday=True` may override the normal weekday rule and optionally provide different start/end times.
- An explicit exception takes precedence over the weekly rule.
- Exceptions affect fixed divisions only.
- Past generated shifts must never be deleted automatically.

---

## 4. Generated-shift provenance

Extend `ShiftAssignment` with a source marker.

Suggested fields:

```python
SOURCE_CHOICES = (("MANUAL", "Manual roster"), ("FIXED", "Fixed schedule"))
source = models.CharField(max_length=12, choices=SOURCE_CHOICES, default="MANUAL")
fixed_schedule_rule = models.ForeignKey(
    FixedScheduleRule,
    null=True,
    blank=True,
    on_delete=models.SET_NULL,
    related_name="generated_shifts",
)
```

Requirements:

- All existing shift assignments migrate as `MANUAL`.
- Fixed-generated assignments use `FIXED`.
- Fixed-generated assignments are always `APPROVED`.
- Add a conditional uniqueness constraint allowing at most one `FIXED` assignment per employee and date.
- Preserve the existing uniqueness rule for employee/date/start/end.
- Never convert an existing manual assignment into a fixed-generated assignment.
- A manual assignment for an employee/date takes precedence and causes fixed generation for that employee/date to be skipped.
- Non-manager roster editors must not edit or delete `FIXED` assignments.

---

## 5. Fixed-shift generation command

Add an idempotent management command:

```bash
python manage.py generate_fixed_shifts
```

The command must be dry-run by default. Database writes require `--confirm`.

Supported options:

- `--from-date YYYY-MM-DD`, default local date
- `--days N`, default 45
- `--division ID`, optional
- `--confirm`
- `--verbosity`

Generation rules:

1. Process only active divisions in `FIXED` mode.
2. Process active employees whose `EmployeeProfile.division` matches the division and whose `is_rostered=True`.
3. Resolve the date using `ScheduleException` first, then `FixedScheduleRule`.
4. Skip non-workdays.
5. Skip employees with an existing manual assignment for the date.
6. Create missing fixed assignments as `APPROVED`.
7. For future dates only, update an existing fixed assignment when the applicable rule changes.
8. Never rewrite a past date.
9. Never rewrite attendance sessions or attendance events.
10. Be safe to run repeatedly without creating duplicates.
11. Report created, updated, skipped, and unchanged counts.
12. Use `timezone.localdate()` and the project timezone.

Approved leave handling:

- Fixed generation may leave an already-generated shift in place.
- Dashboard calculations and alerts must treat approved leave as excused and must not report the employee as late, absent, or missing clock-out for that date.
- When generating a shift for a date that already has approved leave, the command may skip it, but correctness must not depend solely on generation order.

Recommended operation:

- Run the command daily and generate approximately 45 days ahead.
- New employees then receive future fixed assignments on the next run.

---

## 6. Manager schedule configuration

Add a manager-only page:

```text
/manager/schedules/
```

The page must allow a staff manager to:

- See every active division and its scheduling mode.
- Change a division between `ROSTER` and `FIXED`.
- Configure Monday–Sunday fixed rules.
- Add, edit, and remove future calendar exceptions.
- See the last fixed-shift generation result if available in the page response.
- Run a dry-run preview for a selected division/date range.
- Confirm generation through a POST-only, CSRF-protected action.

Safety requirements:

- Changing a mode does not delete shifts.
- Changing fixed hours does not rewrite past shifts.
- Switching from `FIXED` to `ROSTER` stops future automatic generation but retains already generated assignments.
- All state-changing actions are POST-only and CSRF-protected.
- Manager authorization must use the existing staff-manager protection.

Navigation:

- Add `Jadwal Kerja` or `Pengaturan Jadwal` to the manager navigation.
- Do not add schedule configuration to the public attendance page or QR display.

Roster page behaviour:

- Roster-based divisions continue using the existing workflow.
- Fixed divisions show a clear banner explaining that shifts are generated from fixed hours.
- Fixed-generated rows are read-only to non-manager roster editors.
- Use calendar exceptions rather than direct editing for holidays and special days.

---

## 7. Shared attendance classification

Continue using `classify_shift()` and approved `ShiftAssignment` rows for both modes.

Requirements:

- Do not branch the clock-in/clock-out API based on schedule mode.
- Employees can still clock in and out using the existing QR, PIN, and selfie process.
- The schedule controls classification and alerts; it does not prevent a legitimate attendance event.
- Existing grace-period, no-show, early-window, overnight, and missing-clock-out behaviour remains configurable.
- Approved leave must suppress no-show and missing-clock-out exceptions for both schedule modes.
- The employee portal must display generated fixed shifts in the same roster/history area as manual shifts, with a small `Fixed schedule` label.
- CSV export may include a non-sensitive schedule source column.

---

## 8. Telegram notification transport

Implement Telegram as the first notification transport through the official HTTPS Bot API.

Do not add a Telegram SDK unless it is clearly necessary. A small HTTP client with explicit timeouts is sufficient.

Environment settings:

```text
TELEGRAM_ALERTS_ENABLED=false
TELEGRAM_BOT_TOKEN=
TELEGRAM_CHAT_IDS=
ATTENDANCE_ALERT_DAILY_SUMMARY_TIME=18:00
ATTENDANCE_ALERT_REQUEST_LOOKBACK_DAYS=7
ATTENDANCE_ALERT_HTTP_TIMEOUT_SECONDS=10
```

Requirements:

- Bot token and chat IDs must come from environment variables.
- Never store or display the bot token in the database, admin, templates, exceptions, or logs.
- `TELEGRAM_CHAT_IDS` may contain comma-separated chat IDs.
- The manager UI may show only whether configuration is present, never its value.
- Use HTTPS POST requests.
- Apply connection/read timeout.
- A Telegram failure must never fail clock-in, clock-out, leave submission, or correction submission.
- Do not send attendance photos, PINs, raw QR tokens, IP addresses, or full user-agent strings.
- Escape or safely format employee-entered text.

---

## 9. Notification delivery audit and deduplication

Add `NotificationDelivery`.

Suggested fields:

- `event_type`
- `dedupe_key` — unique
- `employee` — nullable foreign key
- `division` — nullable foreign key
- `target_date` — nullable
- `status` — `PENDING`, `SENT`, or `FAILED`
- `attempts`
- `last_error` — bounded text with secrets removed
- `created_at`
- `last_attempt_at`
- `sent_at`

Required event types:

- `NEW_LEAVE_REQUEST`
- `NEW_CORRECTION_REQUEST`
- `NO_SHOW`
- `MISSING_CLOCKOUT`
- `PROXY_ATTENDANCE`
- `PIN_LOCKOUT`
- `DAILY_SUMMARY`

Deduplication examples:

- Leave request: request primary key
- Correction request: request primary key
- No-show: employee + shift assignment + date
- Missing clock-out: attendance session + applicable shift/date
- Proxy attendance: attendance event primary key
- PIN lockout: employee + purpose + `locked_until`
- Daily summary: local date + target chat

Requirements:

- Unique dedupe keys prevent repeated messages when the scheduled command runs frequently.
- Failed deliveries may be retried with bounded attempts.
- A successful delivery is never automatically resent.
- Store concise errors only; redact tokens and sensitive URL data.

---

## 10. Alert collection and sending command

Add:

```bash
python manage.py send_attendance_alerts
```

The command is dry-run by default. Actual delivery requires `--send`.

Supported options:

- `--send`
- `--event-type`, optional filter
- `--division ID`, optional
- `--date YYYY-MM-DD`, optional
- `--retry-failed`
- `--max-retries`, sensible default

Behaviour:

1. Build alert candidates from database state.
2. Use the same approved-shift classification logic as the manager dashboard.
3. Support both manual roster shifts and generated fixed shifts.
4. Exclude inactive employees and approved leave.
5. Create or reuse a deduplicated delivery record.
6. In dry-run mode, display what would be sent without changing delivery status or contacting Telegram.
7. In send mode, deliver to configured chats and record success/failure.
8. Continue processing other alerts after one failure.
9. Return a non-zero exit only for command-level configuration or database failures, not for a single Telegram recipient failure.

Alert timing:

- `NEW_LEAVE_REQUEST` and `NEW_CORRECTION_REQUEST`: next scheduled run after submission.
- `NO_SHOW`: only after the configured no-show threshold.
- `MISSING_CLOCKOUT`: only after shift end plus tolerance.
- `PROXY_ATTENDANCE`: next scheduled run.
- `PIN_LOCKOUT`: after a lockout is created.
- `DAILY_SUMMARY`: once per local date after the configured summary time.

Daily summary content should include concise counts:

- Expected employees
- On time
- Late
- No-show
- On approved leave
- Missing clock-out
- Proxy attendance events
- Pending leave requests
- Pending correction requests

Do not include photos or PIN-related details.

---

## 11. Manager alert status page

Add a manager-only page:

```text
/manager/alerts/
```

Display:

- Telegram alerts enabled/disabled
- Configuration complete/incomplete without revealing secrets
- Recent delivery status
- Event type
- Employee/division where appropriate
- Created, attempted, and sent times
- Sanitized error message
- Filter by status, event type, date, and division

Actions:

- Retry a failed delivery through POST + CSRF.
- Run a dry-run preview.
- Do not allow arbitrary Telegram messages from the web UI in this phase.

Add a manager navigation link named `Notifikasi`.

---

## 12. Scheduling the commands on Orange Pi

Do not add Celery, Redis, RabbitMQ, or another persistent task platform.

Provide documented systemd service/timer examples under `deploy/systemd/`:

- `clinic-attendance-fixed-shifts.service`
- `clinic-attendance-fixed-shifts.timer`
- `clinic-attendance-alerts.service`
- `clinic-attendance-alerts.timer`

Recommended cadence:

- Fixed-shift generation: daily shortly after midnight, with `--confirm`.
- Alert checking: every five minutes, with `--send`.

Requirements:

- Templates must make the project path, service user, environment file, and Python/virtualenv path obvious.
- Do not automatically enable or install timers during Django migration.
- Include manual installation, enable, status, log, disable, and rollback commands in deployment documentation.
- Commands must use a lock or another safe mechanism to avoid overlapping runs.

---

## 13. Migration requirements

A migration is expected.

Before creating it, inspect the latest migrations on `main`.

Expected next migration is likely:

```text
0007_fixed_schedules_and_alerts.py
```

It must depend on the actual latest migration, currently expected to be:

```text
0006_employee_self_service
```

Migration rules:

- Existing divisions default to `ROSTER`.
- Existing shift assignments default to `MANUAL`.
- Do not recreate any existing roster, leave, employee, session, event, correction, or PIN table.
- Do not delete or rewrite attendance records.
- Do not use `--fake` or `--fake-initial` as deployment instructions.
- Add indexes and constraints with stable explicit names.

---

## 14. Security and privacy

- Keep `/display/` unchanged.
- Keep existing QR, PIN, selfie, and attendance APIs compatible.
- Do not include photos in Telegram alerts.
- Do not expose employee PIN hashes or PIN attempts beyond concise lockout alerts.
- Manager pages remain staff-authenticated.
- State-changing actions remain POST-only and CSRF-protected.
- Use server-side schedule resolution; never trust schedule mode, shift source, or alert type supplied by a browser.
- Do not expose Telegram credentials to frontend JavaScript.
- Sanitize external API error messages before storage/display.

---

## 15. Tests

Add comprehensive tests covering at least:

### Fixed schedule models and generation

- Existing divisions default to roster mode.
- Existing/manual shifts remain manual.
- Fixed Monday–Friday rules generate approved assignments.
- Weekend rules do not generate assignments.
- Overnight fixed hours generate correct shift datetimes.
- Calendar holiday suppresses generation.
- Special working-day exception generates overridden hours.
- Manual assignment prevents duplicate fixed generation.
- Repeated command is idempotent.
- Future fixed assignment updates when a rule changes.
- Past assignments never change.
- Inactive or non-rostered employees are skipped.
- Mixed roster and fixed divisions work simultaneously.
- Non-manager roster editor cannot modify a fixed-generated assignment.

### Classification and leave

- Fixed-generated shift uses existing on-time/late/no-show classification.
- Approved leave suppresses no-show and missing-clock-out alerts.
- Clinic roster classification regression tests continue to pass.
- Employee portal shows fixed-generated schedule only for the logged-in employee.

### Notifications

- Dry-run never contacts Telegram.
- Disabled/unconfigured notifications do not contact Telegram.
- Telegram HTTP calls are mocked in tests.
- Successful delivery records `SENT`.
- Failed delivery records sanitized failure data.
- Duplicate scheduled runs do not resend successful alerts.
- Retry works only for eligible failed records.
- Each required event type generates the correct dedupe key.
- Daily summary is sent once per local date.
- Alert failures do not affect attendance or request submission.
- No message contains PIN, photo path, QR token, IP address, or user-agent data.

### Authorization

- Schedule and alert pages require manager access.
- POST actions reject GET.
- CSRF protection remains enabled.
- Existing employee and manager authorization tests continue to pass.

Run:

```bash
python manage.py check
python manage.py makemigrations --check --dry-run
python manage.py showmigrations attendance
python manage.py migrate --plan
python manage.py test attendance
```

---

## 16. Pull request requirements

Implement in a separate branch and open a draft pull request into `main`.

The implementation PR must include:

- Exact migration name and dependency
- Summary of new models and fields
- Explanation of why fixed schedules generate normal approved shifts
- Mixed clinic/office behaviour
- Alert event and deduplication behaviour
- Environment variables
- Test results
- Orange Pi deployment commands using `/srv/webapps/clinic-attendance-app`
- systemd timer installation and verification commands
- Rollback instructions

Do not merge automatically.

---

## Explicit exclusions

Do not add in this phase:

- Facial recognition or biometric verification
- Kiosk-device registration
- Payroll calculations
- Overtime approval/payment calculations
- WhatsApp integration
- GPS/geofencing
- Automatic disciplinary action
- Automatic rewriting of attendance history
- Celery, Redis, RabbitMQ, or another message broker

Telegram is the only notification transport for this phase, but the internal notification service should not prevent adding another provider later.