# Phase 3 — Live Camera and Employee Self-Service

## Objective

Add a visible employee portal and manager-reviewed correction/leave workflow while preserving the current QR display, attendance API behavior, roster system, manager dashboard, PostgreSQL data, and Orange Pi deployment.

This phase intentionally does not add kiosk registration. `/display/`, `/api/qr/`, and the dedicated display computer remain unchanged.

## Scope

### 1. Live camera attendance capture

Replace the current selfie file-picker experience with an in-page front-camera flow using `navigator.mediaDevices.getUserMedia()`.

Required behavior:

- Show live preview.
- Provide Capture, Retake, and Submit controls.
- Submit a JPEG blob created from the captured frame.
- Do not offer gallery selection in the normal supported flow.
- Stop all camera tracks after submit, navigation, or error.
- Preserve a clearly labelled compatibility fallback only when camera APIs are unavailable.
- Keep server-side image validation and recompression.
- Do not add facial recognition or biometric identification.

### 2. Employee PIN portal

Add these routes:

- `/employee/login/`
- `/employee/`
- `/employee/logout/`
- `/employee/leave/new/`
- `/employee/corrections/new/`

Authentication requirements:

- Employee selects their active employee record and enters the existing six-digit PIN.
- Reuse the existing PIN verification and lockout concepts; do not store raw PINs.
- On success store only the employee ID and authentication timestamp in the Django session.
- Employee session lifetime: 30 minutes of inactivity.
- Rotate the session key on login and flush it on logout.
- Employee routes must never expose another employee's records by changing a URL or form value.
- Login errors should not reveal unnecessary account details.

### 3. Employee dashboard

The employee dashboard must show only the authenticated employee's information:

- Name and division.
- Current IN/OUT state.
- Today's approved shifts.
- Approved roster for the next 14 days.
- Attendance history for the last 30 days.
- Clock-in, clock-out, and calculated duration.
- Status indicators such as on time, late, missing clock-out, no roster, or proxy event where available from existing services.
- Their own leave requests and statuses.
- Their own correction requests and statuses.

Do not show other employee names, photos, PIN information, IP addresses, user agents, or manager-only audit information.

### 4. Leave request submission

Reuse the existing `LeaveRequest` model.

Employee form fields:

- Date from.
- Date to.
- Leave type.
- Reason/note.

Validation:

- `date_to` cannot precede `date_from`.
- Limit one request to a configurable maximum range, default 31 days.
- Reject an exact duplicate active request.
- Employee cannot set status or approver.
- New requests are always `SUBMITTED`.

Manager workflow:

- Add a manager page or section listing submitted leave requests.
- Manager may approve or reject.
- Record `approved_by`.
- Use POST with CSRF protection.
- Do not silently modify roster assignments in this phase.

### 5. Attendance correction requests

Add one new model named `AttendanceCorrectionRequest` with a migration that depends on `0005_security_hardening`. Use the next available sequential migration number after inspecting current `main`.

Suggested fields:

- `employee`: ForeignKey to Employee.
- `session`: nullable ForeignKey to AttendanceSession using `SET_NULL`.
- `request_type`: choices `FORGOT_CLOCK_IN`, `FORGOT_CLOCK_OUT`, `WRONG_TIME`, `WRONG_ACTION`, `OTHER`.
- `requested_clock_in`: nullable DateTimeField.
- `requested_clock_out`: nullable DateTimeField.
- `reason`: TextField with a sensible length limit enforced in forms.
- `status`: `SUBMITTED`, `APPROVED`, `REJECTED`, `CANCELLED`.
- `created_at`, `reviewed_at`.
- `reviewed_by`: nullable ForeignKey to Django user using `SET_NULL`.
- `manager_note`: blank TextField.

Rules:

- Employee can submit only for themselves.
- Existing attendance rows must not be edited automatically when a request is submitted.
- Employee may cancel only their own `SUBMITTED` request.
- Manager may approve or reject through POST actions.
- Approval in this phase records the decision but does not silently rewrite historical attendance. Any actual correction must remain an explicit manager action in a later phase.
- Prevent duplicate submitted requests for the same employee/session/request type.

### 6. Manager review interface

Add manager-only views for:

- Submitted attendance correction requests.
- Submitted leave requests.
- Filtering by status, date, employee, and division.
- Approve/reject actions with manager notes.

Requirements:

- Reuse existing manager authorization rules.
- Every state-changing action must be POST-only and CSRF-protected.
- Show original attendance values beside requested values.
- Preserve audit history and never delete reviewed requests.

### 7. Privacy and security

- Remove `@csrf_exempt` from employee-facing state-changing endpoints where technically feasible; use Django CSRF tokens in fetch requests.
- Keep the existing attendance endpoint compatible with the QR workflow, but document any CSRF compatibility decision clearly in the PR.
- Apply `Cache-Control: no-store` to employee portal pages.
- Do not place PINs or sensitive employee information in URLs, logs, HTML data attributes, or JavaScript console output.
- Validate ownership server-side on every employee request.
- Rate-limit employee login attempts using existing PIN-attempt infrastructure or an equivalent tested approach.
- Do not serve attendance photos in the employee portal in this phase.

### 8. User interface

Use the existing Bootstrap styling and keep mobile use as the priority.

Employee dashboard navigation:

- Overview.
- My roster.
- Attendance history.
- Leave requests.
- Correction requests.
- Logout.

Use clear Indonesian labels and error messages consistent with the current application.

### 9. Tests

Add tests covering at minimum:

- Correct PIN login and logout.
- Wrong PIN and lockout behavior.
- Session rotation and expiry behavior.
- Employee cannot view another employee's data.
- Dashboard contains only the authenticated employee's records.
- Live-camera submission still produces a valid attendance photo payload at the backend boundary.
- Camera fallback does not bypass server-side image validation.
- Valid and invalid leave requests.
- Employee cannot approve their own leave request.
- Correction request creation, duplicate prevention, cancellation, approval, and rejection.
- Manager authorization for review pages.
- POST-only and CSRF behavior for state-changing actions.
- Existing QR, clock-in/out, manager dashboard, CSV export, protected photos, roster, and photo-purge tests continue to pass.

Run:

```bash
python manage.py check
python manage.py makemigrations --check --dry-run
python manage.py test attendance
```

If a migration is added, also run and include:

```bash
python manage.py showmigrations attendance
python manage.py migrate --plan
```

## Exclusions

Do not add in this phase:

- Kiosk-device registration.
- Cloudflare configuration changes.
- Telegram or WhatsApp notifications.
- Payroll calculations.
- Facial recognition or biometric matching.
- Automatic mutation of historical attendance after correction approval.
- Destructive cleanup of attendance, employee, roster, leave, or photo records.

## Pull request requirements

Implement in a separate branch and open a draft PR. Include:

- Visible employee and manager changes.
- New routes.
- Exact migration name and dependency.
- Security and privacy decisions.
- Test results.
- Exact Orange Pi deployment commands.
- Rollback notes.

Do not merge automatically.