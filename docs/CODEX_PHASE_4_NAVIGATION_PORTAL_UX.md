# Phase 4 — Navigation and Portal UX

## Objective
Make every major workflow discoverable from the base URL without changing attendance, QR, roster, employee-session, or manager authorization logic.

## Scope

### 1. Shared base template
Create a reusable `attendance/base.html` with:
- Clinic/app name
- Mobile-first responsive navbar
- Home link
- Attendance link
- Employee Portal link
- Manager link
- Roster link only for authenticated Django users who can access it
- Context-aware employee portal login/logout controls

The `/display/` QR page must remain standalone and must not inherit the navigation bar.

### 2. Base URL landing page
Change `/` from being only the attendance form into a clear landing page with three primary cards:
- `Mulai Absensi` → dedicated attendance page
- `Portal Staff` → employee login or employee dashboard when already signed in
- `Portal Manager` → manager dashboard/login flow

Include a short explanation under each card. Keep the page usable on mobile phones.

### 3. Dedicated attendance route
Move the existing scan/selfie/PIN attendance interface to `/attendance/` while preserving all existing behavior and JavaScript.

Maintain backward compatibility:
- Existing bookmarks to `/` must still be useful through the landing page.
- API endpoints must remain unchanged.
- `/display/` must remain unchanged.

### 4. Context-aware employee link
When no employee session exists:
- Navbar and landing-page card link to `/employee/login/`
- Label: `Login Staff`

When an employee session is valid:
- Link to `/employee/`
- Display employee first/full name safely
- Offer POST-only logout with CSRF protection

Do not expose employee information from expired or invalid sessions.

### 5. Manager navigation
Provide visible links between:
- Manager dashboard
- Request review page
- Roster page when authorized
- Home

Do not weaken existing manager/staff authorization. Unauthorized users must still be redirected or rejected by current backend checks.

### 6. Employee portal navigation
Use the shared layout for:
- Employee login
- Employee dashboard
- Leave request form
- Correction request form

Employee navigation should include:
- Dashboard
- New leave request
- New correction request
- Back to attendance
- POST-only logout

### 7. Consistent feedback and usability
- Use Django messages consistently for successful login, logout, submission, cancellation, approval, rejection, and validation failure where practical.
- Show active navigation state.
- Use Indonesian labels consistently.
- Ensure buttons and touch targets are usable on small screens.
- Avoid new external JavaScript dependencies.
- Preserve accessibility labels and keyboard navigation.

### 8. Tests
Add tests covering:
- `/` shows links to attendance, employee portal, and manager portal
- `/attendance/` loads the existing attendance interface
- Employee link points to login when logged out
- Employee link points to dashboard when employee session is valid
- Expired employee session does not expose employee identity
- Employee logout remains POST-only and CSRF-protected
- Manager and roster links do not bypass authorization
- `/display/` remains unchanged and standalone
- Existing clock-in/out, QR, manager, roster, leave, and correction tests continue to pass

## Database and migration requirements
No model or database changes are expected. Do not create a migration unless a genuine schema requirement is discovered. Any unexpected migration must be explained before implementation.

## Exclusions
- No kiosk registration
- No Cloudflare changes
- No notifications
- No payroll
- No facial recognition
- No modification of historical attendance data
- No change to QR token behavior

## Validation
Run:
- `python manage.py check`
- `python manage.py makemigrations --check --dry-run`
- `python manage.py test attendance`

The implementation PR must describe visible navigation changes, route changes, compatibility behavior, test results, deployment commands, and rollback steps.