from acce_optimizer.core.learning import LearnedPreference, LearnedRouteEstimate, reset_preference_on_change
from acce_optimizer.core.routing_policy import RoutingPolicy, cloud_override_allowed, next_preference_observation_count, preference_is_promotable


def estimate(route, quality):
    return LearnedRouteEstimate(
        route_id=route,
        sample_count=10,
        confidence=0.95,
        success_rate=0.98,
        quality_score=quality,
        latency_p50=100,
        latency_p95=150,
        context_growth=0.1,
        quota_consumption=0.1,
        fallback_rate=0.01,
        retry_rate=0.01,
    )


def test_default_preference_learning_requires_odd_observations_and_agreement():
    policy = RoutingPolicy(preference_mode="learned")
    preference = LearnedPreference(
        "user", "coding", "local", "learned", 0.9, 5, 0.95, agreement_rate=0.9
    )
    assert preference_is_promotable(
        preference, demand_similarity=0.9, task_similarity=0.9, policy=policy
    )


def test_cloud_override_uses_configurable_quality_advantage():
    policy = RoutingPolicy(cloud_override_threshold_normal=0.30)
    local = estimate("local", 0.75)
    cloud = estimate("cloud", 1.00)
    assert cloud_override_allowed(
        local_estimate=local,
        cloud_estimate=cloud,
        urgency="normal",
        policy=policy,
    )


def test_preference_observation_thresholds_grow_by_two():
    policy = RoutingPolicy()
    assert next_preference_observation_count(0, policy) == 5
    assert next_preference_observation_count(4, policy) == 5
    assert next_preference_observation_count(5, policy) == 7
    assert next_preference_observation_count(6, policy) == 7
    assert next_preference_observation_count(7, policy) == 9
    assert next_preference_observation_count(8, policy) == 9


def test_preference_promotion_defaults_are_configurable():
    policy = RoutingPolicy(preference_mode="learned")
    assert policy.preference_observation_count == 5
    assert policy.preference_agreement_threshold == 0.85
    assert policy.preference_confidence_threshold == 0.85
    assert policy.demand_similarity_threshold == 0.80
    assert policy.task_similarity_threshold == 0.80

    custom = RoutingPolicy(
        preference_mode="learned",
        preference_observation_count=7,
        preference_agreement_threshold=0.90,
        preference_confidence_threshold=0.90,
        demand_similarity_threshold=0.85,
        task_similarity_threshold=0.85,
    )
    assert custom.preference_observation_count == 7
    assert custom.preference_agreement_threshold == 0.90
    assert custom.preference_confidence_threshold == 0.90
    assert custom.demand_similarity_threshold == 0.85
    assert custom.task_similarity_threshold == 0.85


def test_preference_promotion_checks_odd_checkpoints_until_promoted():
    policy = RoutingPolicy(preference_mode="learned")
    common = dict(
        scope="user",
        task_signature="coding",
        preferred_route="local",
        mode="learned",
        confidence=0.85,
        success_rate=0.95,
        agreement_rate=0.85,
    )
    assert preference_is_promotable(
        LearnedPreference(**common, evidence_count=5),
        demand_similarity=0.80,
        task_similarity=0.80,
        policy=policy,
    )
    assert not preference_is_promotable(
        LearnedPreference(**{**common, "agreement_rate": 0.84}, evidence_count=7),
        demand_similarity=0.80,
        task_similarity=0.80,
        policy=policy,
    )


def test_preference_confidence_threshold_is_independent_and_configurable():
    policy = RoutingPolicy(preference_mode="learned", preference_confidence_threshold=0.90)
    preference = LearnedPreference(
        "user", "coding", "local", "learned", 0.85, 5, 0.95, agreement_rate=0.90
    )
    assert not preference_is_promotable(
        preference, demand_similarity=0.90, task_similarity=0.90, policy=policy
    )


def test_effective_preference_change_resets_learning_cycle_to_start():
    preference = LearnedPreference(
        "user", "coding", "local", "learned", 0.95, 9, 0.98, agreement_rate=0.95
    )
    assert reset_preference_on_change(preference, "local") == preference
    reset = reset_preference_on_change(preference, "cloud")
    assert reset.preferred_route == "cloud"
    assert reset.evidence_count == 0
    assert next_preference_observation_count(reset.evidence_count, RoutingPolicy()) == 5
    assert reset.confidence == 0.0
    assert reset.success_rate == 0.0
    assert reset.agreement_rate == 0.0
    assert reset.reset_generation == 1
