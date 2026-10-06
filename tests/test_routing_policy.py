from acce_optimizer.core.learning import LearnedPreference, LearnedRouteEstimate
from acce_optimizer.core.routing_policy import RoutingPolicy, cloud_override_allowed, preference_is_promotable


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
