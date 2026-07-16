# Clinic Attendance Phase 5 timers

Example Orange Pi install path: `/srv/webapps/clinic-attendance-app`.

Install/update:

```bash
cd /srv/webapps/clinic-attendance-app
git fetch --all
/srv/webapps/clinic-attendance-app/.venv/bin/python manage.py migrate
sudo cp deploy/systemd/clinic-attendance-*.service deploy/systemd/clinic-attendance-*.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now clinic-attendance-fixed-shifts.timer clinic-attendance-alerts.timer
```

Verify:

```bash
systemctl list-timers 'clinic-attendance-*'
systemctl status clinic-attendance-fixed-shifts.timer clinic-attendance-alerts.timer
journalctl -u clinic-attendance-fixed-shifts.service -n 100 --no-pager
journalctl -u clinic-attendance-alerts.service -n 100 --no-pager
```

Manual runs:

```bash
cd /srv/webapps/clinic-attendance-app
.venv/bin/python manage.py generate_fixed_shifts --confirm --days 45
.venv/bin/python manage.py send_attendance_alerts --send --retry-failed
```

Disable/rollback timers:

```bash
sudo systemctl disable --now clinic-attendance-fixed-shifts.timer clinic-attendance-alerts.timer
sudo rm -f /etc/systemd/system/clinic-attendance-fixed-shifts.service /etc/systemd/system/clinic-attendance-fixed-shifts.timer /etc/systemd/system/clinic-attendance-alerts.service /etc/systemd/system/clinic-attendance-alerts.timer
sudo systemctl daemon-reload
```
