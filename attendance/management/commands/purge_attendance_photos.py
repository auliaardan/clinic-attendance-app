from datetime import datetime, time

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from attendance.models import AttendanceEvent


class Command(BaseCommand):
    help = "Dry-run or purge old attendance photo files while retaining attendance records."

    def add_arguments(self, parser):
        parser.add_argument("--older-than-days", type=int, default=90)
        parser.add_argument("--before")
        parser.add_argument("--limit", type=int)
        parser.add_argument("--confirm", action="store_true")

    def handle(self, *args, **opts):
        if opts["before"]:
            try:
                cutoff_date = datetime.strptime(opts["before"], "%Y-%m-%d").date()
            except ValueError as exc:
                raise CommandError("--before must be YYYY-MM-DD") from exc
            cutoff = timezone.make_aware(datetime.combine(cutoff_date, time.min))
        else:
            cutoff = timezone.now() - timezone.timedelta(days=opts["older_than_days"])
        qs = AttendanceEvent.objects.exclude(photo="").filter(created_at__lt=cutoff).order_by("created_at", "id")
        if opts["limit"]:
            qs = qs[: opts["limit"]]
        scanned = deleted = missing = failures = bytes_total = 0
        failure_details = []
        for event in qs:
            scanned += 1
            try:
                size = event.photo.size
            except (OSError, FileNotFoundError, ValueError):
                size = 0
                missing += 1
            bytes_total += size
            if not opts["confirm"]:
                continue
            try:
                event.photo.delete(save=False)
                event.photo = ""
                event.save(update_fields=["photo"])
                deleted += 1
            except Exception as exc:  # keep purging other records after one file/storage error
                failures += 1
                failure_details.append(f"event {event.id}: {exc}")
        mode = "CONFIRMED" if opts["confirm"] else "DRY RUN"
        self.stdout.write(f"{mode}: matched={scanned} estimated_bytes={bytes_total} deleted={deleted} missing_files={missing} failures={failures}")
        if failure_details:
            self.stdout.write("Failure summary:")
            for line in failure_details:
                self.stdout.write(line)
