from datetime import datetime, timedelta, timezone

from appeals import config

UTC = timezone.utc


def _rate(*args, tz=UTC):
    return config.load().reasoning.prices(datetime(*args, tzinfo=tz))[0]


def test_peak_hours_on_working_days():
    assert _rate(2026, 10, 14, 2, 30) == 'peak'          # Wednesday 02:30 UTC
    assert _rate(2026, 10, 14, 8, 0) == 'peak'
    assert _rate(2026, 10, 14, 4, 0) == 'off-peak'       # the gap between the two peak windows
    assert _rate(2026, 10, 14, 10, 0) == 'off-peak'      # windows end on the hour
    assert _rate(2026, 10, 14, 15, 0) == 'off-peak'


def test_weekends_and_holidays_are_off_peak():
    assert _rate(2026, 10, 17, 2, 0) == 'off-peak'       # Saturday
    assert _rate(2026, 10, 10, 2, 0) == 'off-peak'       # a make-up working Saturday
    assert _rate(2026, 10, 6, 2, 0) == 'off-peak'        # Tuesday in the National Day holiday
    assert _rate(2026, 2, 23, 7, 0) == 'off-peak'        # Monday, last day of Spring Festival


def test_local_times_are_converted_to_utc():
    eastern = timezone(timedelta(hours=-4))
    assert _rate(2026, 10, 13, 22, 30, tz=eastern) == 'peak'       # Wednesday 02:30 UTC


def test_a_year_without_a_holiday_calendar_is_priced_as_peak():
    reasoning = config.load().reasoning
    assert not reasoning.holidays_cover(2027)
    assert reasoning.prices(datetime(2027, 10, 6, 2, 0, tzinfo=UTC))[0] == 'peak'
