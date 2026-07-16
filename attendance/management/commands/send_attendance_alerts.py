from datetime import date
from django.core.management.base import BaseCommand, CommandError
from attendance.services import process_alerts

class Command(BaseCommand):
    help = "Preview or send attendance operational alerts."
    def add_arguments(self, parser):
        parser.add_argument('--send', action='store_true')
        parser.add_argument('--event-type')
        parser.add_argument('--division', type=int)
        parser.add_argument('--date')
        parser.add_argument('--retry-failed', action='store_true')
        parser.add_argument('--max-retries', type=int, default=3)
    def handle(self, *args, **opts):
        try:
            target_date = date.fromisoformat(opts['date']) if opts.get('date') else None
        except ValueError as exc:
            raise CommandError('Invalid --date') from exc
        rows = process_alerts(send=opts['send'], event_type=opts.get('event_type'), division_id=opts.get('division'), target_date=target_date, retry_failed=opts['retry_failed'], max_retries=opts['max_retries'])
        self.stdout.write(('SEND' if opts['send'] else 'DRY-RUN') + f' alerts={len(rows)}')
        for rec, msg, status in rows:
            self.stdout.write(f"{status} {rec.event_type} {rec.dedupe_key} {msg}")
