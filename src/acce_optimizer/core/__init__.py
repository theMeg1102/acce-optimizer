"""ACCE adaptive routing implementation."""

from .errors import ContractValidationError
from .ollama_measurement import OllamaMeasurementClient
from .registry import CapabilityRegistry, validate_production_registry
from .runtime import ContextPolicy, DecisionService, EconomicPolicy, QuotaPolicy, runtime_contract

try:\n    from importlib.metadata import version as _distribution_version\nexcept ImportError:  # pragma: no cover\n    _distribution_version = None\n\nif _distribution_version is None:\n    __version__ = "0.1.0"\nelse:\n    try:\n        __version__ = _distribution_version("acce-optimizer")\n    except Exception:  # pragma: no cover\n        __version__ = "0.1.0"

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
