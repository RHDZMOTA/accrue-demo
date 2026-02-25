import enum
import os

from accrue.configs.contracts.interface import Contract


# ---------------------------------------------------------------------------
# ContractCatalog — auto-discovers JSON contracts from the contracts/ directory
# ---------------------------------------------------------------------------

_CONTRACTS_DIR = os.environ.get(
    "CONTRACTS_DIR",
    default=os.path.dirname(__file__),
)


def _load_all_contracts() -> dict[str, str]:
    """Return a mapping of contract_name → absolute JSON path."""
    if not os.path.isdir(_CONTRACTS_DIR):
        return {}
    return {
        f[:-5]: os.path.join(_CONTRACTS_DIR, f)
        for f in os.listdir(_CONTRACTS_DIR)
        if f.endswith(".json")
    }

class ContractCatalogMixin:
    def load(self) -> Contract:
        """Load and parse the JSON contract for this table."""
        contracts = _load_all_contracts()
        path = contracts.get(self.value)
        if path is None:
            raise FileNotFoundError(
                f"No contract JSON found for '{self.value}' in {_CONTRACTS_DIR}"
            )
        return Contract.from_json(path)

    @classmethod
    def all(cls) -> list[Contract]:
        """Load all contracts."""
        return [member.load() for member in cls]


class ContractBronzeCatalog(ContractCatalogMixin, enum.Enum):
    PAYMENT_EVENTS = "contract_bronze_payment_events"
    CHECKOUT_PAYMENTS = "contract_bronze_checkout_payments"
    AUDIT_LOGS = "contract_bronze_audit_logs"


class ContractSilverCatalog(ContractCatalogMixin,enum.Enum):
    PAYMENT_EVENTS = "contract_silver_payment_events"
    CHECKOUT_PAYMENTS = "contract_silver_checkout_payments"
    AUDIT_LOGS = "contract_silver_audit_logs"


__all__ = [
    "ContractBronzeCatalog",
    "ContractSilverCatalog"
]
