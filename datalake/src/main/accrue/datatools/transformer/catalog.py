import enum

from accrue.datatools.transformer.interface import Transformer
from accrue.datatools.transformer._audit_logs import AuditLogsTransformer
from accrue.datatools.transformer._checkout_payments import CheckoutPaymentsTransformer
from accrue.datatools.transformer._payment_events import PaymentEventsTransformer


class TransformerCatalog(enum.Enum):
    AUDIT_LOGS = AuditLogsTransformer
    CHECKOUT_PAYMENTS = CheckoutPaymentsTransformer
    PAYMENT_EVENTS = PaymentEventsTransformer

    def __call__(self, **kwargs) -> Transformer:
        return self.value(**kwargs)


__all__ = ["TransformerCatalog"]
