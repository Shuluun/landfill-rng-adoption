"""Fixed windows, plant observations and limited sensitivity analysis."""
from datetime import date
import calendar


def month_interval(year, month):
    return date(year, month, 1), date(year, month, calendar.monthrange(year, month)[1])


def windows(year):
    return {'background_years': list(range(year-3, year)), 'event_year': year, 'main_post_years': [year+1, year+2]}


def configured_windows(year, config):
    assert config['event_year_separate'] and config['anchor'] == 'frozen_registry_date'
    return {'background_years': list(range(year-config['background_complete_years'], year)),
            'event_year': year, 'main_post_years': list(range(year+1, year+1+config['post_complete_years']))}


def date_and_asset_checks(anchor, registry, units, config, issuer_month=None, issuer_evidence=None):
    """Reported event precision and explicitly limited asset scopes, not causality."""
    win = configured_windows(anchor.year, config)
    start = date(win['background_years'][0], 1, 1)
    scopes = []
    dated = []
    for sheet, row_no, r in units:
        if r.get('Retirement Year') and r.get('Retirement Month'):
            lo, hi = month_interval(int(r['Retirement Year']), int(r['Retirement Month']))
            dated.append((lo, hi))
            scopes.append({'scope': 'single_listed_generator', 'asset_ids': [str(r['Generator ID'])],
                           'reported_end_interval': [lo.isoformat(), hi.isoformat()], 'source_sheet': sheet, 'source_rows': [row_no]})
    if dated and len(dated) == len(units):
        lo, hi = max(pair[0] for pair in dated), max(pair[1] for pair in dated)
        scopes.append({'scope': 'all_listed_generators_last_retirement',
                       'asset_ids': [str(r['Generator ID']) for _, _, r in units],
                       'reported_end_interval': [lo.isoformat(), hi.isoformat()],
                       'source_rows': [n for _, n, _ in units],
                       'limitation': 'Only this listed set; not a proven complete site asset inventory.'})
    for n, r in registry:
        if r['Project Type Category'] == 'Electricity' and r['Project Shutdown Date'] is not None:
            d = r['Project Shutdown Date'].date()
            scopes.append({'scope': 'registered_electricity_project', 'asset_ids': [str(r['Project ID'])],
                           'reported_end_interval': [d.isoformat(), d.isoformat()], 'source_rows': [n],
                           'limitation': 'Project event, not an interchangeable generator event.'})
    for scope in scopes:
        lo, hi = map(date.fromisoformat, scope['reported_end_interval'])
        scope.update(gap_days_to_registered_rng=[(anchor-hi).days, (anchor-lo).days],
                     entirely_before_background=hi < start,
                     entirely_before_rng_registration=hi < anchor,
                     end_event_within_generation_data_years=config['data_first_year'] <= hi.year <= config['data_last_year'])
    result = {'status': 'LIMITED_DATE_CHECK_NOT_OPERATING_PATHWAY_CLASSIFICATION',
              'fixed_registry_anchor': {'date': anchor.isoformat(), **win},
              'calendar_windows_unchanged_under_supported_rng_dates': None,
              'asset_scope_scenarios': scopes, 'site_pathway': 'UNDETERMINED',
              'interpretation': 'Different reported asset scopes/precision are shown explicitly. No complete site withdrawal, precise operating day, distribution over dates or causal effect is inferred.'}
    if dated:
        lo, hi = dated[0]
        result['reported_unit_retirement_interval'] = [lo.isoformat(), hi.isoformat()]
        result['days_between_reported_retirement_month_and_registered_rng_date'] = [(anchor-hi).days, (anchor-lo).days]
    if issuer_month:
        year, month = map(int, issuer_month.split('-'))
        lo, hi = month_interval(year, month)
        alt = configured_windows(year, config)
        result['issuer_month_alternative'] = {'interval': [lo.isoformat(), hi.isoformat()], **alt, 'evidence': issuer_evidence,
                                            'interpretation': 'Supplemental reported month, not a replacement primary anchor.'}
        result['calendar_windows_unchanged_under_supported_rng_dates'] = alt == win
    return result


def plant_series(raw, pid, scope, win_config, anchor_year):
    """One exact fuel/prime-mover record per plant-year. Never allocate to a landfill."""
    from decimal import Decimal
    indexed = {}
    for source_row, r in enumerate(raw['response']['data'], 1):
        if str(r['plantCode']) != str(pid) or r['fuel2002'] != scope['fuel'] or r['primeMover'] != scope['prime_mover']:
            continue
        year = int(r['period'])
        if year in indexed:
            raise ValueError(f'Duplicate exact plant/fuel/prime-mover/year record: {pid}, {year}; no silent summation')
        aliases = {'megawatthours': 'MWh', 'MWh': 'MWh'}
        assert r['generation-units'] == scope['raw_units'] and aliases.get(r['generation-units']) == scope['units']
        indexed[year] = (source_row, r)
    win = configured_windows(anchor_year, win_config)
    result = []
    for year in range(win_config['data_first_year'], win_config['data_last_year']+1):
        item = indexed.get(year)
        value, reported, raw_row = None, None, None
        status = 'record_missing'
        if item:
            raw_row, r = item
            reported = r.get('generation')
            if reported is None or str(reported).strip() == '':
                status = 'value_missing'
            else:
                number = Decimal(str(reported))
                if not number.is_finite():
                    raise ValueError('Nonfinite generation value')
                value = float(number)
                status = 'positive' if number > 0 else 'negative' if number < 0 else 'zero'
        period = 'background' if year in win['background_years'] else 'registration_year' if year == anchor_year else 'main_post' if year in win['main_post_years'] else 'other'
        result.append({'plant_code': pid, 'year': year, 'fuel': scope['fuel'], 'prime_mover': scope['prime_mover'],
                       'net_generation_MWh': value, 'reported_value': reported, 'record_status': status,
                       'period_role': period, 'raw_json_record_1based': raw_row,
                       'measurement_or_imputation_status': 'UNRESOLVED_AT_RECORD_LEVEL',
                       'landfill_assigned_MWh': None, 'scope': 'EIA_PLANT_ONLY_PROVISIONAL_LANDFILL_LINK'})
    return result


def comparison_eligibility(series, asset_relation_verified=False, comparable=False):
    """Five complete calendar years are necessary, but not sufficient, for comparison."""
    selected = {role: [r for r in series if r['period_role'] == role] for role in ['background', 'main_post']}
    available = {role: sum(r['net_generation_MWh'] is not None for r in rows) for role, rows in selected.items()}
    complete = available == {'background': 3, 'main_post': 2}
    eligible = complete and asset_relation_verified and comparable
    pre = sum(r['net_generation_MWh'] for r in selected['background']) / 3 if eligible else None
    post = sum(r['net_generation_MWh'] for r in selected['main_post']) / 2 if eligible else None
    return {'pre_nonmissing_years': available['background'], 'post_nonmissing_years': available['main_post'],
            'five_year_values_complete': complete, 'asset_relation_verified': asset_relation_verified,
            'measurement_scope_comparable': comparable, 'eligible': eligible,
            'pre_mean_MWh': pre, 'post_mean_MWh': post,
            'post_pre_ratio': post/pre if eligible and pre > 0 else None,
            'reason': 'Requires complete three-pre/two-post values plus time-valid asset relation and comparable net-generation scope; ratio additionally requires positive pre mean.'}


def public_event_date_check(supplement, anchor, config):
    """Compare the supported module-month year without promoting it to plant start."""
    event = next(e for e in supplement['events'] if e['event_type'] == 'MODULE_OPERATION_SINCE_REPORTED_MONTH')
    year = date.fromisoformat(event['date_low']).year
    return {'comparison': 'Module operating-month year versus frozen registration year, different objects/events',
            'module_event': event, 'registry_anchor': anchor.isoformat(),
            'calendar_windows_equal_for_these_two_years': configured_windows(year, config) == configured_windows(anchor.year, config),
            'primary_anchor_changed': False,
            'acceptance_and_asof_dates_are_valid_first_start_alternatives': False,
            'full_plant_first_gas_or_commercial_date_known': False,
            'interpretation': 'March2022 and April2022 fall in the same calendar year; no annual-window change in this limited check. January2023 acceptance and April2023 asof operation cannot replace first startup. No production effect is estimable from missing plant-year rows.'}


def event_annotation(event):
    """Keep year-only source precision visible instead of inventing a January event."""
    lo, hi = date.fromisoformat(event['date_low']), date.fromisoformat(event['date_high'])
    if 'year' in event.get('precision','').lower() and lo.year == hi.year and lo != hi:
        return f'{lo.year} (year only)'
    if lo == hi:
        return lo.isoformat()
    if (lo.year,lo.month) != (hi.year,hi.month):
        return lo.strftime('%Y-%m')+' to '+hi.strftime('%Y-%m')
    return lo.strftime('%Y-%m')


def timeline_plot(path, name, pid, fid, registry, units, anchor, windows_config, public_events=()):
    """Plot month intervals as intervals, without inventing exact retirement days."""
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    import matplotlib.dates as mdates
    win = configured_windows(anchor.year, windows_config)
    fig, ax = plt.subplots(figsize=(11, 4.6 + .35*len(public_events) + .2*max(0,len(units)-3)), constrained_layout=True)
    labels = []
    for i, (sheet, _, r) in enumerate(units):
        label = 'Generator ' + str(r['Generator ID']) + (' [Sep2026 Operating tab only]' if sheet == 'Operating' else '')
        labels.append(label)
        if r.get('Retirement Year'):
            lo, hi = month_interval(int(r['Retirement Year']), int(r['Retirement Month']))
            ax.plot([lo, hi], [i, i], linewidth=5, color='#333333', solid_capstyle='butt')
            ax.annotate(f'{lo.year}-{lo.month:02d}', (hi, i), xytext=(5, 6), textcoords='offset points', fontsize=8)
    i = len(labels)
    for _, r in registry:
        if r['Project Type Category'] == 'Electricity' and r['Project Shutdown Date'] is not None:
            labels.append('Registered power closure')
            ax.plot(r['Project Shutdown Date'].date(), i, marker='o', color='#555555')
            i += 1
    labels.append('Registered RNG start')
    ax.plot(anchor, i, marker='D', color='#8c4b15')
    for event in public_events:
        i += 1
        labels.append(event['label'])
        lo, hi = date.fromisoformat(event['date_low']), date.fromisoformat(event['date_high'])
        ax.plot([lo, hi], [i, i], color='#2d7565', linewidth=4)
        ax.plot(hi, i, marker='>' if event['event_type'].endswith('AS_OF') else '|', color='#2d7565')
        ax.annotate(event_annotation(event), (hi, i), xytext=(4, 6), textcoords='offset points', fontsize=8)
    for lo, hi, label, color in [
        (date(win['background_years'][0], 1, 1), date(anchor.year, 1, 1), 'Background', '#c4d5e7'),
        (date(anchor.year, 1, 1), date(anchor.year+1, 1, 1), 'Registration year', '#ead7a4'),
        (date(anchor.year+1, 1, 1), date(win['main_post_years'][-1]+1, 1, 1), 'Main comparison', '#c8ddca')]:
        ax.axvspan(lo, hi, color=color, alpha=.65, label=label)
    # Earlier project closures must not be silently clipped by a unit-only x range.
    earliest = min([int(r['Retirement Year']) for _, _, r in units if r.get('Retirement Year')]
                   + [r['Project Shutdown Date'].year for _, r in registry if r['Project Type Category'] == 'Electricity' and r['Project Shutdown Date'] is not None]
                   + [win['background_years'][0]])
    ax.set_xlim(date(earliest-1, 1, 1), date(max(windows_config['data_last_year']+1, win['main_post_years'][-1]+1), 4, 1))
    ax.set_yticks(range(len(labels)), labels)
    ax.xaxis.set_major_locator(mdates.YearLocator(1 if anchor.year-earliest < 6 else 2))
    ax.xaxis.set_major_formatter(mdates.DateFormatter('%Y'))
    ax.set_title(name + ': reported events and the fixed observation window', fontsize=11)
    ax.set_xlabel(f'Plant lead {pid}; LMOP site {fid}. Retirement months: Sep 2026 inventory; registry dates: Sep 2024. Link provisional.', fontsize=8)
    ax.legend(loc='upper left' if public_events else 'upper right', fontsize=8, frameon=False)
    ax.grid(axis='x', alpha=.2)
    ax.spines[['top', 'right']].set_visible(False)
    fig.savefig(path, dpi=150)
    plt.close(fig)
