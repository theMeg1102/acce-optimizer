"""ACCE adaptive routing implementation."""

from .errors import ContractValidationError
from .ollama_measurement import OllamaMeasurementClient
from .registry import CapabilityRegistry, validate_production_registry
from .runtime import ContextPolicy, DecisionService, EconomicPolicy, QuotaPolicy, runtime_contract

try:
    from importlib.metadata import version as _distribution_version
except ImportError:  # pragma: no cover
    _distribution_version = None

if _distribution_version is None:
    __version__ = "0.1.0"
else:
    try:
        __version__ = _distribution_version("acce-optimizer")
    except Exception:  # pragma: no cover
        __version__ = "0.1.0"

__all__ = [
    "ContextPolicy",
    "CapabilityRegistry",
    "ContractValidationError",
    "OllamaMeasurementClient",
    "DecisionService",
    "EconomicPolicy",
    "QuotaPolicy",
    "__version__",
    "runtime_contract",
    "validate_production_registry",
]
