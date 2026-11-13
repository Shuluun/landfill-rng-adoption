"""Descriptive summaries with explicit completeness and asset-time boundaries."""
from datetime import date
from .analysis import windows,month_interval


def window_summary(observations,year):
    """Publish parts when present; never create a primary comparison from missingpost."""
    win=windows(year)
    pre=[observations.get(y) for y in win['background_years']]
    post=[observations.get(y) for y in win['main_post_years']]
    event=observations.get(year)
    pre_n=sum(x is not None for x in pre);post_n=sum(x is not None for x in post)
    a=sum(pre)/3 if pre_n==3 else None
    b=sum(post)/2 if post_n==2 else None
    pct=100*(b/a-1) if a is not None and a>0 and b is not None else None
    event_pct=100*(event/a-1) if a is not None and a>0 and event is not None else None
    return dict(anchor_year=year,**win,pre_nonmissing=pre_n,post_nonmissing=post_n,pre_mean_MWh=a,post_mean_MWh=b,
        event_year_MWh=event,plant_only_percent_change=pct,
        event_year_vs_pre_percent=event_pct,
        event_year_statistic_role='SEPARATE_DESCRIPTIVE_EVENT_YEAR_NOT_PRIMARY_POST_COMPARISON',
        complete3plus2=pre_n==3 and post_n==2,landfill_assigned_MWh=None)


def retirement_gap(anchor,lo,hi,background_start_year):
    assert lo<=hi
    return dict(retirement_low=lo.isoformat(),retirement_high=hi.isoformat(),
        gap_min_days=(anchor-hi).days,gap_max_days=(anchor-lo).days,
        entirely_before_rng_registration=hi<anchor,
        entirely_before_background=hi<date(background_start_year,1,1))


def listed_asset_scopes(site,anchor,inventory_path):
    """Retired subsets and registered projects remain separate from all-site coverage."""
    rows=[];retired=[];background=anchor.year-3
    for u in site['reported_unit_rows']:
        if u['fuel']!='LFG' or u['sheet']!='Retired' or not u.get('retirement_month') or not u.get('retirement_year'):continue
        lo,hi=month_interval(int(u['retirement_year']),int(u['retirement_month']))
        retired.append((u,lo,hi))
        rows.append(dict(landfill_id=site['landfill_id'],scope='SINGLE_LISTED_LFG_GENERATOR',asset_ids=[u['id']],
            source=inventory_path,source_sheet=u['sheet'],source_excel_rows=[u['source_row']],
            scope_limit='Candidateplantlistedunit; not allsite coverage',**retirement_gap(anchor,lo,hi,background)))
    if retired:
        lo=max(x[1] for x in retired);hi=max(x[2] for x in retired)
        rows.append(dict(landfill_id=site['landfill_id'],scope='LISTED_LFG_RETIRED_SUBSET_LAST_REPORTED_RETIREMENT',
            asset_ids=[x[0]['id'] for x in retired],source=inventory_path,source_sheet='Retired',source_excel_rows=[x[0]['source_row'] for x in retired],
            scope_limit='Excludes currentlyOperating andNG rows. Not the last generator at whole site.',**retirement_gap(anchor,lo,hi,background)))
    for p in site['registry_electricity']:
        if not p.get('shutdown'):continue
        d=date.fromisoformat(p['shutdown'][:10])
        rows.append(dict(landfill_id=site['landfill_id'],scope='REGISTERED_ELECTRIC_PROJECT_CLOSURE',asset_ids=[p['project_id']],
            source='data/raw/2026-10-06_public_inputs/lmopdata.xlsx',source_sheet='LMOP Database',source_excel_rows=[p['row']],
            scope_limit='Projectadministrative event, not generator physical retirement',**retirement_gap(anchor,d,d,background)))
    return rows
