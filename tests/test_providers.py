import json
from datetime import date, datetime, timedelta, timezone

import pytest

from appeals import config, providers
from appeals.providers import Usage

UTC = timezone.utc


def _deepseek():
    return config.load().reasoning.model


def _rate(*args, tz=UTC):
    return _deepseek().charge(Usage(), datetime(*args, tzinfo=tz)).basis['rate']


# ---- DeepSeek peak hours ---------------------------------------------------------------

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
    provider = _deepseek().provider
    assert provider.warnings(date(2027, 1, 1)) and not provider.warnings(date(2026, 1, 1))
    assert _rate(2027, 10, 6, 2, 0) == 'peak'


def test_deepseek_prices_cache_hits_from_its_own_usage_field():
    model = _deepseek()
    usage = model.usage({'prompt_tokens': 1_000_000, 'prompt_cache_hit_tokens': 400_000, 'completion_tokens': 100_000})
    assert usage == Usage(input=600_000, output=100_000, cache_read=400_000)
    off_peak = model.charge(usage, datetime(2026, 10, 17, 2, 0, tzinfo=UTC))
    assert off_peak.usd == pytest.approx(0.6 * 0.15 + 0.1 * 0.60 + 0.4 * 0.003)


def test_typesafe_prices_input_only():
    model = config.load().decision.model
    charge = model.charge(model.usage({'input_tokens': 2_000_000}), datetime(2026, 10, 17, tzinfo=UTC))
    assert charge.usd == pytest.approx(2 * 0.042)


# ---- loading and resolving -------------------------------------------------------------

def _write(folder, name, data):
    (folder / f'{name}.json').write_text(json.dumps(data))
    return folder


STANDARD = {'kind': 'standard', 'api': 'anthropic', 'base_url': 'https://example.test', 'key_env': 'EXAMPLE_KEY',
            'models': {'m1': {'input': 3, 'output': 15, 'cache_read': 0.3}}}


def test_standard_provider_and_cache_price_defaults(tmp_path, monkeypatch):
    monkeypatch.setenv('EXAMPLE_KEY', 'secret')
    model = providers.resolve(providers.load(_write(tmp_path, 'example', STANDARD)), 'example/m1')
    assert model.key == 'secret' and model.ref == 'example/m1'
    assert model.identity() == {'format': 'anthropic', 'base_url': 'https://example.test', 'model': 'm1'}
    usage = model.usage({'input_tokens': 10**6, 'output_tokens': 10**6, 'cache_read_input_tokens': 10**6,
                         'cache_creation_input_tokens': 10**6})
    charge = model.charge(usage, datetime(2026, 10, 17, tzinfo=UTC))
    assert charge.usd == pytest.approx(3 + 15 + 0.3 + 3)        # a cache write left out costs the input price
    assert charge.basis['rate'] == 'standard'


@pytest.mark.parametrize('change, message', [
    ({'kind': 'flat'}, 'kind must be one of'),
    ({'api': 'grpc'}, 'unknown api'),
    ({'rate_limit': 5}, 'unknown field rate_limit'),
    ({'models': {'m1': {'input': 3, 'outptu': 15}}}, 'models.m1: missing output'),
    ({'models': {'m1': {'input': -1, 'output': 15}}}, 'models.m1.input: expected a number'),
    ({'models': {}}, 'at least one model'),
])
def test_provider_files_are_checked(tmp_path, change, message):
    with pytest.raises(ValueError, match=message):
        providers.load(_write(tmp_path, 'example', {**STANDARD, **change}))


def test_unknown_provider_or_model(tmp_path):
    catalog = providers.load(_write(tmp_path, 'example', STANDARD))
    with pytest.raises(ValueError, match='unknown provider'):
        providers.resolve(catalog, 'other/m1')
    with pytest.raises(ValueError, match='no model'):
        providers.resolve(catalog, 'example/m2')


def test_overrides_choose_another_model_with_its_own_prices(tmp_path):
    folder = _write(tmp_path, 'example', STANDARD)
    for path in (config.ROOT / 'providers').glob('*.json'):
        (folder / path.name).write_text(path.read_text())
    settings = config.load(overrides={'reasoning.model': 'example/m1', 'reasoning.key': 'k'}, provider_files=folder)
    assert settings.reasoning.model.ref == 'example/m1' and settings.reasoning.model.key == 'k'
    assert settings.reasoning.json_repairs == 2
    assert settings.decision.model.ref == 'typesafe/jev-1.14.0'


def test_live_clients_are_built_from_the_configured_models():
    from appeals.graph import endpoints
    settings = config.load()
    decision = endpoints.decision_model(settings.decision.model)
    reasoning = endpoints.reasoning_model(settings.reasoning)
    assert decision.identity()['format'] == 'typesafe' and reasoning.identity()['model'] == 'deepseek-flash'
