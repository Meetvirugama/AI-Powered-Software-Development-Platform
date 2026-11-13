from iso import parse_iso_utc
dt = parse_iso_utc('2026-11-13T12:00:00+00:00')
assert dt.year == 2026
