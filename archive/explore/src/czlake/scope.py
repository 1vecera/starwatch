"""Daniel's active research scope, separate from the retained official archive."""

TOP_CITY_RANK = 10
ACTIVE_PERSON_SQL = f"""select distinct person_id from marts.active_city_2026_candidates
    where population_rank <= {TOP_CITY_RANK} and eligible_current_ballot"""
ACTIVE_LEADER_SQL = f"""select distinct leader_person_id from marts.city_2026_contenders
    where population_rank <= {TOP_CITY_RANK}"""
