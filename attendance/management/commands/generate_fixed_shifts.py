from datetime import date
from django.core.management.base import BaseCommand, CommandError
from attendance.services import generate_fixed_shifts

class Command(BaseCommand):
    help = "Preview or generate approved fixed-schedule shift assignments."
    def add_arguments(self, parser):
        parser.add_argument('--from-date')
        parser.add_argument('--days', type=int, default=45)
        parser.add_argument('--division', type=int)
        parser.add_argument('--confirm', action='store_true')
    def handle(self, *args, **opts):
        try:
            from_date = date.fromisoformat(opts['from_date']) if opts.get('from_date') else None
        except ValueError as exc:
            raise CommandError('Invalid --from-date') from exc
        counts = generate_fixed_shifts(from_date=from_date, days=opts['days'], division_id=opts.get('division'), confirm=opts['confirm'])
        mode = 'CONFIRMED' if opts['confirm'] else 'DRY-RUN'
        self.stdout.write(f"{mode} created={counts['created']} updated={counts['updated']} skipped={counts['skipped']} unchanged={counts['unchanged']}")
